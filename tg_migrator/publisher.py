from __future__ import annotations

import html
from copy import copy
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

from telethon.helpers import add_surrogate, del_surrogate

from .max_client import AmbiguousMaxSendError, MaxAttachment, MaxClient
from .selection import sanitize_message_text
from .state import MigrationState, QueueItem


@dataclass(frozen=True)
class PublishResult:
    item_id: str
    telegram_message_ids: tuple[int, ...]
    max_mid: str


_ENTITY_TAGS = {
    "messageentitybold": ("<b>", "</b>"),
    "messageentityitalic": ("<i>", "</i>"),
    "messageentityunderline": ("<u>", "</u>"),
    "messageentitystrike": ("<s>", "</s>"),
    "messageentitycode": ("<code>", "</code>"),
    "messageentitypre": ("<pre>", "</pre>"),
}


def telegram_entities_to_max_html(text: str, entities: list | tuple) -> str:
    """Convert supported Telegram UTF-16 entities to MAX-safe HTML."""
    if not text:
        return ""
    surrogate = add_surrogate(text)
    normalized = []
    for entity in entities or ():
        tags = _ENTITY_TAGS.get(entity.__class__.__name__.lower())
        start = int(getattr(entity, "offset", -1))
        length = int(getattr(entity, "length", 0))
        end = start + length
        if tags and start >= 0 and length > 0 and end <= len(surrogate):
            normalized.append((start, end, tags[0], tags[1]))

    openings: dict[int, list[tuple]] = {}
    closings: dict[int, list[tuple]] = {}
    for item in normalized:
        openings.setdefault(item[0], []).append(item)
        closings.setdefault(item[1], []).append(item)
    for values in openings.values():
        values.sort(key=lambda value: value[1], reverse=True)
    for values in closings.values():
        values.sort(key=lambda value: value[0], reverse=True)

    positions = sorted({0, len(surrogate), *openings, *closings})
    result: list[str] = []
    for index, position in enumerate(positions):
        result.extend(value[3] for value in closings.get(position, ()))
        result.extend(value[2] for value in openings.get(position, ()))
        if index + 1 < len(positions):
            segment = del_surrogate(surrogate[position : positions[index + 1]])
            result.append(html.escape(segment, quote=False))
    return "".join(result)


