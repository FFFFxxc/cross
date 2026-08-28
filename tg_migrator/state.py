from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, RowMapping

CONTENT_CATEGORIES = {"content", "news"}


@dataclass(frozen=True)
class Source:
    peer: str
    title: str
    category: str = "content"
    availability: str = "unknown"
    checked_at: datetime | None = None
    error: str | None = None


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
    content_category: str
    score: int
    published_at: datetime
    status: str
    telegram_message_ids: tuple[int, ...]
    max_mid: str | None
    error: str | None
    caption_excerpt: str
    views_count: int
    reactions_count: int
    forwards_count: int
    metrics_known: bool
    preview_mime: str | None
    preview_data: bytes | None
    preview_checked_at: datetime | None
    ai_caption: str | None
    ai_caption_status: str
    ai_caption_provider: str | None
    ai_caption_error: str | None
    ai_caption_generated_at: datetime | None


@dataclass(frozen=True)
class DashboardAction:
    id: str
    kind: str
    payload: dict[str, object]
    status: str
    queue_item_id: str | None
    result: dict[str, object] | None
    error: str | None
    created_at: datetime
    claimed_at: datetime | None
    completed_at: datetime | None


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
        binary_type = "BYTEA" if self._engine.dialect.name == "postgresql" else "BLOB"
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
            CREATE TABLE IF NOT EXISTS automation_actions (
                id TEXT PRIMARY KEY,
                action_kind TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT NOT NULL,
                queue_item_id TEXT,
                result TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                claimed_at TEXT,
                completed_at TEXT
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS automation_actions_pending
            ON automation_actions (status, created_at)
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS automation_actions_active_publish
            ON automation_actions (queue_item_id)
            WHERE action_kind = 'publish_now'
              AND status IN ('pending', 'processing')
              AND queue_item_id IS NOT NULL
            """,
            """
            CREATE INDEX IF NOT EXISTS automation_queue_claim
            ON automation_queue (status, media_kind, score, published_at)
            """,
        )
        with self._engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
            migrations = {
                "automation_sources": {
                    "category": "TEXT NOT NULL DEFAULT 'content'",
                    "availability": "TEXT NOT NULL DEFAULT 'unknown'",
                    "checked_at": "TEXT",
                    "error": "TEXT",
                },
                "automation_queue": {
                    "content_category": "TEXT NOT NULL DEFAULT 'content'",
                    "caption_excerpt": "TEXT NOT NULL DEFAULT ''",
                    "views_count": "INTEGER NOT NULL DEFAULT 0",
                    "reactions_count": "INTEGER NOT NULL DEFAULT 0",
                    "forwards_count": "INTEGER NOT NULL DEFAULT 0",
                    "metrics_known": "INTEGER NOT NULL DEFAULT 0",
                    "preview_mime": "TEXT",
                    "preview_data": binary_type,
                    "preview_checked_at": "TEXT",
                    "ai_caption": "TEXT",
                    "ai_caption_status": "TEXT NOT NULL DEFAULT 'unchecked'",
                    "ai_caption_provider": "TEXT",
                    "ai_caption_error": "TEXT",
                    "ai_caption_generated_at": "TEXT",
                },
            }
            inspector = inspect(connection)
            for table_name, columns in migrations.items():
                existing = {
                    str(column["name"])
                    for column in inspector.get_columns(table_name)
                }
                for column_name, definition in columns.items():
                    if column_name not in existing:
                        connection.execute(
                            text(
                                f"ALTER TABLE {table_name} "
                                f"ADD COLUMN {column_name} {definition}"
                            )
                        )

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

    def add_source(self, peer: str, title: str, category: str = "content") -> bool:
        if category not in CONTENT_CATEGORIES:
            raise ValueError("Категория источника: content или news.")
        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    INSERT INTO automation_sources (peer, title, category, added_at)
                    VALUES (:peer, :title, :category, :added_at)
                    ON CONFLICT (peer) DO NOTHING
                    """
                ),
                {
                    "peer": str(peer),
                    "title": title,
                    "category": category,
                    "added_at": _utcnow(),
                },
            )
            return result.rowcount == 1

    def set_source_category(self, peer: str, category: str) -> bool:
        if category not in CONTENT_CATEGORIES:
            raise ValueError("Категория источника: content или news.")
        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE automation_sources SET category = :category
                    WHERE peer = :peer
                    """
                ),
                {"peer": str(peer), "category": category},
            )
            if result.rowcount == 1:
                connection.execute(
                    text(
                        """
                        UPDATE automation_queue SET content_category = :category
                        WHERE source = :peer
                          AND status IN ('pending', 'candidate')
                        """
                    ),
                    {"peer": str(peer), "category": category},
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
                text(
                    """
                    SELECT peer, title, category, availability, checked_at, error
                    FROM automation_sources ORDER BY added_at, peer
                    """
                )
            )
            return [
                Source(
                    peer=str(row.peer),
                    title=str(row.title),
                    category=str(row.category),
                    availability=str(row.availability),
                    checked_at=(
                        datetime.fromisoformat(str(row.checked_at))
                        if row.checked_at is not None
                        else None
                    ),
                    error=str(row.error) if row.error is not None else None,
                )
                for row in rows
            ]

    def update_source_availability(
        self,
        peer: str,
        availability: str,
        error: str | None = None,
    ) -> bool:
        if availability not in {"unknown", "available", "unavailable"}:
            raise ValueError("Доступность: unknown, available или unavailable.")
        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE automation_sources
                    SET availability = :availability,
                        checked_at = :checked_at,
                        error = :error
                    WHERE peer = :peer
                    """
                ),
                {
                    "peer": str(peer),
                    "availability": availability,
                    "checked_at": _utcnow(),
                    "error": error[:1000] if error is not None else None,
                },
            )
            return result.rowcount == 1

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
        if slot.kind not in {"any", "video", "image", "news"}:
            raise ValueError("Тип слота: any, video, image или news.")
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
        status: str = "pending",
        content_category: str = "content",
    ) -> QueueItem | None:
        if status not in {"pending", "candidate"}:
            raise ValueError("Новый пост может быть pending или candidate.")
        if content_category not in CONTENT_CATEGORIES:
            raise ValueError("Категория публикации: content или news.")
        item_id = uuid.uuid4().hex[:12]
        params = {
            "id": item_id,
            "source": str(source),
            "post_key": post_key,
            "message_ids": json.dumps([int(value) for value in message_ids]),
            "media_kind": media_kind,
            "content_category": content_category,
            "score": int(score),
            "published_at": published_at.isoformat(),
            "status": status,
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
                        id, source, post_key, message_ids, media_kind,
                        content_category, score,
                        published_at, status, created_at
                    ) VALUES (
                        :id, :source, :post_key, :message_ids, :media_kind,
                        :content_category, :score, :published_at, :status,
                        :created_at
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
            content_category=str(row["content_category"]),
            score=int(row["score"]),
            published_at=published_at,
            status=str(row["status"]),
            telegram_message_ids=tuple(int(value) for value in telegram_ids),
            max_mid=str(row["max_mid"]) if row["max_mid"] is not None else None,
            error=str(row["error"]) if row["error"] is not None else None,
            caption_excerpt=str(row["caption_excerpt"]),
            views_count=int(row["views_count"]),
            reactions_count=int(row["reactions_count"]),
            forwards_count=int(row["forwards_count"]),
            metrics_known=bool(row["metrics_known"]),
            preview_mime=(
                str(row["preview_mime"])
                if row["preview_mime"] is not None
                else None
            ),
            preview_data=(
                bytes(row["preview_data"])
                if row["preview_data"] is not None
                else None
            ),
            preview_checked_at=(
                datetime.fromisoformat(str(row["preview_checked_at"]))
                if row["preview_checked_at"] is not None
                else None
            ),
            ai_caption=(
                str(row["ai_caption"])
                if row["ai_caption"] is not None
                else None
            ),
            ai_caption_status=str(row["ai_caption_status"]),
            ai_caption_provider=(
                str(row["ai_caption_provider"])
                if row["ai_caption_provider"] is not None
                else None
            ),
            ai_caption_error=(
                str(row["ai_caption_error"])
                if row["ai_caption_error"] is not None
                else None
            ),
            ai_caption_generated_at=(
                datetime.fromisoformat(str(row["ai_caption_generated_at"]))
                if row["ai_caption_generated_at"] is not None
                else None
            ),
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
        content_category: str | None = None,
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
        if content_category is not None:
            if content_category not in CONTENT_CATEGORIES:
                raise ValueError("Категория публикации: content или news.")
            clauses.append("content_category = :content_category")
            params["content_category"] = content_category
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

    def pool_items(
        self,
        media_kind: str = "any",
        source: str | None = None,
        *,
        content_category: str | None = None,
        limit: int = 1000,
    ) -> list[QueueItem]:
        clauses = ["status IN ('pending', 'candidate')"]
        params: dict[str, str | int] = {"limit": int(limit)}
        if media_kind != "any":
            clauses.append("media_kind = :media_kind")
            params["media_kind"] = media_kind
        if source is not None:
            clauses.append("source = :source")
            params["source"] = str(source)
        if content_category is not None:
            if content_category not in CONTENT_CATEGORIES:
                raise ValueError("Категория публикации: content или news.")
            clauses.append("content_category = :content_category")
            params["content_category"] = content_category
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"""
                    SELECT * FROM automation_queue
                    WHERE {' AND '.join(clauses)}
                    ORDER BY score DESC, published_at DESC, created_at DESC
                    LIMIT :limit
                    """
                ),
                params,
            ).mappings()
            return [self._queue_item(row) for row in rows]

    def items_missing_previews(
        self,
        media_kind: str = "any",
        source: str | None = None,
        *,
        content_category: str | None = None,
        limit: int = 120,
    ) -> list[QueueItem]:
        clauses = [
            "status IN ('pending', 'candidate')",
            "preview_data IS NULL",
        ]
        params: dict[str, str | int] = {"limit": int(limit)}
        if media_kind != "any":
            clauses.append("media_kind = :media_kind")
            params["media_kind"] = media_kind
        if source is not None:
            clauses.append("source = :source")
            params["source"] = str(source)
        if content_category is not None:
            if content_category not in CONTENT_CATEGORIES:
                raise ValueError("Категория публикации: content или news.")
            clauses.append("content_category = :content_category")
            params["content_category"] = content_category
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"""
                    SELECT * FROM automation_queue
                    WHERE {' AND '.join(clauses)}
                    ORDER BY
                        CASE WHEN preview_checked_at IS NULL THEN 0 ELSE 1 END,
                        preview_checked_at ASC,
                        score DESC,
                        published_at DESC,
                        created_at DESC
                    LIMIT :limit
                    """
                ),
                params,
            ).mappings()
            return [self._queue_item(row) for row in rows]

    def rebalance_pending(self, selected_ids: Iterable[str]) -> None:
        values = list(dict.fromkeys(str(value) for value in selected_ids))
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE automation_queue SET status = 'candidate' "
                    "WHERE status = 'pending'"
                )
            )
            for item_id in values:
                connection.execute(
                    text(
                        "UPDATE automation_queue SET status = 'pending' "
                        "WHERE id = :id AND status = 'candidate'"
                    ),
                    {"id": item_id},
                )

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

    def update_post_metadata(
        self,
        item_id: str,
        *,
        score: int | None = None,
        caption_excerpt: str | None = None,
        views_count: int | None = None,
        reactions_count: int | None = None,
        forwards_count: int | None = None,
        metrics_known: bool | None = None,
        preview_mime: str | None = None,
        preview_data: bytes | None = None,
        preview_checked_at: datetime | None = None,
    ) -> bool:
        if preview_data is not None and len(preview_data) > 131_072:
            raise ValueError("Превью не может быть больше 131072 байт.")
        counters = {
            "views_count": views_count,
            "reactions_count": reactions_count,
            "forwards_count": forwards_count,
        }
        if any(value is not None and int(value) < 0 for value in counters.values()):
            raise ValueError("Счётчики публикации не могут быть отрицательными.")

        values: dict[str, object] = {"id": item_id}
        assignments: list[str] = []
        if score is not None:
            assignments.append("score = :score")
            values["score"] = int(score)
        if caption_excerpt is not None:
            assignments.append("caption_excerpt = :caption_excerpt")
            values["caption_excerpt"] = caption_excerpt[:2000]
        for name, value in counters.items():
            if value is not None:
                assignments.append(f"{name} = :{name}")
                values[name] = int(value)
        if metrics_known is not None:
            assignments.append("metrics_known = :metrics_known")
            values["metrics_known"] = int(bool(metrics_known))
        if preview_mime is not None:
            assignments.append("preview_mime = :preview_mime")
            values["preview_mime"] = preview_mime[:100]
        if preview_data is not None:
            assignments.append("preview_data = :preview_data")
            values["preview_data"] = preview_data
        if preview_checked_at is not None:
            assignments.append("preview_checked_at = :preview_checked_at")
            values["preview_checked_at"] = preview_checked_at.isoformat()
        if not assignments:
            return self.queue_item(item_id) is not None

        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    "UPDATE automation_queue SET "
                    + ", ".join(assignments)
                    + " WHERE id = :id"
                ),
                values,
            )
            return result.rowcount == 1

    def claim_ai_caption(self, item_id: str) -> QueueItem | None:
        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE automation_queue
                    SET ai_caption_status = 'processing', ai_caption_error = NULL
                    WHERE id = :id
                      AND status IN ('pending', 'candidate', 'processing')
                      AND ai_caption_status = 'unchecked'
                    """
                ),
                {"id": item_id},
            )
            if result.rowcount != 1:
                return None
        return self.queue_item(item_id)

    def claim_ai_caption_item(self) -> QueueItem | None:
        with self._engine.begin() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT id FROM automation_queue
                    WHERE status IN ('pending', 'candidate')
                      AND ai_caption_status = 'unchecked'
                      AND preview_data IS NOT NULL
                    ORDER BY
                      CASE WHEN status = 'pending' THEN 0 ELSE 1 END,
                      score DESC, published_at DESC, created_at DESC
                    LIMIT 1
                    """
                )
            ).mappings().one_or_none()
            if row is None:
                return None
            result = connection.execute(
                text(
                    """
                    UPDATE automation_queue
                    SET ai_caption_status = 'processing', ai_caption_error = NULL
                    WHERE id = :id AND ai_caption_status = 'unchecked'
                    """
                ),
                {"id": str(row["id"])},
            )
            if result.rowcount != 1:
                return None
            item_id = str(row["id"])
        return self.queue_item(item_id)

    def save_ai_caption(self, item_id: str, caption: str, provider: str) -> bool:
        value = " ".join(caption.split()).strip()
        if not value:
            raise ValueError("AI-подпись не может быть пустой.")
        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE automation_queue
                    SET ai_caption = :caption,
                        ai_caption_status = 'generated',
                        ai_caption_provider = :provider,
                        ai_caption_error = NULL,
                        ai_caption_generated_at = :generated_at
                    WHERE id = :id
                    """
                ),
                {
                    "id": item_id,
                    "caption": value[:500],
                    "provider": provider[:200],
                    "generated_at": _utcnow(),
                },
            )
            return result.rowcount == 1

    def mark_ai_caption_not_needed(self, item_id: str, status: str = "not_needed") -> bool:
        if status not in {"not_needed", "no_preview"}:
            raise ValueError("Некорректный статус AI-подписи.")
        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE automation_queue
                    SET ai_caption = NULL,
                        ai_caption_status = :status,
                        ai_caption_provider = NULL,
                        ai_caption_error = NULL,
                        ai_caption_generated_at = NULL
                    WHERE id = :id
                    """
                ),
                {"id": item_id, "status": status},
            )
            return result.rowcount == 1

    def fail_ai_caption(self, item_id: str, error: str) -> bool:
        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE automation_queue
                    SET ai_caption_status = 'failed',
                        ai_caption_error = :error
                    WHERE id = :id
                    """
                ),
                {"id": item_id, "error": error[:1000]},
            )
            return result.rowcount == 1

    def reset_ai_caption(self, item_id: str) -> bool:
        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE automation_queue
                    SET ai_caption = NULL,
                        ai_caption_status = 'unchecked',
                        ai_caption_provider = NULL,
                        ai_caption_error = NULL,
                        ai_caption_generated_at = NULL
                    WHERE id = :id AND status IN ('pending', 'candidate')
                    """
                ),
                {"id": item_id},
            )
            return result.rowcount == 1

    def claim_item(self, item_id: str) -> QueueItem | None:
        with self._engine.begin() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT * FROM automation_queue
                    WHERE id = :id AND status IN ('pending', 'candidate')
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
                    WHERE id = :id AND status IN ('pending', 'candidate')
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
                    UPDATE automation_queue
                    SET ai_caption_status = 'unchecked',
                        ai_caption_error = 'Генерация прервалась при перезапуске'
                    WHERE ai_caption_status = 'processing'
                    """
                )
            )
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

    def pending_count(self, content_category: str | None = None) -> int:
        clauses = ["status = 'pending'"]
        params: dict[str, str] = {}
        if content_category is not None:
            if content_category not in CONTENT_CATEGORIES:
                raise ValueError("Категория публикации: content или news.")
            clauses.append("content_category = :content_category")
            params["content_category"] = content_category
        with self._engine.connect() as connection:
            value = connection.execute(
                text(
                    "SELECT COUNT(*) FROM automation_queue WHERE "
                    + " AND ".join(clauses)
                ),
                params,
            ).scalar_one()
            return int(value)

    def expire_pending_before(
        self,
        cutoff: datetime,
        content_category: str | None = None,
    ) -> int:
        clauses = [
            "status IN ('pending', 'candidate')",
            "published_at < :cutoff",
        ]
        params = {"cutoff": cutoff.isoformat()}
        if content_category is not None:
            if content_category not in CONTENT_CATEGORIES:
                raise ValueError("Категория публикации: content или news.")
            clauses.append("content_category = :content_category")
            params["content_category"] = content_category
        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    f"""
                    UPDATE automation_queue
                    SET status = 'expired', error = NULL
                    WHERE {' AND '.join(clauses)}
                    """
                ),
                params,
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

    @staticmethod
    def _dashboard_action(row: RowMapping | None) -> DashboardAction | None:
        if row is None:
            return None

        def parsed_at(name: str) -> datetime | None:
            value = row[name]
            return datetime.fromisoformat(str(value)) if value is not None else None

        result = json.loads(row["result"]) if row["result"] is not None else None
        return DashboardAction(
            id=str(row["id"]),
            kind=str(row["action_kind"]),
            payload=dict(json.loads(row["payload"])),
            status=str(row["status"]),
            queue_item_id=(
                str(row["queue_item_id"])
                if row["queue_item_id"] is not None
                else None
            ),
            result=dict(result) if result is not None else None,
            error=str(row["error"]) if row["error"] is not None else None,
            created_at=datetime.fromisoformat(str(row["created_at"])),
            claimed_at=parsed_at("claimed_at"),
            completed_at=parsed_at("completed_at"),
        )

    def action(self, action_id: str) -> DashboardAction | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text("SELECT * FROM automation_actions WHERE id = :id"),
                {"id": action_id},
            ).mappings().one_or_none()
            return self._dashboard_action(row)

    def enqueue_action(
        self,
        kind: str,
        payload: dict[str, object],
        *,
        queue_item_id: str | None = None,
    ) -> DashboardAction | None:
        if not kind.strip():
            raise ValueError("Тип действия не может быть пустым.")
        action_id = uuid.uuid4().hex[:16]
        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    INSERT INTO automation_actions (
                        id, action_kind, payload, status, queue_item_id, created_at
                    ) VALUES (
                        :id, :kind, :payload, 'pending', :queue_item_id, :created_at
                    )
                    ON CONFLICT DO NOTHING
                    """
                ),
                {
                    "id": action_id,
                    "kind": kind.strip(),
                    "payload": json.dumps(payload, ensure_ascii=False),
                    "queue_item_id": queue_item_id,
                    "created_at": _utcnow(),
                },
            )
            if result.rowcount != 1:
                return None
        return self.action(action_id)

    def claim_action(self) -> DashboardAction | None:
        with self._engine.begin() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT * FROM automation_actions
                    WHERE status = 'pending'
                    ORDER BY created_at, id
                    LIMIT 1
                    """
                )
            ).mappings().one_or_none()
            if row is None:
                return None
            claimed_at = _utcnow()
            result = connection.execute(
                text(
                    """
                    UPDATE automation_actions
                    SET status = 'processing', claimed_at = :claimed_at, error = NULL
                    WHERE id = :id AND status = 'pending'
                    """
                ),
                {"id": row["id"], "claimed_at": claimed_at},
            )
            if result.rowcount != 1:
                return None
            updated = dict(row)
            updated["status"] = "processing"
            updated["claimed_at"] = claimed_at
            updated["error"] = None
            return self._dashboard_action(updated)

    def complete_action(
        self,
        action_id: str,
        result: dict[str, object],
    ) -> bool:
        with self._engine.begin() as connection:
            updated = connection.execute(
                text(
                    """
                    UPDATE automation_actions
                    SET status = 'completed', result = :result,
                        error = NULL, completed_at = :completed_at
                    WHERE id = :id AND status = 'processing'
                    """
                ),
                {
                    "id": action_id,
                    "result": json.dumps(result, ensure_ascii=False),
                    "completed_at": _utcnow(),
                },
            )
            return updated.rowcount == 1

    def fail_action(self, action_id: str, error: str) -> bool:
        with self._engine.begin() as connection:
            updated = connection.execute(
                text(
                    """
                    UPDATE automation_actions
                    SET status = 'failed', error = :error,
                        completed_at = :completed_at
                    WHERE id = :id AND status = 'processing'
                    """
                ),
                {
                    "id": action_id,
                    "error": error[:1000],
                    "completed_at": _utcnow(),
                },
            )
            return updated.rowcount == 1

    def recent_actions(self, limit: int = 50) -> list[DashboardAction]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT * FROM automation_actions
                    ORDER BY created_at DESC, id DESC
                    LIMIT :limit
                    """
                ),
                {"limit": max(1, min(int(limit), 200))},
            ).mappings()
            return [self._dashboard_action(row) for row in rows]

    def skip_item(self, item_id: str) -> bool:
        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE automation_queue SET status = 'skipped', error = NULL
                    WHERE id = :id AND status IN ('pending', 'candidate')
                    """
                ),
                {"id": item_id},
            )
            return result.rowcount == 1

    def touch_worker_heartbeat(self) -> datetime:
        heartbeat = datetime.now(timezone.utc)
        self.set_setting("worker_heartbeat_at", heartbeat.isoformat())
        return heartbeat
