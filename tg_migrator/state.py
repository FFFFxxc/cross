from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


class MigrationState:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS transferred_messages (
                source TEXT NOT NULL,
                destination TEXT NOT NULL,
                source_message_id INTEGER NOT NULL,
                transferred_at TEXT NOT NULL,
                PRIMARY KEY (source, destination, source_message_id)
            )
            """
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def transferred_ids(
        self,
        source: str,
        destination: str,
        ids: Iterable[int],
    ) -> set[int]:
        values = tuple(ids)
        if not values:
            return set()
        placeholders = ",".join("?" for _ in values)
        rows = self._connection.execute(
            f"""
            SELECT source_message_id
            FROM transferred_messages
            WHERE source = ?
              AND destination = ?
              AND source_message_id IN ({placeholders})
            """,
            (source, destination, *values),
        )
        return {int(row[0]) for row in rows}

    def mark_transferred(
        self,
        source: str,
        destination: str,
        ids: Iterable[int],
    ) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        self._connection.executemany(
            """
            INSERT OR IGNORE INTO transferred_messages (
                source,
                destination,
                source_message_id,
                transferred_at
            ) VALUES (?, ?, ?, ?)
            """,
            (
                (source, destination, int(message_id), timestamp)
                for message_id in ids
            ),
        )
        self._connection.commit()

    def total(self, source: str, destination: str) -> int:
        row = self._connection.execute(
            """
            SELECT COUNT(*)
            FROM transferred_messages
            WHERE source = ? AND destination = ?
            """,
            (source, destination),
        ).fetchone()
        return int(row[0]) if row else 0

