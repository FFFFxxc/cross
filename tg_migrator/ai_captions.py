from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import os
import re
import socket
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .previews import capture_preview
from .selection import sanitize_message_text
from .state import MigrationState, QueueItem


DEFAULT_AI_PROMPT = (
    "Ты редактор русскоязычного аниме-паблика. Внимательно посмотри на "
    "изображение или кадр из видео и придумай одну короткую естественную "
    "подпись строго по его содержанию. Можно добавить лёгкую эмоцию или шутку, "
    "но нельзя выдумывать имена, названия аниме и факты, которых не видно. "
    "Не пиши ссылки, рекламу, хэштеги, призывы подписаться, кавычки и слова "
    "«нейросеть» или «изображение». Верни только готовую подпись на русском."
)
_AAD = b"desiree-ai-provider-v1"
_URL_RE = re.compile(r"(?i)https?://\S+")
_HASHTAG_RE = re.compile(r"(?<!\w)#[\wА-Яа-яЁё]+", re.UNICODE)


class AiCaptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class AiProvider:
    index: int
    base_url: str
    api_key: str
    model: str

    @property
    def label(self) -> str:
        return f"{self.index}:{self.model}"


def _secret_key(secret: str) -> bytes:
    if not secret:
        raise ValueError("Секрет шифрования AI-ключей не задан.")
    parsed = urlparse(secret)
    material = unquote(parsed.password) if parsed.password else secret
    return hashlib.sha256(material.encode("utf-8")).digest()


def encrypt_secret(value: str, secret: str) -> str:
    if not value:
        raise ValueError("API-ключ не может быть пустым.")
    nonce = os.urandom(12)
    encrypted = AESGCM(_secret_key(secret)).encrypt(
        nonce,
        value.encode("utf-8"),
        _AAD,
    )
    payload = base64.urlsafe_b64encode(nonce + encrypted).decode("ascii").rstrip("=")
    return f"enc:v1:{payload}"


def decrypt_secret(value: str, secret: str) -> str:
    if not value.startswith("enc:v1:"):
        return value
    encoded = value.removeprefix("enc:v1:")
    encoded += "=" * (-len(encoded) % 4)
    try:
        raw = base64.urlsafe_b64decode(encoded)
        decrypted = AESGCM(_secret_key(secret)).decrypt(raw[:12], raw[12:], _AAD)
        return decrypted.decode("utf-8")
    except Exception as exc:
        raise AiCaptionError("Не удалось расшифровать сохранённый API-ключ.") from exc


def _chat_completions_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return normalized + "/chat/completions"


async def _resolve_public_https(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise AiCaptionError("Base URL должен быть публичным HTTPS-адресом.")
    if parsed.hostname.lower() in {"localhost", "localhost.localdomain"}:
        raise AiCaptionError("Локальные адреса запрещены.")
    try:
        literal = ipaddress.ip_address(parsed.hostname)
        addresses = [literal]
    except ValueError:
        try:
            resolved = await asyncio.to_thread(
                socket.getaddrinfo,
                parsed.hostname,
                parsed.port or 443,
                type=socket.SOCK_STREAM,
            )
        except OSError as exc:
            raise AiCaptionError("Не удалось найти сервер AI-провайдера.") from exc
        addresses = list({ipaddress.ip_address(item[4][0]) for item in resolved})
    if not addresses or any(not address.is_global for address in addresses):
        raise AiCaptionError("Внутренние и служебные адреса запрещены.")


def _response_text(data: object) -> str:
    if not isinstance(data, dict):
        return ""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return ""
    choice = choices[0]
    message = choice.get("message")
    content = message.get("content") if isinstance(message, dict) else choice.get("text")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            str(item.get("text") or "")
            for item in content
            if isinstance(item, dict) and item.get("type") in {None, "text", "output_text"}
        )
    return ""


