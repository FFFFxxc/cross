from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any


def event(name: str, **fields: Any) -> None:
    logging.getLogger("max_reactions").info(
        json.dumps({"event": name, **fields}, ensure_ascii=False)
    )


class ReactionState:
    def __init__(self, path: Path):
        self.connection = sqlite3.connect(path, timeout=5)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS attempts ("
            "chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL, "
            "status TEXT NOT NULL, PRIMARY KEY(chat_id, message_id))"
        )
        self.connection.commit()

    def claim(self, chat_id: int, message_id: int) -> bool:
        cursor = self.connection.execute(
            "INSERT OR IGNORE INTO attempts VALUES (?, ?, 'claimed')",
            (chat_id, message_id),
        )
        self.connection.commit()
        return cursor.rowcount == 1

    def finish(self, chat_id: int, message_id: int, status: str) -> None:
        self.connection.execute(
            "UPDATE attempts SET status = ? WHERE chat_id = ? AND message_id = ?",
            (status, chat_id, message_id),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()


class ReactionWorker:
    def __init__(
        self, api: Any, state: ReactionState, *, channel_id: int, emoji: str,
        started_at_ms: int, max_age_ms: int, max_per_poll: int, dry_run: bool,
    ):
        if type(channel_id) is not int or channel_id == 0:
            raise ValueError("TARGET_CHANNEL_ID_INVALID")
        self.api = api
        self.state = state
        self.channel_id = channel_id
        self.emoji = emoji
        self.started_at_ms = started_at_ms
        self.max_age_ms = max_age_ms
        self.max_per_poll = max_per_poll
        self.dry_run = dry_run

    async def tick(self, messages: list[Any], *, now_ms: int) -> int:
        candidates = []
        for message in messages:
            mid = getattr(message, "id", None)
            chat = getattr(message, "chat_id", None)
            timestamp = getattr(message, "time", None)
            if (
                type(mid) is not int or mid <= 0
                or type(chat) is not int or chat != self.channel_id
                or type(timestamp) is not int
                or not max(self.started_at_ms, now_ms - self.max_age_ms) < timestamp <= now_ms
                or getattr(message, "type", "") not in {"CHANNEL", "USER"}
                or getattr(getattr(message, "reaction_info", None), "your_reaction", None)
            ):
                continue
            candidates.append(message)

        attempts = 0
        for message in sorted(candidates, key=lambda item: (item.time, item.id)):
            if attempts >= self.max_per_poll:
                break
            if self.dry_run:
                event("dry_run_candidate", chat_id=self.channel_id, message_id=message.id)
                attempts += 1
                continue
            # Commit before the request: a timeout or crash must not replay it.
            if not self.state.claim(self.channel_id, message.id):
                continue
            attempts += 1
            try:
                reactions = await self.api.get_reactions(self.channel_id, [message.id])
                own = (reactions or {}).get(str(message.id))
                if getattr(own, "your_reaction", None):
                    self.state.finish(self.channel_id, message.id, "already_reacted")
                    continue
                result = await self.api.add_reaction(self.channel_id, message.id, self.emoji)
                confirmed = getattr(result, "your_reaction", None) == self.emoji
                self.state.finish(
                    self.channel_id, message.id, "confirmed" if confirmed else "requested"
                )
                event(
                    "reaction_confirmed" if confirmed else "reaction_requested",
                    chat_id=self.channel_id, message_id=message.id, emoji=self.emoji,
                )
            except Exception as error:
                self.state.finish(self.channel_id, message.id, "failed_or_ambiguous")
                event("reaction_failed", message_id=message.id, error_type=type(error).__name__)
                raise
        return attempts
