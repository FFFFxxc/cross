from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import os
import re
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, urlparse

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .previews import capture_preview
from .selection import sanitize_message_text
from .state import MigrationState, QueueItem


DEFAULT_AI_PROMPT = (
    "Ты ведёшь небольшой живой аниме-мем паблик. Посмотри именно на прикреплённую "
    "картинку и напиши реакцию как обычный человек в чате: 3–9 слов, максимум "
    "одно короткое предложение. Подойдут простая шутка, узнаваемая эмоция или "
    "разговорная реплика по тому, что реально видно. Пиши разнообразно; иногда "
    "достаточно 1–3 слов или одного уместного эмодзи. Не объясняй мем, не "
    "пересказывай картинку, не используй канцелярит и шаблоны «когда…», «тот "
    "самый момент…», «вот это…», «логика…». Не называй персонажей и аниме, если "
    "не уверен. Без ссылок, хэштегов, рекламы, призывов, кавычек и упоминаний ИИ. "
    "Если картинка недоступна, непонятна или заблокирована, ответь строго SKIP. "
    "Верни только готовую подпись или SKIP."
)
_AAD = b"desiree-ai-provider-v1"
_URL_RE = re.compile(r"(?i)https?://\S+")
_HASHTAG_RE = re.compile(r"(?<!\w)#[\wА-Яа-яЁё]+", re.UNICODE)
_INVALID_CAPTION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bпришл(?:и|ите)\b.{0,60}\b(?:изображ|картин|фото)",
        r"\bзагруз(?:и|ите)\b.{0,60}\b(?:изображ|картин|фото)",
        r"\bопиш(?:и|ите)\b.{0,40}\b(?:его|изображ|картин|фото)",
        r"\b(?:не вижу|не могу (?:увидеть|просмотреть|проанализировать))\b",
        r"\b(?:изображение|картинка|фото)\b.{0,30}\b(?:недоступн|не загруз|заблокирован)",
        r"\bукаж(?:и|ите)\b.{0,30}\b(?:тон|стиль|пожелан)",
        r"\bя (?:подготовлю|придумаю|создам)\b.{0,40}\bподпис",
        r"\b(?:вот|готова)\b.{0,20}\b(?:вариант |ваша )?подпис",
        r"\bподпис(?:ь|и)\b.{0,30}\b(?:писать|дать|сделать) не буду\b",
        r"\bi (?:can(?:not|'t)|won't)\b.{0,50}\b(?:write|create|provide)\b.{0,30}\bcaption\b",
        r"\bi(?:'ll| will) pass\b",
        r"\b(?:send|upload|provide)\b.{0,40}\b(?:image|picture|photo)\b",
        r"\b(?:can't|cannot|unable to)\b.{0,40}\b(?:see|view|analy[sz]e)\b",
    )
)
_STYLE_HINTS = (
    "Форма этой подписи: 1–3 слова.",
    "Форма этой подписи: короткая разговорная реакция.",
    "Форма этой подписи: сухая ирония без объяснений.",
    "Форма этой подписи: один эмодзи и короткая фраза.",
    "Форма этой подписи: очень короткий вопрос по ситуации.",
)


class AiCaptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class AiProviderFailure:
    provider: "AiProvider"
    error: str


