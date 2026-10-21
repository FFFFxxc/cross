import importlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


CHANNEL = -77809668353385
NOW = 2_000_000_000_000


def message(mid=1, *, chat_id=CHANNEL, time=NOW, kind="CHANNEL", own=None):
    return SimpleNamespace(
        id=mid, chat_id=chat_id, time=time, type=kind,
        reaction_info=SimpleNamespace(your_reaction=own),
    )


class FakeAPI:
    def __init__(self):
        self.sent = []
        self.existing = None
        self.failure = None

    async def get_reactions(self, chat_id, message_ids):
        if self.failure:
            raise self.failure
        return {str(message_ids[0]): SimpleNamespace(your_reaction=self.existing)}

    async def add_reaction(self, chat_id, message_id, reaction):
        self.sent.append((chat_id, message_id, reaction))
        return SimpleNamespace(your_reaction=reaction)


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.module = importlib.import_module("max_reactions.worker")
        self.state = self.module.ReactionState(Path(self.directory.name) / "state.sqlite3")
        self.addCleanup(self.state.close)
        self.api = FakeAPI()
        self.worker = self.module.ReactionWorker(
            self.api, self.state, channel_id=CHANNEL, emoji="👍",
            started_at_ms=NOW - 1_000, max_age_ms=900_000,
            max_per_poll=1, dry_run=False,
        )

    async def test_new_target_post_receives_one_reaction(self):
        self.assertEqual(await self.worker.tick([message()], now_ms=NOW), 1)
        self.assertEqual(self.api.sent, [(CHANNEL, 1, "👍")])

    async def test_other_chat_and_service_events_are_ignored(self):
        events = [message(chat_id=55), message(2, kind="SERVICE")]
        self.assertEqual(await self.worker.tick(events, now_ms=NOW), 0)
        self.assertEqual(self.api.sent, [])

    async def test_startup_history_and_expired_posts_are_ignored(self):
        events = [message(time=NOW - 1_000), message(2, time=NOW - 1_000_000)]
        self.assertEqual(await self.worker.tick(events, now_ms=NOW), 0)

    async def test_duplicate_events_and_repeated_polls_are_idempotent(self):
        await self.worker.tick([message(), message()], now_ms=NOW)
        await self.worker.tick([message()], now_ms=NOW + 100)
        self.assertEqual(len(self.api.sent), 1)

    async def test_durable_claim_survives_a_new_worker(self):
        await self.worker.tick([message()], now_ms=NOW)
        worker = self.module.ReactionWorker(
            self.api, self.state, channel_id=CHANNEL, emoji="👍",
            started_at_ms=NOW - 1_000, max_age_ms=900_000,
            max_per_poll=1, dry_run=False,
        )
        await worker.tick([message()], now_ms=NOW + 100)
        self.assertEqual(len(self.api.sent), 1)

    async def test_manually_chosen_reaction_is_not_replaced(self):
        self.api.existing = "❤️"
        await self.worker.tick([message()], now_ms=NOW)
        self.assertEqual(self.api.sent, [])

    async def test_visible_own_reaction_is_not_replaced(self):
        await self.worker.tick([message(own="❤️")], now_ms=NOW)
        self.assertEqual(self.api.sent, [])

    async def test_api_failure_is_not_retried_for_the_same_post(self):
        self.api.failure = ConnectionError("test")
        with self.assertRaises(ConnectionError):
            await self.worker.tick([message()], now_ms=NOW)
        self.api.failure = None
        await self.worker.tick([message()], now_ms=NOW + 100)
        self.assertEqual(self.api.sent, [])

    async def test_rate_limit_chooses_oldest_new_post_then_next(self):
        events = [message(2, time=NOW + 1), message()]
        await self.worker.tick(events, now_ms=NOW + 2)
        self.assertEqual(self.api.sent, [(CHANNEL, 1, "👍")])
        await self.worker.tick(events, now_ms=NOW + 100)
        self.assertEqual(self.api.sent[-1], (CHANNEL, 2, "👍"))

    async def test_dry_run_never_calls_or_reserves_reactions(self):
        self.worker.dry_run = True
        await self.worker.tick([message()], now_ms=NOW)
        self.assertEqual(self.api.sent, [])
        self.worker.dry_run = False
        await self.worker.tick([message()], now_ms=NOW)
        self.assertEqual(len(self.api.sent), 1)

    async def test_malformed_ids_and_future_messages_fail_closed(self):
        events = [message(mid="1"), message(2, time=NOW + 1), message(3, chat_id=True)]
        self.assertEqual(await self.worker.tick(events, now_ms=NOW), 0)

    async def test_zero_target_id_is_rejected(self):
        with self.assertRaises(ValueError):
            self.module.ReactionWorker(
                self.api, self.state, channel_id=0, emoji="👍",
                started_at_ms=NOW, max_age_ms=900_000,
                max_per_poll=1, dry_run=False,
            )

    async def test_scoped_history_restores_sdk_messages_missing_chat_id(self):
        from pymax import Message
        original = Message(id=7, time=NOW, type="CHANNEL")
        values = self.module.bind_scoped_history([original], CHANNEL)
        self.assertIsNone(original.chat_id)
        self.assertEqual(values[0].chat_id, CHANNEL)
        await self.worker.tick(values, now_ms=NOW)
        self.assertEqual(self.api.sent, [(CHANNEL, 7, "👍")])

    async def test_scoped_history_does_not_overwrite_foreign_chat_id(self):
        values = self.module.bind_scoped_history([message(chat_id=55)], CHANNEL)
        await self.worker.tick(values, now_ms=NOW)
        self.assertEqual(values[0].chat_id, 55)
        self.assertEqual(self.api.sent, [])

    async def test_scoped_history_rejects_unknown_target(self):
        with self.assertRaises(ValueError):
            self.module.bind_scoped_history([message()], 0)


if __name__ == "__main__":
    unittest.main()
