from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, RowMapping


@dataclass(frozen=True)
class Source:
    peer: str
    title: str


@dataclass(frozen=True, order=True)
class Slot:
    time: str
    kind: str = "any"
    source: str | None = None


@dataclass(frozen=True)
class QueueItem:
    id: str
    source: str
    post_key: str
    message_ids: tuple[int, ...]
    media_kind: str
    score: int
    published_at: datetime
    status: str
    telegram_message_ids: tuple[int, ...]
    max_mid: str | None
    error: str | None


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _database_url(path: Path, database_url: str | None) -> str:
    if not database_url:
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite+pysqlite:///{path}"
    if database_url.startswith("postgres://"):
        return "postgresql+psycopg://" + database_url[len("postgres://") :]
    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + database_url[len("postgresql://") :]
    return database_url


class MigrationState:
    def __init__(self, path: Path, database_url: str | None = None):
        self._engine = create_engine(
            _database_url(path, database_url),
            pool_pre_ping=True,
        )
        self._create_schema()

    def _create_schema(self) -> None:
        statements = (
            """
            CREATE TABLE IF NOT EXISTS transferred_messages (
                source TEXT NOT NULL,
                destination TEXT NOT NULL,
                source_message_id INTEGER NOT NULL,
                transferred_at TEXT NOT NULL,
                PRIMARY KEY (source, destination, source_message_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS automation_sources (
                peer TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                added_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS automation_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS automation_slots (
                run_time TEXT PRIMARY KEY,
                media_kind TEXT NOT NULL,
                source TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS automation_queue (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                post_key TEXT NOT NULL,
                message_ids TEXT NOT NULL,
                media_kind TEXT NOT NULL,
                score INTEGER NOT NULL,
                published_at TEXT NOT NULL,
                status TEXT NOT NULL,
                telegram_message_ids TEXT,
                max_mid TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                UNIQUE (source, post_key)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS automation_slot_runs (
                run_date TEXT NOT NULL,
                run_time TEXT NOT NULL,
                claimed_at TEXT NOT NULL,
                PRIMARY KEY (run_date, run_time)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS automation_fingerprints (
                fingerprint TEXT PRIMARY KEY,
                added_at TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS automation_queue_claim
            ON automation_queue (status, media_kind, score, published_at)
            """,
        )
        with self._engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))

    def close(self) -> None:
        self._engine.dispose()

    def transferred_ids(
        self,
        source: str,
        destination: str,
        ids: Iterable[int],
    ) -> set[int]:
        values = tuple(int(value) for value in ids)
        if not values:
            return set()
        names = [f"id_{index}" for index in range(len(values))]
        placeholders = ",".join(f":{name}" for name in names)
        params = {name: value for name, value in zip(names, values)}
        params.update({"source": source, "destination": destination})
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"""
                    SELECT source_message_id FROM transferred_messages
                    WHERE source = :source AND destination = :destination
                      AND source_message_id IN ({placeholders})
                    """
                ),
                params,
            )
            return {int(row[0]) for row in rows}

    def mark_transferred(
        self,
        source: str,
        destination: str,
        ids: Iterable[int],
    ) -> None:
        timestamp = _utcnow()
        rows = [
            {
                "source": source,
                "destination": destination,
                "message_id": int(message_id),
                "timestamp": timestamp,
            }
            for message_id in ids
        ]
        if not rows:
            return
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO transferred_messages (
                        source, destination, source_message_id, transferred_at
                    ) VALUES (:source, :destination, :message_id, :timestamp)
                    ON CONFLICT (source, destination, source_message_id) DO NOTHING
                    """
                ),
                rows,
            )

    def total(self, source: str, destination: str) -> int:
        with self._engine.connect() as connection:
            value = connection.execute(
                text(
                    """
                    SELECT COUNT(*) FROM transferred_messages
                    WHERE source = :source AND destination = :destination
                    """
                ),
                {"source": source, "destination": destination},
            ).scalar_one()
            return int(value)

    def add_source(self, peer: str, title: str) -> bool:
        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    INSERT INTO automation_sources (peer, title, added_at)
                    VALUES (:peer, :title, :added_at)
                    ON CONFLICT (peer) DO NOTHING
                    """
                ),
                {"peer": str(peer), "title": title, "added_at": _utcnow()},
            )
            return result.rowcount == 1

    def remove_source(self, peer: str) -> bool:
        with self._engine.begin() as connection:
            result = connection.execute(
                text("DELETE FROM automation_sources WHERE peer = :peer"),
                {"peer": str(peer)},
            )
            return result.rowcount == 1

    def sources(self) -> list[Source]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text("SELECT peer, title FROM automation_sources ORDER BY added_at, peer")
            )
            return [Source(str(row.peer), str(row.title)) for row in rows]

    def set_setting(self, key: str, value: str) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO automation_settings (key, value) VALUES (:key, :value)
                    ON CONFLICT (key) DO UPDATE SET value = excluded.value
                    """
                ),
                {"key": key, "value": value},
            )

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self._engine.connect() as connection:
            value = connection.execute(
                text("SELECT value FROM automation_settings WHERE key = :key"),
                {"key": key},
            ).scalar_one_or_none()
            return default if value is None else str(value)

    def set_slot(self, slot: Slot) -> None:
        if slot.kind not in {"any", "video", "image"}:
            raise ValueError("Тип слота: any, video или image.")
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO automation_slots (run_time, media_kind, source)
                    VALUES (:time, :kind, :source)
                    ON CONFLICT (run_time) DO UPDATE SET
                        media_kind = excluded.media_kind,
                        source = excluded.source
                    """
                ),
                {"time": slot.time, "kind": slot.kind, "source": slot.source},
            )

    def remove_slot(self, run_time: str) -> bool:
        with self._engine.begin() as connection:
            result = connection.execute(
                text("DELETE FROM automation_slots WHERE run_time = :time"),
                {"time": run_time},
            )
            return result.rowcount == 1

    def slots(self) -> list[Slot]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT run_time, media_kind, source
                    FROM automation_slots ORDER BY run_time
                    """
                )
            )
            return [Slot(str(row.run_time), str(row.media_kind), row.source) for row in rows]

    def enqueue(
        self,
        source: str,
        post_key: str,
        message_ids: Iterable[int],
        media_kind: str,
        score: int,
        published_at: datetime,
        fingerprint: str | None = None,
    ) -> QueueItem | None:
        item_id = uuid.uuid4().hex[:12]
        params = {
            "id": item_id,
            "source": str(source),
            "post_key": post_key,
            "message_ids": json.dumps([int(value) for value in message_ids]),
            "media_kind": media_kind,
            "score": int(score),
            "published_at": published_at.isoformat(),
            "status": "pending",
            "created_at": _utcnow(),
        }
        with self._engine.begin() as connection:
            if fingerprint:
                fingerprint_result = connection.execute(
                    text(
                        """
                        INSERT INTO automation_fingerprints (fingerprint, added_at)
                        VALUES (:fingerprint, :added_at)
                        ON CONFLICT (fingerprint) DO NOTHING
                        """
                    ),
                    {"fingerprint": fingerprint, "added_at": _utcnow()},
                )
                if fingerprint_result.rowcount != 1:
                    return None
            result = connection.execute(
                text(
                    """
                    INSERT INTO automation_queue (
                        id, source, post_key, message_ids, media_kind, score,
                        published_at, status, created_at
                    ) VALUES (
                        :id, :source, :post_key, :message_ids, :media_kind,
                        :score, :published_at, :status, :created_at
                    )
                    ON CONFLICT (source, post_key) DO NOTHING
                    """
                ),
                params,
            )
            if result.rowcount != 1:
                return None
        return self.queue_item(item_id)

    def mark_fingerprints(self, fingerprints: Iterable[str]) -> int:
        rows = [
            {"fingerprint": value, "added_at": _utcnow()}
            for value in dict.fromkeys(fingerprints)
            if value
        ]
        if not rows:
            return 0
        added = 0
        with self._engine.begin() as connection:
            for row in rows:
                result = connection.execute(
                    text(
                        """
                        INSERT INTO automation_fingerprints (fingerprint, added_at)
                        VALUES (:fingerprint, :added_at)
                        ON CONFLICT (fingerprint) DO NOTHING
                        """
                    ),
                    row,
                )
                added += int(result.rowcount == 1)
        return added

    @staticmethod
    def _queue_item(row: RowMapping | None) -> QueueItem | None:
        if row is None:
            return None
        telegram_ids = json.loads(row["telegram_message_ids"] or "[]")
        published_at = datetime.fromisoformat(str(row["published_at"]))
        return QueueItem(
            id=str(row["id"]),
            source=str(row["source"]),
            post_key=str(row["post_key"]),
            message_ids=tuple(int(value) for value in json.loads(row["message_ids"])),
            media_kind=str(row["media_kind"]),
            score=int(row["score"]),
            published_at=published_at,
            status=str(row["status"]),
            telegram_message_ids=tuple(int(value) for value in telegram_ids),
            max_mid=str(row["max_mid"]) if row["max_mid"] is not None else None,
            error=str(row["error"]) if row["error"] is not None else None,
        )

    def queue_item(self, item_id: str) -> QueueItem | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text("SELECT * FROM automation_queue WHERE id = :id"),
                {"id": item_id},
            ).mappings().one_or_none()
            return self._queue_item(row)

    def pending_items(
        self,
        media_kind: str = "any",
        source: str | None = None,
        *,
        limit: int = 120,
    ) -> list[QueueItem]:
        clauses = ["status = 'pending'"]
        params: dict[str, str | int] = {"limit": int(limit)}
        if media_kind != "any":
            clauses.append("media_kind = :media_kind")
            params["media_kind"] = media_kind
        if source is not None:
            clauses.append("source = :source")
            params["source"] = str(source)
        where = " AND ".join(clauses)
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"""
                    SELECT * FROM automation_queue WHERE {where}
                    ORDER BY score DESC, published_at ASC, created_at ASC
                    LIMIT :limit
                    """
                ),
                params,
            ).mappings()
            return [self._queue_item(row) for row in rows]

    def update_score(self, item_id: str, score: int) -> bool:
        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE automation_queue SET score = :score
                    WHERE id = :id AND status = 'pending'
                    """
                ),
                {"id": item_id, "score": int(score)},
            )
            return result.rowcount == 1

    def claim_item(self, item_id: str) -> QueueItem | None:
        with self._engine.begin() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT * FROM automation_queue
                    WHERE id = :id AND status = 'pending'
                    """
                ),
                {"id": item_id},
            ).mappings().one_or_none()
            if row is None:
                return None
            result = connection.execute(
                text(
                    """
                    UPDATE automation_queue SET status = 'processing', error = NULL
                    WHERE id = :id AND status = 'pending'
                    """
                ),
                {"id": item_id},
            )
            if result.rowcount != 1:
                return None
            updated = dict(row)
            updated["status"] = "processing"
            updated["error"] = None
            return self._queue_item(updated)

    def claim(self, media_kind: str = "any", source: str | None = None) -> QueueItem | None:
        clauses = ["status = 'pending'"]
        params: dict[str, str] = {}
        if media_kind != "any":
            clauses.append("media_kind = :media_kind")
            params["media_kind"] = media_kind
        if source is not None:
            clauses.append("source = :source")
            params["source"] = str(source)
        where = " AND ".join(clauses)
        with self._engine.begin() as connection:
            row = connection.execute(
                text(
                    f"""
                    SELECT * FROM automation_queue WHERE {where}
                    ORDER BY score DESC, published_at ASC, created_at ASC
                    LIMIT 1
                    """
                ),
                params,
            ).mappings().one_or_none()
            if row is None:
                return None
            result = connection.execute(
                text(
                    """
                    UPDATE automation_queue SET status = 'processing', error = NULL
                    WHERE id = :id AND status = 'pending'
                    """
                ),
                {"id": row["id"]},
            )
            if result.rowcount != 1:
                return None
            updated = dict(row)
            updated["status"] = "processing"
            updated["error"] = None
            return self._queue_item(updated)

    def save_telegram_delivery(self, item_id: str, message_ids: Iterable[int]) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE automation_queue SET telegram_message_ids = :ids
                    WHERE id = :id
                    """
                ),
                {"id": item_id, "ids": json.dumps([int(value) for value in message_ids])},
            )

    def complete(self, item_id: str, max_mid: str) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE automation_queue
                    SET status = 'published', max_mid = :max_mid, error = NULL
                    WHERE id = :id
                    """
                ),
                {"id": item_id, "max_mid": str(max_mid)},
            )

    def mark_error(self, item_id: str, status: str, error: str) -> None:
        if status not in {"failed", "ambiguous"}:
            raise ValueError("Ошибка очереди должна быть failed или ambiguous.")
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE automation_queue SET status = :status, error = :error
                    WHERE id = :id
                    """
                ),
                {"id": item_id, "status": status, "error": error[:1000]},
            )

    def retry(self, item_id: str) -> bool:
        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE automation_queue SET status = 'pending', error = NULL
                    WHERE id = :id AND status IN ('failed', 'ambiguous')
                    """
                ),
                {"id": item_id},
            )
            return result.rowcount == 1

    def release(self, item_id: str) -> bool:
        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE automation_queue SET status = 'pending', error = NULL
                    WHERE id = :id AND status = 'processing'
                    """
                ),
                {"id": item_id},
            )
            return result.rowcount == 1

    def recover_interrupted(self) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE automation_queue SET status = 'pending', error = NULL
                    WHERE status = 'processing' AND telegram_message_ids IS NOT NULL
                    """
                )
            )
            connection.execute(
                text(
                    """
                    UPDATE automation_queue
                    SET status = 'ambiguous',
                        error = 'Процесс остановился до фиксации Telegram-этапа'
                    WHERE status = 'processing' AND telegram_message_ids IS NULL
                    """
                )
            )

    def queue_counts(self) -> dict[str, int]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text("SELECT status, COUNT(*) AS total FROM automation_queue GROUP BY status")
            )
            return {str(row.status): int(row.total) for row in rows}

    def pending_count(self) -> int:
        return self.queue_counts().get("pending", 0)

    def expire_pending_before(self, cutoff: datetime) -> int:
        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE automation_queue
                    SET status = 'expired', error = NULL
                    WHERE status = 'pending' AND published_at < :cutoff
                    """
                ),
                {"cutoff": cutoff.isoformat()},
            )
            return int(result.rowcount)

    def claim_slot(self, run_date: date, run_time: str) -> bool:
        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    INSERT INTO automation_slot_runs (run_date, run_time, claimed_at)
                    VALUES (:run_date, :run_time, :claimed_at)
                    ON CONFLICT (run_date, run_time) DO NOTHING
                    """
                ),
                {
                    "run_date": run_date.isoformat(),
                    "run_time": run_time,
                    "claimed_at": _utcnow(),
                },
            )
            return result.rowcount == 1