def _clean_generated_caption(value: str, max_chars: int) -> str:
    cleaned = " ".join(value.strip().strip("`\"'«»").split())
    cleaned = _URL_RE.sub("", cleaned)
    cleaned = _HASHTAG_RE.sub("", cleaned)
    cleaned = " ".join(cleaned.split()).strip(" -–—:;,.\n")
    if len(cleaned) > max_chars:
        shortened = cleaned[: max_chars + 1]
        boundary = shortened.rfind(" ")
        cleaned = (shortened[:boundary] if boundary >= max_chars // 2 else shortened[:max_chars]).rstrip()
    if not cleaned:
        raise AiCaptionError("Модель вернула пустую подпись.")
    return cleaned


class AiCaptionClient:
    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver=_resolve_public_https,
    ):
        self._resolver = resolver
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(45.0, connect=15.0),
            follow_redirects=False,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _complete(self, provider: AiProvider, messages: list[dict], max_tokens: int) -> str:
        endpoint = _chat_completions_url(provider.base_url)
        await self._resolver(endpoint)
        common = {"model": provider.model, "messages": messages}
        variants = (
            {**common, "temperature": 0.75, "max_tokens": max_tokens},
            {**common, "max_completion_tokens": max_tokens},
        )
        response: httpx.Response | None = None
        data: object = {}
        for attempt, payload in enumerate(variants):
            try:
                response = await self._client.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {provider.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            except httpx.RequestError as exc:
                raise AiCaptionError(f"Сеть: {exc.__class__.__name__}") from exc
            try:
                data = response.json()
            except ValueError:
                data = {"message": response.text[:300]}
            if response.status_code != 400 or attempt == len(variants) - 1:
                break
        assert response is not None
        if response.is_error:
            detail = ""
            if isinstance(data, dict):
                error = data.get("error")
                detail = str(error.get("message") if isinstance(error, dict) else error or data.get("message") or "")
            raise AiCaptionError(f"HTTP {response.status_code}: {detail[:240]}".rstrip())
        text = _response_text(data)
        if not text.strip():
            raise AiCaptionError("Провайдер не вернул текст в OpenAI-совместимом формате.")
        return text

    async def test(self, provider: AiProvider) -> str:
        result = await self._complete(
            provider,
            [{"role": "user", "content": "Ответь ровно: связь есть"}],
            16,
        )
        return " ".join(result.split())[:160]

    async def generate_with_fallback(
        self,
        providers: list[AiProvider],
        *,
        image: bytes,
        mime_type: str,
        prompt: str,
        max_chars: int,
        context: str,
    ) -> tuple[str, AiProvider]:
        encoded = base64.b64encode(image).decode("ascii")
        messages = [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Контекст публикации: {context}. "
                            f"Подпись должна быть не длиннее {max_chars} символов."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                    },
                ],
            },
        ]
        errors: list[str] = []
        for provider in providers:
            try:
                raw = await self._complete(provider, messages, 120)
                return _clean_generated_caption(raw, max_chars), provider
            except Exception as exc:
                errors.append(f"провайдер {provider.index}: {exc}")
        raise AiCaptionError("; ".join(errors)[:1000] or "Нет настроенных AI-провайдеров.")


def cleaned_source_text(messages) -> str:
    for message in messages:
        raw = getattr(message, "raw_text", None) or getattr(message, "message", None) or ""
        cleaned, _ = sanitize_message_text(
            raw,
            list(getattr(message, "entities", None) or []),
        )
        if cleaned.strip():
            return cleaned.strip()
    return ""