class AiCaptionGenerationError(AiCaptionError):
    def __init__(self, failures: list[AiProviderFailure]):
        self.failures = tuple(failures)
        super().__init__(
            "; ".join(
                f"провайдер {failure.provider.index}: {failure.error}"
                for failure in failures
            )[:1000]
            or "Нет доступных AI-провайдеров."
        )


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
    normalized = cleaned.casefold().strip(" !?.:;,-–—")
    if normalized == "skip" or any(pattern.search(cleaned) for pattern in _INVALID_CAPTION_PATTERNS):
        raise AiCaptionError("Модель не смогла распознать изображение.")
    if len(cleaned.split()) > 12:
        raise AiCaptionError("Модель вернула слишком длинную подпись.")
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
    ) -> tuple[str, AiProvider, tuple[AiProviderFailure, ...]]:
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
                            "Изображение уже прикреплено ниже: не проси прислать его. "
                            "Если не можешь его увидеть, ответь только SKIP. "
                            f"Подпись должна быть не длиннее {max_chars} символов. "
                            f"{_STYLE_HINTS[hashlib.sha256(image).digest()[0] % len(_STYLE_HINTS)]}"
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                    },
                ],
            },
        ]
        failures: list[AiProviderFailure] = []
        for provider in providers:
            try:
                raw = await self._complete(provider, messages, 120)
                return (
                    _clean_generated_caption(raw, max_chars),
                    provider,
                    tuple(failures),
                )
            except Exception as exc:
                failures.append(AiProviderFailure(provider, str(exc)))
        raise AiCaptionGenerationError(failures)


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
        self._generation_lock = asyncio.Lock()

    def enabled(self) -> bool:
        return (self.state.get_setting("ai_enabled", "false") or "false").lower() == "true"

    def prompt(self) -> str:
        return self.state.get_setting("ai_prompt", DEFAULT_AI_PROMPT) or DEFAULT_AI_PROMPT

    def max_chars(self) -> int:
        try:
            return min(300, max(40, int(self.state.get_setting("ai_max_chars", "75") or 75)))
        except (TypeError, ValueError):
            return 75

    def auto_delay_seconds(self) -> int:
        try:
            return min(
                3600,
                max(
                    30,
                    int(self.state.get_setting("ai_auto_delay_seconds", "90") or 90),
                ),
            )
        except (TypeError, ValueError):
            return 90

    def interval_seconds(self) -> int:
        try:
            return min(
                600,
                max(
                    10,
                    int(self.state.get_setting("ai_interval_seconds", "20") or 20),
                ),
            )
        except (TypeError, ValueError):
            return 20

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

    def _cooldown_until(self, provider: AiProvider) -> datetime | None:
        raw = self.state.get_setting(
            f"ai_provider_{provider.index}_cooldown_until",
            "",
        )
        if not raw:
            return None
        try:
            value = datetime.fromisoformat(raw)
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    def _ordered_available_providers(self) -> list[AiProvider]:
        now = datetime.now(timezone.utc)
        available = [
            provider
            for provider in self.providers()
            if (self._cooldown_until(provider) or now) <= now
        ]
        if not available:
            return []
        try:
            preferred = int(
                self.state.get_setting("ai_next_provider_index", "1") or 1
            )
        except (TypeError, ValueError):
            preferred = 1
        return sorted(
            available,
            key=lambda provider: (provider.index != preferred, provider.index),
        )

    def _mark_provider_failed(
        self,
        failure: AiProviderFailure,
        item: QueueItem | None,
    ) -> None:
        seconds = 1800 if re.search(r"HTTP (?:401|403|429)\b", failure.error) else 300
        cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        self.state.set_setting(
            f"ai_provider_{failure.provider.index}_cooldown_until",
            cooldown_until.isoformat(),
        )
        self.state.record_event(
            "ai_provider_error",
            queue_item_id=item.id if item else None,
            result={
                "provider": failure.provider.index,
                "model": failure.provider.model,
                "cooldownUntil": cooldown_until.isoformat(),
            },
            error=failure.error,
        )

    def _mark_provider_succeeded(self, provider: AiProvider) -> None:
        self.state.set_setting(
            f"ai_provider_{provider.index}_cooldown_until",
            "",
        )
        configured = self.providers()
        other = next(
            (value for value in configured if value.index != provider.index),
            provider,
        )
        self.state.set_setting("ai_next_provider_index", str(other.index))

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
        if not self.enabled() or item.ai_caption_status in {"generated", "not_needed", "no_preview", "dismissed"}:
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
            async with self._generation_lock:
                providers = self._ordered_available_providers()
                if not providers:
                    raise AiCaptionError(
                        "Все AI-провайдеры временно на паузе после ошибок."
                    )
                caption, provider, failures = await self.client.generate_with_fallback(
                    providers,
                    image=preview_data,
                    mime_type=preview_mime,
                    prompt=self.prompt(),
                    max_chars=self.max_chars(),
                    context=f"{item.content_category}, {item.media_kind}",
                )
            for failure in failures:
                self._mark_provider_failed(failure, item)
            self._mark_provider_succeeded(provider)
            self.state.save_ai_caption(item.id, caption, provider.label)
            self.state.record_event(
                "ai_caption_generated",
                queue_item_id=item.id,
                result={
                    "provider": provider.index,
                    "model": provider.model,
                    "source": item.source,
                    "fallbacks": len(failures),
                },
            )
        except AiCaptionGenerationError as exc:
            for failure in exc.failures:
                self._mark_provider_failed(failure, item)
            error = f"{exc.__class__.__name__}: {exc}"
            self.state.fail_ai_caption(item.id, error)
            self.state.record_event(
                "ai_caption_failed",
                queue_item_id=item.id,
                result={"source": item.source},
                error=error,
            )
        except Exception as exc:
            error = f"{exc.__class__.__name__}: {exc}"
            self.state.fail_ai_caption(item.id, error)
            self.state.record_event(
                "ai_caption_failed",
                queue_item_id=item.id,
                result={"source": item.source},
                error=error,
            )
        return self.state.queue_item(item.id) or item

    async def run_once(self) -> bool:
        if not self.enabled() or not self._ordered_available_providers():
            return False
        item = self.state.claim_ai_caption_item(
            datetime.now(timezone.utc) - timedelta(seconds=self.auto_delay_seconds())
        )
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
            await sleep(self.interval_seconds() if processed else 10)

    async def test_provider(self, index: int) -> dict[str, object]:
        provider = next((value for value in self.providers() if value.index == index), None)
        if provider is None:
            raise AiCaptionError(f"AI-провайдер {index} настроен не полностью.")
        try:
            async with self._generation_lock:
                reply = await self.client.test(provider)
        except Exception as exc:
            self._mark_provider_failed(AiProviderFailure(provider, str(exc)), None)
            raise
        self._mark_provider_succeeded(provider)
        return {"provider": index, "model": provider.model, "reply": reply}

    async def aclose(self) -> None:
        await self.client.aclose()
