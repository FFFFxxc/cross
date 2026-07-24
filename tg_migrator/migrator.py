from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, Sequence

from telethon.errors import (
    ChatForwardsRestrictedError,
    FloodWaitError,
    RPCError,
)

from .selection import Post
from .state import MigrationState


class TransferMode(str, Enum):
    COPY = "copy"
    FORWARD = "forward"


@dataclass(frozen=True)
class Progress:
    total_posts: int
    processed_posts: int
    transferred_posts: int
    skipped_posts: int
    current_post: Post | None
    cancelled: bool = False


ProgressCallback = Callable[[Progress], Awaitable[None] | None]


async def _report(
    callback: ProgressCallback | None,
    progress: Progress,
) -> None:
    if callback is None:
        return
    result = callback(progress)
    if result is not None:
        await result


async def migrate_posts(
    client,
    source,
    destination,
    posts: Sequence[Post],
    state: MigrationState,
    mode: TransferMode = TransferMode.COPY,
    dry_run: bool = False,
    cancel_event: asyncio.Event | None = None,
    callback: ProgressCallback | None = None,
) -> Progress:
    source_key = str(source)
    destination_key = str(destination)
    transferred_posts = 0
    skipped_posts = 0

    for index, post in enumerate(posts, start=1):
        if cancel_event is not None and cancel_event.is_set():
            progress = Progress(
                len(posts),
                index - 1,
                transferred_posts,
                skipped_posts,
                post,
                cancelled=True,
            )
            await _report(callback, progress)
            return progress

        already_done = state.transferred_ids(
            source_key,
            destination_key,
            post.ids,
        )
        ids_to_send = [
            message_id
            for message_id in post.ids
            if message_id not in already_done
        ]
        if not ids_to_send:
            skipped_posts += 1
        elif dry_run:
            transferred_posts += 1
        else:
            while True:
                try:
                    await client.forward_messages(
                        destination,
                        ids_to_send,
                        from_peer=source,
                        drop_author=mode is TransferMode.COPY,
                    )
                    break
                except FloodWaitError as exc:
                    await asyncio.sleep(exc.seconds + 1)
                except ChatForwardsRestrictedError as exc:
                    raise RuntimeError(
                        "В источнике включена защита контента. "
                        "Telegram не разрешает перенос этих публикаций."
                    ) from exc
                except RPCError as exc:
                    raise RuntimeError(
                        f"Telegram отклонил пост {post.ids}: "
                        f"{exc.__class__.__name__}: {exc}"
                    ) from exc
            state.mark_transferred(
                source_key,
                destination_key,
                ids_to_send,
            )
            transferred_posts += 1

        progress = Progress(
            len(posts),
            index,
            transferred_posts,
            skipped_posts,
            post,
        )
        await _report(callback, progress)

    return Progress(
        len(posts),
        len(posts),
        transferred_posts,
        skipped_posts,
        None,
    )
