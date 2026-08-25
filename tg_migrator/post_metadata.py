from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PostMetrics:
    views: int
    reactions: int
    forwards: int


def post_metrics(post: Any) -> PostMetrics:
    views = 0
    reactions = 0
    forwards = 0
    for message in post.messages:
        views += int(getattr(message, "views", 0) or 0)
        forwards += int(getattr(message, "forwards", 0) or 0)
        results = getattr(getattr(message, "reactions", None), "results", None) or ()
        reactions += sum(int(getattr(result, "count", 0) or 0) for result in results)
    return PostMetrics(views=views, reactions=reactions, forwards=forwards)


def caption_excerpt(post: Any, limit: int = 500) -> str:
    if limit <= 0:
        return ""
    for message in post.messages:
        value = (
            getattr(message, "raw_text", None)
            or getattr(message, "message", None)
            or ""
        ).strip()
        if value:
            compact = " ".join(value.split())
            if len(compact) <= limit:
                return compact
            if limit == 1:
                return "…"
            return compact[: limit - 1].rstrip() + "…"
    return ""
