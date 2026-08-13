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
                [(source.peer, source.title) for source in state.sources()],
                [("animeworldmem", "Anime World")],
            )
            state.set_setting("signature_text", "КАНАЛ")
            self.assertEqual(state.get_setting("signature_text"), "КАНАЛ")

            state.set_slot(Slot("14:00", "video", "animeworldmem"))
            state.set_slot(Slot("08:00", "any", None))
            state.set_slot(Slot("14:00", "image", None))
            self.assertEqual(
                state.slots(),
                [Slot("08:00", "any", None), Slot("14:00", "image", None)],
            )
            self.assertTrue(state.remove_slot("14:00"))
            self.assertFalse(state.remove_slot("14:00"))
            self.assertTrue(state.remove_source("animeworldmem"))
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


if __name__ == "__main__":
    unittest.main()
