import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from tg_migrator.state import MigrationState, Slot


class StateTests(unittest.TestCase):
    def test_tracks_messages_per_route(self):
        with tempfile.TemporaryDirectory() as directory:
            state = MigrationState(Path(directory) / "state.sqlite3")
            state.mark_transferred("a", "b", [1, 2])
            self.assertEqual(
                state.transferred_ids("a", "b", [1, 2, 3]),
                {1, 2},
            )
            self.assertEqual(state.transferred_ids("a", "c", [1]), set())
            self.assertEqual(state.total("a", "b"), 2)
            state.close()

    def test_sources_settings_and_slots_are_replaceable(self):
        with tempfile.TemporaryDirectory() as directory:
            state = MigrationState(Path(directory) / "state.sqlite3")

            self.assertTrue(state.add_source("animeworldmem", "Anime World"))
            self.assertFalse(state.add_source("animeworldmem", "Duplicate"))
            self.assertEqual(
                [(source.peer, source.title, source.category) for source in state.sources()],
                [("animeworldmem", "Anime World", "content")],
            )
            state.set_setting("signature_text", "КАНАЛ")
            self.assertEqual(state.get_setting("signature_text"), "КАНАЛ")

            state.set_slot(Slot("14:00", "video", "animeworldmem"))
            state.set_slot(Slot("08:00", "any", None))
            state.set_slot(Slot("14:00", "image", None))
            state.set_slot(Slot("16:00", "news", None))
            self.assertEqual(
                state.slots(),
                [
                    Slot("08:00", "any", None),
                    Slot("14:00", "image", None),
                    Slot("16:00", "news", None),
                ],
            )
            self.assertTrue(state.remove_slot("14:00"))
            self.assertFalse(state.remove_slot("14:00"))
            self.assertTrue(state.remove_source("animeworldmem"))
            state.close()

    def test_additive_schema_preserves_legacy_rows_and_stores_dashboard_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state.sqlite3"
            with sqlite3.connect(database) as connection:
                connection.executescript(
                    """
                    CREATE TABLE automation_sources (
                        peer TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        added_at TEXT NOT NULL
                    );
                    CREATE TABLE automation_queue (
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
                    );
                    """
                )

            state = MigrationState(database)
            self.assertTrue(state.add_source("source", "Source"))
            self.assertTrue(
                state.update_source_availability("source", "available")
            )
            item = state.enqueue(
                "source",
                "message:1",
                (1,),
                "image",
                10,
                datetime.now(timezone.utc),
            )
            self.assertTrue(
                state.update_post_metadata(
                    item.id,
                    caption_excerpt="caption",
                    views_count=5_000,
                    reactions_count=120,
                    forwards_count=31,
                    preview_mime="image/webp",
                    preview_data=b"preview",
                )
            )
            state.close()

            state = MigrationState(database)
            saved = state.queue_item(item.id)
            self.assertEqual(saved.caption_excerpt, "caption")
            self.assertEqual(saved.views_count, 5_000)
            self.assertEqual(saved.reactions_count, 120)
            self.assertEqual(saved.forwards_count, 31)
            self.assertEqual(saved.preview_mime, "image/webp")
            self.assertEqual(saved.preview_data, b"preview")
            source = state.sources()[0]
            self.assertEqual(source.category, "content")
            self.assertEqual(source.availability, "available")
            self.assertIsNotNone(source.checked_at)
            self.assertIsNone(source.error)
            self.assertEqual(saved.content_category, "content")
            with self.assertRaisesRegex(ValueError, "131072"):
                state.update_post_metadata(
                    item.id,
                    preview_mime="image/webp",
                    preview_data=b"x" * 131_073,
                )
            state.close()

    def test_source_category_updates_only_unprocessed_queue_items(self):
        with tempfile.TemporaryDirectory() as directory:
            state = MigrationState(Path(directory) / "state.sqlite3")
            self.assertTrue(state.add_source("anime-news", "Anime News", "news"))
            self.assertEqual(state.sources()[0].category, "news")
            published_at = datetime.now(timezone.utc)
            pending = state.enqueue(
                "anime-news", "message:1", (1,), "image", 10, published_at,
                content_category="news",
            )
            candidate = state.enqueue(
                "anime-news", "message:2", (2,), "video", 9, published_at,
                content_category="news", status="candidate",
            )
            published = state.enqueue(
                "anime-news", "message:3", (3,), "any", 8, published_at,
                content_category="news",
            )
            state.claim_item(published.id)
            state.complete(published.id, "mid")

            self.assertTrue(state.set_source_category("anime-news", "content"))

            self.assertEqual(state.queue_item(pending.id).content_category, "content")
            self.assertEqual(state.queue_item(candidate.id).content_category, "content")
            self.assertEqual(state.queue_item(published.id).content_category, "news")
            self.assertEqual(
                [item.id for item in state.pending_items(content_category="content")],
                [pending.id],
            )
            with self.assertRaisesRegex(ValueError, "content или news"):
                state.set_source_category("anime-news", "unknown")
            state.close()

    def test_queue_deduplicates_claims_and_records_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            state = MigrationState(Path(directory) / "state.sqlite3")
            published = datetime(2026, 8, 13, 18, 0, tzinfo=timezone.utc)

            item = state.enqueue(
                "animeworldmem",
                "album:9",
                (90, 91),
                "video",
                700,
                published,
            )
            duplicate = state.enqueue(
                "animeworldmem",
                "album:9",
                (90, 91),
                "video",
                999,
                published,
            )
            self.assertIsNotNone(item)
            self.assertIsNone(duplicate)

            claimed = state.claim("video", "animeworldmem")
            self.assertEqual(claimed.id, item.id)
            self.assertEqual(claimed.message_ids, (90, 91))
            self.assertIsNone(state.claim("any"))

            state.save_telegram_delivery(item.id, (501, 502))
            state.complete(item.id, "max-mid-1")
            saved = state.queue_item(item.id)
            self.assertEqual(saved.status, "published")
            self.assertEqual(saved.telegram_message_ids, (501, 502))
            self.assertEqual(saved.max_mid, "max-mid-1")
            self.assertEqual(state.queue_counts(), {"published": 1})
            state.close()

    def test_queue_deduplicates_same_media_fingerprint_across_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            state = MigrationState(Path(directory) / "state.sqlite3")
            published = datetime.now(timezone.utc)
            first = state.enqueue(
                "source-a", "message:1", (1,), "video", 1, published,
                fingerprint="media:777",
            )
            second = state.enqueue(
                "source-b", "message:99", (99,), "video", 2, published,
                fingerprint="media:777",
            )
            self.assertIsNotNone(first)
            self.assertIsNone(second)
            state.close()

    def test_dashboard_actions_are_atomic_and_publish_is_unique_while_active(self):
        with tempfile.TemporaryDirectory() as directory:
            state = MigrationState(Path(directory) / "state.sqlite3")
            item = state.enqueue(
                "source",
                "message:1",
                (1,),
                "image",
                10,
                datetime.now(timezone.utc),
            )

            action = state.enqueue_action(
                "publish_now",
                {"item_id": item.id},
                queue_item_id=item.id,
            )
            self.assertIsNotNone(action)
            self.assertIsNone(
                state.enqueue_action(
                    "publish_now",
                    {"item_id": item.id},
                    queue_item_id=item.id,
                )
            )
            claimed = state.claim_action()
            self.assertEqual(claimed.id, action.id)
            self.assertEqual(claimed.status, "processing")
            self.assertIsNone(state.claim_action())

            self.assertTrue(
                state.complete_action(action.id, {"max_mid": "mid-1"})
            )
            completed = state.action(action.id)
            self.assertEqual(completed.status, "completed")
            self.assertEqual(completed.result, {"max_mid": "mid-1"})
            self.assertIsNotNone(completed.completed_at)
            self.assertIsNotNone(
                state.enqueue_action(
                    "publish_now",
                    {"item_id": item.id},
                    queue_item_id=item.id,
                )
            )
            state.close()

    def test_dashboard_action_failure_skip_and_heartbeat_are_guarded(self):
        with tempfile.TemporaryDirectory() as directory:
            state = MigrationState(Path(directory) / "state.sqlite3")
            item = state.enqueue(
                "source",
                "message:1",
                (1,),
                "video",
                10,
                datetime.now(timezone.utc),
            )
            failed = state.enqueue_action("scan", {"count": 10})
            state.claim_action()
            self.assertTrue(state.fail_action(failed.id, "x" * 1_100))
            self.assertEqual(len(state.action(failed.id).error), 1_000)
            self.assertFalse(state.complete_action(failed.id, {"added": 1}))

            self.assertTrue(state.skip_item(item.id))
            self.assertFalse(state.skip_item(item.id))
            self.assertEqual(state.queue_item(item.id).status, "skipped")

            candidate = state.enqueue(
                "source",
                "message:2",
                (2,),
                "image",
                20,
                datetime.now(timezone.utc),
                status="candidate",
            )
            self.assertTrue(state.skip_item(candidate.id))
            self.assertEqual(state.queue_item(candidate.id).status, "skipped")
            self.assertEqual(state.recent_actions(1)[0].id, failed.id)

    def test_ai_caption_state_is_claimed_saved_and_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            state = MigrationState(Path(directory) / "state.sqlite3")
            item = state.enqueue(
                "source", "message:91", (91,), "image", 10,
                datetime.now(timezone.utc),
            )
            state.update_post_metadata(
                item.id,
                preview_mime="image/webp",
                preview_data=b"preview",
            )

            claimed = state.claim_ai_caption_item()
            self.assertEqual(claimed.id, item.id)
            self.assertEqual(claimed.ai_caption_status, "processing")
            self.assertIsNone(state.claim_ai_caption_item())
            state.save_ai_caption(item.id, "Короткая подпись", "1:model")
            saved = state.queue_item(item.id)
            self.assertEqual(saved.ai_caption, "Короткая подпись")
            self.assertEqual(saved.ai_caption_status, "generated")

            self.assertTrue(state.reset_ai_caption(item.id))
            reset = state.queue_item(item.id)
            self.assertIsNone(reset.ai_caption)
            self.assertEqual(reset.ai_caption_status, "unchecked")
            state.close()

            heartbeat = state.touch_worker_heartbeat()
            self.assertEqual(
                state.get_setting("worker_heartbeat_at"),
                heartbeat.isoformat(),
            )
            state.close()

    def test_ambiguous_items_require_manual_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            state = MigrationState(Path(directory) / "state.sqlite3")
            item = state.enqueue(
                "source",
                "message:1",
                (1,),
                "image",
                3,
                datetime.now(timezone.utc),
            )
            state.claim("any")
            state.mark_error(item.id, "ambiguous", "MAX timeout")

            self.assertIsNone(state.claim("any"))
            self.assertTrue(state.retry(item.id))
            claimed = state.claim("image")
            self.assertEqual(claimed.id, item.id)
            self.assertTrue(state.release(item.id))
            self.assertEqual(state.claim("image").id, item.id)
            state.close()

    def test_recovery_resumes_saved_telegram_stage_but_blocks_unknown_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            state = MigrationState(Path(directory) / "state.sqlite3")
            first = state.enqueue(
                "source", "message:1", (1,), "image", 10,
                datetime.now(timezone.utc),
            )
            second = state.enqueue(
                "source", "message:2", (2,), "video", 9,
                datetime.now(timezone.utc),
            )
            state.claim("image")
            state.claim("video")
            state.save_telegram_delivery(second.id, (200,))

            state.recover_interrupted()

            self.assertEqual(state.queue_item(first.id).status, "ambiguous")
            self.assertEqual(state.queue_item(second.id).status, "pending")
            state.close()

    def test_slot_run_is_claimed_once(self):
        with tempfile.TemporaryDirectory() as directory:
            state = MigrationState(Path(directory) / "state.sqlite3")
            self.assertTrue(state.claim_slot(date(2026, 8, 14), "14:00"))
            self.assertFalse(state.claim_slot(date(2026, 8, 14), "14:00"))
            self.assertTrue(state.claim_slot(date(2026, 8, 15), "14:00"))
            state.close()

    def test_candidate_pool_promotes_only_selected_top_items(self):
        with tempfile.TemporaryDirectory() as directory:
            state = MigrationState(Path(directory) / "state.sqlite3")
            first = state.enqueue(
                "source-a", "message:1", (1,), "image", 100,
                datetime.now(timezone.utc), status="candidate",
            )
            second = state.enqueue(
                "source-b", "message:2", (2,), "video", 90,
                datetime.now(timezone.utc), status="candidate",
            )
            extra = state.enqueue(
                "source-a", "message:3", (3,), "image", 1,
                datetime.now(timezone.utc), status="pending",
            )

            state.rebalance_pending([first.id, second.id])

            self.assertEqual(
                {item.id for item in state.pending_items()},
                {first.id, second.id},
            )
            self.assertEqual(state.queue_item(extra.id).status, "candidate")
            self.assertEqual(len(state.pool_items()), 3)
            state.close()


if __name__ == "__main__":
    unittest.main()