def _signature_html(label: str, url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Ссылка подписи должна начинаться с http:// или https://")
    return (
        f'<a href="{html.escape(url, quote=True)}">'
        f"{html.escape(label, quote=False)}</a>"
    )


def _message_text(message) -> tuple[str, list]:
    text = (
        getattr(message, "raw_text", None)
        or getattr(message, "message", None)
        or ""
    )
    return sanitize_message_text(
        text,
        list(getattr(message, "entities", None) or []),
    )


def _utf16_len(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _split_text(text: str, entities: list, limit: int = 2800) -> list[tuple[str, list]]:
    if not text:
        return [("", [])]
    chunks: list[tuple[str, list]] = []
    start = 0
    while start < len(text):
        end = min(start + limit, len(text))
        if end < len(text):
            candidate = text[start:end]
            natural = max(candidate.rfind("\n"), candidate.rfind(" "))
            if natural >= limit // 2:
                end = start + natural + 1
        start_u16 = _utf16_len(text[:start])
        end_u16 = _utf16_len(text[:end])
        adjusted = []
        for entity in entities:
            entity_start = int(getattr(entity, "offset", 0))
            entity_end = entity_start + int(getattr(entity, "length", 0))
            overlap_start = max(entity_start, start_u16)
            overlap_end = min(entity_end, end_u16)
            if overlap_start < overlap_end:
                clone = copy(entity)
                clone.offset = overlap_start - start_u16
                clone.length = overlap_end - overlap_start
                adjusted.append(clone)
        chunks.append((text[start:end], adjusted))
        start = end
    return chunks


def _media_type(message) -> str:
    document = getattr(message, "document", None)
    mime_type = (getattr(document, "mime_type", None) or "").lower()
    if (
        getattr(message, "video", None) is not None
        or getattr(message, "gif", None) is not None
        or mime_type.startswith("video/")
    ):
        return "video"
    if getattr(message, "photo", None) is not None:
        return "image"
    if getattr(message, "audio", None) is not None or mime_type.startswith("audio/"):
        return "audio"
    return "file"


def _downloadable(message) -> bool:
    return any(
        getattr(message, name, None) is not None
        for name in ("file", "document", "photo", "video", "gif", "audio", "voice")
    )


def _media_suffix(message, media_type: str) -> str:
    suffix = getattr(getattr(message, "file", None), "ext", None)
    if suffix:
        return str(suffix)
    return {"video": ".mp4", "image": ".jpg", "audio": ".mp3"}.get(
        media_type,
        ".bin",
    )


class PostPublisher:
    def __init__(
        self,
        client,
        state: MigrationState,
        destination,
        max_client: MaxClient,
        *,
        default_signature: tuple[str, str],
    ):
        self.client = client
        self.state = state
        self.destination = destination
        self.max_client = max_client
        self.default_signature = default_signature

    async def _messages(self, item: QueueItem) -> list:
        values = await self.client.get_messages(
            item.source,
            ids=list(item.message_ids),
        )
        messages = list(values) if isinstance(values, (list, tuple)) else [values]
        by_id = {message.id: message for message in messages if message is not None}
        ordered = [by_id[value] for value in item.message_ids if value in by_id]
        if len(ordered) != len(item.message_ids):
            raise RuntimeError("Часть исходной Telegram-публикации больше недоступна")
        return ordered

    async def _telegram_stage(self, item: QueueItem, messages: list) -> tuple[int, ...]:
        if item.telegram_message_ids:
            return item.telegram_message_ids
        forwarded = await self.client.forward_messages(
            self.destination,
            list(item.message_ids),
            from_peer=item.source,
            drop_author=True,
        )
        sent = list(forwarded) if isinstance(forwarded, (list, tuple)) else [forwarded]
        for source_message, sent_message in zip(messages, sent):
            original = (
                getattr(source_message, "raw_text", None)
                or getattr(source_message, "message", None)
                or ""
            )
            cleaned, entities = _message_text(source_message)
            has_buttons = bool(
                getattr(source_message, "reply_markup", None)
                or getattr(source_message, "buttons", None)
            )
            if cleaned != original or has_buttons:
                await self.client.edit_message(
                    self.destination,
                    sent_message,
                    text=cleaned,
                    formatting_entities=entities,
                    link_preview=False,
                    buttons=None,
                )
        ids = tuple(int(message.id) for message in sent)
        self.state.save_telegram_delivery(item.id, ids)
        return ids

    def _max_text_chunks(self, messages: list) -> list[str]:
        cleaned_text = ""
        entities: list = []
        for message in messages:
            cleaned_text, entities = _message_text(message)
            if cleaned_text:
                break
        signature_text = self.state.get_setting(
            "signature_text",
            self.default_signature[0],
        ) or self.default_signature[0]
        signature_url = self.state.get_setting(
            "signature_url",
            self.default_signature[1],
        ) or self.default_signature[1]
        signature = _signature_html(signature_text, signature_url)
        chunks = [
            telegram_entities_to_max_html(text, chunk_entities)
            for text, chunk_entities in _split_text(cleaned_text, entities)
        ]
        if chunks[-1]:
            chunks[-1] = f"{chunks[-1]}\n\n{signature}"
        else:
            chunks[-1] = signature
        return chunks

    async def _max_stage(self, messages: list) -> str:
        attachments: list[MaxAttachment] = []
        with TemporaryDirectory(prefix="desiree-max-") as directory:
            for message in messages:
                if getattr(message, "media", None) is None or not _downloadable(message):
                    continue
                media_type = _media_type(message)
                path = Path(directory) / f"telegram-{message.id}{_media_suffix(message, media_type)}"
                downloaded = await self.client.download_media(message, file=str(path))
                if not downloaded:
                    raise RuntimeError(f"Telegram не скачал вложение #{message.id}")
                attachments.append(await self.max_client.upload(Path(downloaded), media_type))
            mids = []
            for index, chunk in enumerate(self._max_text_chunks(messages)):
                mids.append(
                    await self.max_client.send(
                        chunk,
                        attachments if index == 0 else [],
                    )
                )
            return ",".join(mids)

    async def publish(self, item: QueueItem) -> PublishResult:
        if item.status != "processing":
            raise ValueError("Публиковать можно только claimed-элемент очереди")
        try:
            messages = await self._messages(item)
        except Exception as exc:
            self.state.mark_error(item.id, "failed", str(exc))
            raise
        try:
            telegram_ids = await self._telegram_stage(item, messages)
        except Exception as exc:
            self.state.mark_error(
                item.id,
                "ambiguous",
                f"Неопределённый Telegram-этап: {exc}",
            )
            raise
        try:
            max_mid = await self._max_stage(messages)
        except AmbiguousMaxSendError as exc:
            self.state.mark_error(item.id, "ambiguous", str(exc))
            raise
        except Exception as exc:
            self.state.mark_error(item.id, "failed", str(exc))
            raise
        self.state.complete(item.id, max_mid)
        return PublishResult(item.id, telegram_ids, max_mid)