class AiCaptionService:
    def __init__(
        self,
        telegram_client,
        state: MigrationState,
        credential_secret: str,
        *,
        client: AiCaptionClient | None = None,
    ):
        self.telegram_client = telegram_client
        self.state = state
        self.credential_secret = credential_secret or "desiree-local-ai"
        self.client = client or AiCaptionClient()

    def enabled(self) -> bool:
        return (self.state.get_setting("ai_enabled", "false") or "false").lower() == "true"

    def prompt(self) -> str:
        return self.state.get_setting("ai_prompt", DEFAULT_AI_PROMPT) or DEFAULT_AI_PROMPT

    def max_chars(self) -> int:
        try:
            return min(300, max(40, int(self.state.get_setting("ai_max_chars", "140") or 140)))
        except (TypeError, ValueError):
            return 140

    def providers(self) -> list[AiProvider]:
        providers: list[AiProvider] = []
        for index in (1, 2):
            base_url = (self.state.get_setting(f"ai_provider_{index}_base_url", "") or "").strip()
            model = (self.state.get_setting(f"ai_provider_{index}_model", "") or "").strip()
            encrypted = (self.state.get_setting(f"ai_provider_{index}_api_key", "") or "").strip()
            if not (base_url and model and encrypted):
                continue
            providers.append(
                AiProvider(
                    index,
                    base_url,
                    decrypt_secret(encrypted, self.credential_secret),
                    model,
                )
            )
        return providers

    async def _messages(self, item: QueueItem):
        values = await self.telegram_client.get_messages(
            item.source,
            ids=list(item.message_ids),
        )
        return list(values) if isinstance(values, (list, tuple)) else [values]

    async def ensure_caption(
        self,
        item: QueueItem,
        messages=None,
        *,
        already_claimed: bool = False,
    ) -> QueueItem:
        if not self.enabled() or item.ai_caption_status in {"generated", "not_needed", "no_preview"}:
            return item
        if item.ai_caption_status == "processing" and not already_claimed:
            for _ in range(20):
                await asyncio.sleep(0.5)
                current = self.state.queue_item(item.id)
                if current is None or current.ai_caption_status != "processing":
                    return current or item
            return self.state.queue_item(item.id) or item
        if not already_claimed:
            claimed = self.state.claim_ai_caption(item.id)
            if claimed is None:
                return self.state.queue_item(item.id) or item
            item = claimed
        try:
            loaded_messages = list(messages) if messages is not None else await self._messages(item)
            loaded_messages = [message for message in loaded_messages if message is not None]
            if cleaned_source_text(loaded_messages):
                self.state.mark_ai_caption_not_needed(item.id)
                return self.state.queue_item(item.id) or item
            preview_data = item.preview_data
            preview_mime = item.preview_mime
            if not preview_data:
                preview = await capture_preview(self.telegram_client, loaded_messages)
                if preview is not None:
                    preview_data = preview.data
                    preview_mime = preview.mime_type
                    self.state.update_post_metadata(
                        item.id,
                        preview_data=preview.data,
                        preview_mime=preview.mime_type,
                    )
            if not preview_data or not preview_mime:
                self.state.mark_ai_caption_not_needed(item.id, "no_preview")
                return self.state.queue_item(item.id) or item
            providers = self.providers()
            if not providers:
                raise AiCaptionError("Не настроен ни один AI-провайдер.")
            caption, provider = await self.client.generate_with_fallback(
                providers,
                image=preview_data,
                mime_type=preview_mime,
                prompt=self.prompt(),
                max_chars=self.max_chars(),
                context=f"{item.content_category}, {item.media_kind}",
            )
            self.state.save_ai_caption(item.id, caption, provider.label)
        except Exception as exc:
            self.state.fail_ai_caption(item.id, f"{exc.__class__.__name__}: {exc}")
        return self.state.queue_item(item.id) or item

    async def run_once(self) -> bool:
        if not self.enabled() or not self.providers():
            return False
        item = self.state.claim_ai_caption_item()
        if item is None:
            return False
        await self.ensure_caption(item, already_claimed=True)
        return True

    async def loop(self, sleep=asyncio.sleep) -> None:
        while True:
            try:
                processed = await self.run_once()
            except Exception:
                processed = False
            await sleep(1 if processed else 10)

    async def test_provider(self, index: int) -> dict[str, object]:
        provider = next((value for value in self.providers() if value.index == index), None)
        if provider is None:
            raise AiCaptionError(f"AI-провайдер {index} настроен не полностью.")
        reply = await self.client.test(provider)
        return {"provider": index, "model": provider.model, "reply": reply}

    async def aclose(self) -> None:
        await self.client.aclose()
