from __future__ import annotations

from copy import copy
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
import re
from typing import Any, AsyncIterator
from zoneinfo import ZoneInfo


MOSCOW = ZoneInfo("Europe/Moscow")
ALLOWED_LINKS = {
    "https://t.me/fulli4k_bot",
    "https://max.ru/channel_anime2d",
}
_VISIBLE_LINK_RE = re.compile(
    r"(?i)(?:https?://|www\.|(?:t\.me|telegram\.me)/)[^\s<>()]+"
)
_MAX_URL_RE = re.compile(r"https?://max\.ru/channel_anime2d/?", re.IGNORECASE)
_MAX_PHRASE_RE = re.compile(r"мы\s+в\s+(?:максе|max)", re.IGNORECASE)


@dataclass(frozen=True)
class Post:
    key: str
    messages: tuple[Any, ...]

    @property
    def ids(self) -> tuple[int, ...]:
        return tuple(message.id for message in self.messages)

    @property
    def published_at(self) -> datetime:
        return min(message.date for message in self.messages)

    @property
    def preview(self) -> str:
        for message in self.messages:
            text = (getattr(message, "raw_text", None) or "").strip()
            if text:
                return text.replace("\n", " ")[:80]
        return "[медиа без подписи]"


def parse_start_date(value: str) -> datetime:
    text = value.strip()
    parsed: date | None = None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            parsed = datetime.strptime(text, fmt).date()
            break
        except ValueError:
            continue
    if parsed is None:
        raise ValueError("Используйте дату в формате ДД.ММ.ГГГГ или ГГГГ-ММ-ДД.")
    local_midnight = datetime.combine(parsed, time.min, tzinfo=MOSCOW)
    return local_midnight.astimezone(timezone.utc)


def _transferable(message: Any) -> bool:
    if getattr(message, "action", None) is not None:
        return False
    return bool(
        getattr(message, "message", None)
        or getattr(message, "media", None)
    )


def _normalize_link(link: str) -> str:
    return link.strip().rstrip(".,!?;:)]}>").rstrip("/").lower()


def _utf16_len(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _removal_spans(text: str) -> list[tuple[int, int]]:
    matches = [
        *_MAX_URL_RE.finditer(text),
        *_MAX_PHRASE_RE.finditer(text),
    ]
    spans: list[tuple[int, int]] = []
    for match in sorted(matches, key=lambda item: item.start()):
        start, end = match.span()
        if match.re is _MAX_PHRASE_RE:
            line_start = text.rfind("\n", 0, start) + 1
            line_end = text.find("\n", end)
            if line_end == -1:
                line_end = len(text)
            surrounding = text[line_start:start] + text[end:line_end]
            surrounding = _MAX_URL_RE.sub("", surrounding)
            if not any(character.isalnum() for character in surrounding):
                start = line_start
                end = line_end
                if end < len(text):
                    end += 1
                elif start > 0:
                    start -= 1
                spans.append((start, end))
                continue
        while start > 0 and text[start - 1] in " \t":
            start -= 1
        while end < len(text) and text[end] in " \t\r\n":
            end += 1
        if match.re is _MAX_PHRASE_RE:
            while end < len(text) and text[end] in ":：,;.!?-–—":
                end += 1
            while end < len(text) and text[end] in " \t":
                end += 1
        spans.append((start, end))
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def sanitize_message_text(text: str, entities: list[Any] | None) -> tuple[str, list[Any]]:
    """Remove MAX promotion while preserving Telegram entity offsets."""
    spans = _removal_spans(text)
    if not spans:
        return text, [copy(entity) for entity in entities or []]

    cleaned = text
    for start, end in reversed(spans):
        cleaned = cleaned[:start] + cleaned[end:]

    adjusted: list[Any] = []
    for entity in entities or []:
        original_start = int(getattr(entity, "offset", 0))
        original_end = original_start + int(getattr(entity, "length", 0))
        removed_before = 0
        overlaps = False
        for start, end in spans:
            start_u16 = _utf16_len(text[:start])
            end_u16 = _utf16_len(text[:end])
            if original_start < end_u16 and original_end > start_u16:
                overlaps = True
                break
            if end_u16 <= original_start:
                removed_before += end_u16 - start_u16
        if overlaps:
            continue
        clone = copy(entity)
        clone.offset = original_start - removed_before
        adjusted.append(clone)
    return cleaned, adjusted


def _message_links(message: Any) -> list[str]:
    """Return visible and hidden links attached to a Telegram message."""
    raw_text = (
        getattr(message, "raw_text", None)
        or getattr(message, "message", None)
        or ""
    )
    links = list(_VISIBLE_LINK_RE.findall(raw_text))
    for entity in getattr(message, "entities", None) or ():
        entity_url = getattr(entity, "url", None)
        if entity_url:
            links.append(str(entity_url))
    return links


def _has_disallowed_link(message: Any) -> bool:
    allowed = {_normalize_link(link) for link in ALLOWED_LINKS}
    return any(
        _normalize_link(link) not in allowed
        for link in _message_links(message)
    )


def _post_is_allowed(messages: list[Any]) -> bool:
    return not any(_has_disallowed_link(message) for message in messages)


def _key(message: Any) -> str:
    grouped_id = getattr(message, "grouped_id", None)
    if grouped_id is not None:
        return f"album:{grouped_id}"
    return f"message:{message.id}"


def _post(key: str, messages: list[Any]) -> Post:
    return Post(key, tuple(sorted(messages, key=lambda message: message.id)))


def post_from_messages(messages: list[Any] | tuple[Any, ...]) -> Post | None:
    """Build one new-post unit for the live listener."""
    transferable = [message for message in messages if _transferable(message)]
    if not transferable or not _post_is_allowed(transferable):
        return None
    return _post(_key(transferable[0]), transferable)


async def latest_posts(
    messages: AsyncIterator[Any],
    count: int,
) -> list[Post]:
    if count <= 0:
        raise ValueError("Количество постов должно быть больше нуля.")

    posts: list[Post] = []
    current_key: str | None = None
    current_messages: list[Any] = []

    async for message in messages:
        if not _transferable(message):
            continue
        message_key = _key(message)
        if current_key is not None and message_key != current_key:
            if _post_is_allowed(current_messages):
                posts.append(_post(current_key, current_messages))
            if len(posts) >= count:
                break
            current_messages = []
        current_key = message_key
        current_messages.append(message)
    else:
        if (
            current_key is not None
            and len(posts) < count
            and _post_is_allowed(current_messages)
        ):
            posts.append(_post(current_key, current_messages))

    return sorted(
        posts,
        key=lambda post: (post.published_at, min(post.ids)),
    )


async def posts_from_date(
    messages: AsyncIterator[Any],
    start: datetime,
) -> list[Post]:
    posts_by_key: dict[str, list[Any]] = {}
    for_comparison = (
        start if start.tzinfo is not None else start.replace(tzinfo=timezone.utc)
    )

    async for message in messages:
        message_date = message.date
        if message_date.tzinfo is None:
            message_date = message_date.replace(tzinfo=timezone.utc)
        if message_date < for_comparison:
            break
        if not _transferable(message):
            continue
        posts_by_key.setdefault(_key(message), []).append(message)

    posts = [
        _post(key, value)
        for key, value in posts_by_key.items()
        if _post_is_allowed(value)
    ]
    return sorted(
        posts,
        key=lambda post: (post.published_at, min(post.ids)),
    )
