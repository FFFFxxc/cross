from __future__ import annotations

from copy import copy
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
import hashlib
import math
import re
from typing import Any, AsyncIterator
from zoneinfo import ZoneInfo

from .post_metadata import post_metrics


MOSCOW = ZoneInfo("Europe/Moscow")
_VISIBLE_LINK_RE = re.compile(
    r"(?i)(?:https?://|www\.|(?:t\.me|telegram\.me)/)[^\s<>()]+"
)
_MENTION_RE = re.compile(r"(?<![\w@])@[A-Za-z0-9_]{5,}")
_PROMO_RE = re.compile(
    r"(?i)(?:"
    r"мы\s+в\s+(?:максе|max)|"
    r"хот\s+контент|"
    r"фулл(?:\s+(?:в|на)\s+[^\n]+)?|"
    r"наш\s+(?:тгк|телеграм|канал)|"
    r"подпис(?:аться|ывай(?:ся)?|ка)"
    r")"
)
_ADVERTISING_MARKER_RE = re.compile(r"\bреклама\b", re.IGNORECASE)


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


def text_has_advertising_marker(text: str | None) -> bool:
    """Match the standalone disclosure word without rejecting 'рекламная'."""
    return bool(_ADVERTISING_MARKER_RE.search(text or ""))


def post_has_advertising_marker(post: Post) -> bool:
    return any(
        text_has_advertising_marker(
            getattr(message, "raw_text", None)
            or getattr(message, "message", None)
        )
        for message in post.messages
    )


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


def _utf16_len(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _index_from_utf16(text: str, offset: int) -> int:
    consumed = 0
    for index, character in enumerate(text):
        if consumed >= offset:
            return index
        consumed += _utf16_len(character)
    return len(text)


def _line_span(text: str, start: int, end: int) -> tuple[int, int]:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end == -1:
        line_end = len(text)
        if line_start > 0:
            line_start -= 1
    else:
        line_end += 1
    return line_start, line_end


def _entity_removes_line(entity: Any) -> bool:
    name = entity.__class__.__name__.lower()
    return bool(
        getattr(entity, "url", None)
        or "url" in name
        or "mention" in name
        or "email" in name
    )


def _removal_spans(text: str, entities: list[Any] | None) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []

    for match in [*_VISIBLE_LINK_RE.finditer(text), *_MENTION_RE.finditer(text)]:
        spans.append(_line_span(text, *match.span()))

    for entity in entities or ():
        if not _entity_removes_line(entity):
            continue
        start_u16 = int(getattr(entity, "offset", 0))
        end_u16 = start_u16 + int(getattr(entity, "length", 0))
        start = _index_from_utf16(text, start_u16)
        end = _index_from_utf16(text, end_u16)
        spans.append(_line_span(text, start, end))

    for match in _PROMO_RE.finditer(text):
        start, end = match.span()
        line_start = text.rfind("\n", 0, start) + 1
        line_end = text.find("\n", end)
        if line_end == -1:
            line_end = len(text)
        surrounding = text[line_start:start] + text[end:line_end]
        if not any(character.isalnum() for character in surrounding):
            spans.append(_line_span(text, start, end))
            continue
        while start > 0 and text[start - 1] in " \t":
            start -= 1
        while end < len(text) and text[end] in " \t\r\n":
            end += 1
        while end < len(text) and text[end] in ":：,;.!?-–—":
            end += 1
        while end < len(text) and text[end] in " \t":
            end += 1
        spans.append((start, end))

    position = 0
    for line in text.splitlines(keepends=True):
        content = line.strip()
        if content and not any(character.isalnum() or character == "#" for character in content):
            spans.append((position, position + len(line)))
        position += len(line)

    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    if merged and merged[-1][1] == len(text):
        start, end = merged[-1]
        if start > 0 and text[start - 1] == "\n":
            merged[-1] = (start - 1, end)
    return merged


def sanitize_message_text(text: str, entities: list[Any] | None) -> tuple[str, list[Any]]:
    """Remove foreign promotion while preserving Telegram entity offsets."""
    spans = _removal_spans(text, entities)
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
    if not transferable:
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
    ]
    return sorted(
        posts,
        key=lambda post: (post.published_at, min(post.ids)),
    )


def post_media_kind(post: Post) -> str:
    for message in post.messages:
        document = getattr(message, "document", None)
        mime_type = (getattr(document, "mime_type", None) or "").lower()
        if (
            getattr(message, "video", None) is not None
            or getattr(message, "gif", None) is not None
            or mime_type.startswith("video/")
        ):
            return "video"
    if any(getattr(message, "photo", None) is not None for message in post.messages):
        return "image"
    return "any"


def post_activity(post: Post) -> int:
    score = 0
    for message in post.messages:
        score += int(getattr(message, "views", 0) or 0)
        score += 3 * int(getattr(message, "forwards", 0) or 0)
        reactions = getattr(getattr(message, "reactions", None), "results", None) or ()
        score += 5 * sum(int(getattr(reaction, "count", 0) or 0) for reaction in reactions)
    return score


def post_smart_score(post: Post, now: datetime | None = None) -> int:
    """Rank reach, engagement quality and freshness on one stable scale."""
    metrics = post_metrics(post)
    views = metrics.views
    reactions = metrics.reactions
    forwards = metrics.forwards

    engagement_base = max(views, 100)
    score = (
        100 * math.log1p(views)
        + 25 * reactions
        + 40 * forwards
        + 5_000 * reactions / engagement_base
        + 7_500 * forwards / engagement_base
    )
    current = now or datetime.now(timezone.utc)
    published_at = post.published_at
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (current - published_at).total_seconds() / 86_400)
    freshness = 0.5 ** (age_days / 7)
    return max(0, int(round(score * freshness)))


def post_fingerprint(post: Post) -> str:
    media: list[str] = []
    texts: list[str] = []
    for message in post.messages:
        document_id = getattr(getattr(message, "document", None), "id", None)
        photo_id = getattr(getattr(message, "photo", None), "id", None)
        if document_id is not None:
            media.append(f"document:{document_id}")
        elif photo_id is not None:
            media.append(f"photo:{photo_id}")
        raw_text = (
            getattr(message, "raw_text", None)
            or getattr(message, "message", None)
            or ""
        )
        cleaned, _ = sanitize_message_text(
            raw_text,
            list(getattr(message, "entities", None) or []),
        )
        if cleaned:
            texts.append(cleaned)
    if media:
        payload = "|".join(sorted(media))
        prefix = "media"
    else:
        payload = "\n".join(texts).strip()
        prefix = "text"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"
