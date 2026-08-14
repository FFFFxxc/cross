from __future__ import annotations

import asyncio
import mimetypes
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import quote

import certifi
import httpx


@dataclass(frozen=True)
class MaxConfig:
    token: str
    channel: str
    api_base: str = "https://platform-api2.max.ru"
    notify: bool = True
    disable_link_preview: bool = False


@dataclass(frozen=True)
class MaxAttachment:
    type: str
    payload: dict

    def as_dict(self) -> dict:
        return {"type": self.type, "payload": self.payload}


class MaxApiError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, code=None):
        super().__init__(message)
        self.status = status
        self.code = code


class AmbiguousMaxSendError(RuntimeError):
    """MAX may have accepted the message; automatic retry could duplicate it."""


Sleep = Callable[[float], Awaitable[None]]


def _ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=certifi.where())
    certificate = Path(__file__).resolve().parent / "certs" / "russian-trusted-root-ca.pem"
    context.load_verify_locations(cafile=str(certificate))
    return context


class MaxClient:
    def __init__(
        self,
        config: MaxConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
    ):
        self.config = config
        self._sleep = sleep
        self._chat_id: int | None = None
        self._client = httpx.AsyncClient(
            transport=transport,
            verify=_ssl_context(),
            timeout=httpx.Timeout(90.0, connect=20.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    async def _json(response: httpx.Response) -> dict:
        try:
            value = response.json()
        except ValueError:
            value = {"message": response.text[:300]}
        return value if isinstance(value, dict) else {"value": value}

    async def _api(self, method: str, path: str, **kwargs) -> dict:
        url = f"{self.config.api_base.rstrip('/')}{path}"
        headers = {"Authorization": self.config.token, **kwargs.pop("headers", {})}
        try:
            response = await self._client.request(
                method,
                url,
                headers=headers,
                **kwargs,
            )
        except httpx.RequestError as exc:
            raise MaxApiError(f"MAX недоступен: {exc.__class__.__name__}") from exc
        data = await self._json(response)
        if response.is_error or data.get("success") is False:
            raise MaxApiError(
                str(data.get("message") or data.get("error") or f"HTTP {response.status_code}"),
                response.status_code,
                data.get("code"),
            )
        return data

    async def resolve_channel(self) -> int:
        if self._chat_id is not None:
            return self._chat_id
        if self.config.channel.lstrip("-").isdigit():
            self._chat_id = int(self.config.channel)
            return self._chat_id
        data = await self._api("GET", f"/chats/{quote(self.config.channel, safe='')}")
        chat_id = data.get("chat_id")
        if chat_id is None:
            raise MaxApiError("MAX не вернул chat_id публичного канала")
        self._chat_id = int(chat_id)
        return self._chat_id

    async def discover_channels(self) -> list[dict]:
        """Return official Bot API channel IDs seen in bot_added events."""
        data = await self._api(
            "GET",
            "/updates",
            params={"limit": "1000", "timeout": "0", "types": "bot_added"},
        )
        chat_ids = {
            int(update["chat_id"])
            for update in data.get("updates", [])
            if update.get("is_channel") and update.get("chat_id") is not None
        }
        channels = []
        for chat_id in sorted(chat_ids):
            chat = await self._api("GET", f"/chats/{chat_id}")
            if chat.get("type") != "channel" or chat.get("status") != "active":
                continue
            membership = await self._api(
                "GET",
                f"/chats/{chat_id}/members/me",
            )
            permissions = list(membership.get("permissions") or [])
            channels.append(
                {
                    "chat_id": int(chat.get("chat_id", chat_id)),
                    "title": str(chat.get("title") or "без названия"),
                    "link": str(chat.get("link") or ""),
                    "is_admin": bool(membership.get("is_admin")),
                    "can_write": bool(
                        {"write", "post_edit_delete_message"}.intersection(
                            permissions
                        )
                    ),
                    "permissions": permissions,
                }
            )
        return channels

    async def upload(self, path: Path, media_type: str) -> MaxAttachment:
        slot = await self._api("POST", "/uploads", params={"type": media_type})
        upload_url = slot.get("url")
        if not upload_url:
            raise MaxApiError("MAX не вернул URL загрузки")
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        try:
            with path.open("rb") as stream:
                response = await self._client.post(
                    str(upload_url),
                    files={"data": (path.name, stream, mime_type)},
                )
        except httpx.RequestError as exc:
            raise MaxApiError(f"Не удалось загрузить файл в MAX: {exc}") from exc
        uploaded = await self._json(response)
        if response.is_error:
            raise MaxApiError(
                str(uploaded.get("message") or f"MAX upload HTTP {response.status_code}"),
                response.status_code,
                uploaded.get("code"),
            )
        if media_type == "image" and uploaded.get("photos"):
            return MaxAttachment("image", {"photos": uploaded["photos"]})
        token = (
            uploaded.get("token")
            or (uploaded.get("payload") or {}).get("token")
            or (uploaded.get("retval") or {}).get("token")
            or slot.get("token")
        )
        if not token:
            raise MaxApiError("MAX не вернул токен загруженного файла")
        return MaxAttachment(media_type, {"token": token})

    async def send(self, text_html: str, attachments: list[MaxAttachment]) -> str:
        chat_id = await self.resolve_channel()
        send_chat_id = chat_id
        tried_positive_channel_id = False
        payload = {
            "text": text_html or None,
            "attachments": [attachment.as_dict() for attachment in attachments] or None,
            "notify": self.config.notify,
            "format": "html",
        }
        last_error: MaxApiError | None = None
        for delay in (0, 1, 2, 4, 8):
            if delay:
                await self._sleep(delay)
            try:
                response = await self._client.post(
                    f"{self.config.api_base.rstrip('/')}/messages",
                    params={
                        "chat_id": str(send_chat_id),
                        "disable_link_preview": str(
                            self.config.disable_link_preview
                        ).lower(),
                    },
                    json=payload,
                    headers={"Authorization": self.config.token},
                )
            except httpx.RequestError as exc:
                raise AmbiguousMaxSendError(
                    "Соединение оборвалось во время отправки в MAX"
                ) from exc
            data = await self._json(response)
            if response.is_error or data.get("success") is False:
                last_error = MaxApiError(
                    str(data.get("message") or data.get("error") or f"HTTP {response.status_code}"),
                    response.status_code,
                    data.get("code"),
                )
                if last_error.code == "attachment.not.ready":
                    continue
                if (
                    400 <= response.status_code < 500
                    and str(last_error).strip().lower() == "chat not found"
                    and send_chat_id < 0
                    and not tried_positive_channel_id
                ):
                    # MAX currently reports signed channel IDs in bot_added and
                    # GET /chats, while POST /messages may require its absolute
                    # value. A definite 4xx means the first request was not sent.
                    send_chat_id = abs(send_chat_id)
                    tried_positive_channel_id = True
                    continue
                raise last_error
            message = data.get("message") or {}
            body = message.get("body") or {}
            mid = body.get("mid") or message.get("id") or data.get("message_id")
            if mid is None:
                raise AmbiguousMaxSendError(
                    "MAX принял запрос, но не вернул идентификатор сообщения"
                )
            self._chat_id = send_chat_id
            return str(mid)
        assert last_error is not None
        raise last_error
