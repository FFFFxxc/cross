import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from tg_migrator.dashboard_actions import DashboardActionRunner
from tg_migrator.selection import MOSCOW
from tg_migrator.state import MigrationState


class FakeMaxClient:
    def __init__(self):
        self.sent = []

    async def send(self, text, attachments):
        self.sent.append((text, attachments))
        return "probe-mid"


class FakeController:
    def __init__(self, state):
        self.state = state
        self.publisher = SimpleNamespace(max_client=FakeMaxClient())
        self.published = []
        self.scans = []
        self.period_scans = []
        self.source_categories = []

    async def publish_item(self, item_id):
        self.published.append(item_id)
        self.state.complete(item_id, "published-mid")
        return self.state.queue_item(item_id)

    async def add_source(self, source, category="content"):
        if source == "bad-source":
            raise ValueError("private source denied")
        self.state.add_source(source, source.title(), category)
        self.source_categories.append((source, category))
        return source, True

    async def set_source_category(self, source, category):
        self.source_categories.append((source, category))
        return self.state.set_source_category(source, category)

    async def remove_source(self, source):
        return self.state.remove_source(source)

    async def parse_latest(self, count, source=None, *, required_kind="any"):
        self.scans.append((count, source, required_kind))
        return 4

    async def parse_from(
        self,
        start,
        count,
        source=None,
        end=None,
        required_kind="any",
    ):
        self.period_scans.append((start, end, count, source, required_kind))
        return 3


class DashboardActionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.state = MigrationState(Path(self.directory.name) / "state.sqlite3")
        self.controller = FakeController(self.state)
        self.runner = DashboardActionRunner(self.state, self.controller)

    async def asyncTearDown(self):
        self.state.close()
        self.directory.cleanup()

    def queue_item(self, message_id=1):
        return self.state.enqueue(
            "source",
            f"message:{message_id}",
            (message_id,),
            "image",
            10,
            datetime.now(timezone.utc),
        )

    async def test_publish_now_uses_exact_item_and_completes_once(self):
        item = self.queue_item()
        action = self.state.enqueue_action(
            "publish_now", {"item_id": item.id}, queue_item_id=item.id
        )

        self.assertTrue(await self.runner.run_once())
        self.assertEqual(self.controller.published, [item.id])
        self.assertEqual(self.state.action(action.id).status, "completed")
        self.assertEqual(
            self.state.action(action.id).result,
            {"item_id": item.id, "max_mid": "published-mid"},
        )
        self.assertFalse(await DashboardActionRunner(self.state, self.controller).run_once())
        self.assertEqual(self.controller.published, [item.id])

    async def test_source_scan_retry_remove_and_probe_actions(self):
        item = self.queue_item()
        self.state.claim_item(item.id)
        self.state.mark_error(item.id, "failed", "temporary")
        actions = [
            self.state.enqueue_action("add_source", {"source": "new-source"}),
            self.state.enqueue_action(
                "scan", {"count": 12, "source": "new-source", "kind": "video"}
            ),
            self.state.enqueue_action("retry", {"item_id": item.id}),
            self.state.enqueue_action("max_probe", {}),
            self.state.enqueue_action("remove_source", {"source": "new-source"}),
        ]

        for _ in actions:
            self.assertTrue(await self.runner.run_once())

        self.assertEqual(self.controller.scans, [(12, "new-source", "video")])
        self.assertEqual(self.state.queue_item(item.id).status, "pending")
        self.assertEqual(self.controller.publisher.max_client.sent[0][0], "Проверка связи Desiree")
        self.assertEqual(self.state.sources(), [])
        self.assertTrue(all(self.state.action(action.id).status == "completed" for action in actions))

    async def test_invalid_payload_and_source_failure_are_recorded_safely(self):
        self.state.enqueue_action("scan", {"count": -5})
        self.state.add_source("bad-source", "Bad")
        failed_source = self.state.enqueue_action(
            "add_source", {"source": "bad-source"}
        )

        self.assertTrue(await self.runner.run_once())
        self.assertTrue(await self.runner.run_once())

        actions = self.state.recent_actions()
        self.assertTrue(all(action.status == "failed" for action in actions))
        self.assertLessEqual(max(len(action.error or "") for action in actions), 1000)
        source = next(source for source in self.state.sources() if source.peer == "bad-source")
        self.assertEqual(source.availability, "unavailable")
        self.assertIn("denied", source.error)

    async def test_period_scan_passes_dates_and_media_kind(self):
        action = self.state.enqueue_action(
            "scan",
            {
                "count": 20,
                "source": "anime",
                "kind": "image",
                "start": "2026-08-01",
                "end": "2026-08-05",
            },
        )

        self.assertTrue(await self.runner.run_once())

        self.assertEqual(self.state.action(action.id).result, {"added": 3})
        start, end, count, source, kind = self.controller.period_scans[0]
        self.assertEqual(start.astimezone(MOSCOW).date().isoformat(), "2026-08-01")
        self.assertEqual(end.astimezone(MOSCOW).date().isoformat(), "2026-08-06")
        self.assertEqual((count, source, kind), (20, "anime", "image"))

    async def test_source_actions_preserve_news_category(self):
        add = self.state.enqueue_action(
            "add_source",
            {"source": "anime-news", "category": "news"},
        )
        change = self.state.enqueue_action(
            "set_source_category",
            {"source": "anime-news", "category": "content"},
        )

        self.assertTrue(await self.runner.run_once())
        self.assertTrue(await self.runner.run_once())

        self.assertEqual(
            self.controller.source_categories,
            [("anime-news", "news"), ("anime-news", "content")],
        )
        self.assertEqual(self.state.sources()[0].category, "content")
        self.assertEqual(self.state.action(add.id).result["category"], "news")
        self.assertEqual(self.state.action(change.id).result["category"], "content")


if __name__ == "__main__":
    unittest.main()
