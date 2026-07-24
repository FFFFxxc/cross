from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
import re
from typing import Any, AsyncIterator
from zoneinfo import ZoneInfo


MOSCOW = ZoneInfo("Europe/Moscow")
ALLOWED_LINK = "https://t.me/fulli4k_bot"
_VISIBLE_LINK_RE = re.compile(
    r"(?i)(?:https?://|www\.|(?:t\.me|telegram\.me)/)[^\s<>()]+"
)


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
    allowed = _normalize_link(ALLOWED_LINK)
    return any(_normalize_link(link) != allowed for link in _message_links(message))


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
