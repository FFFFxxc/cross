import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from tg_migrator.migrator import migrate_posts
from tg_migrator.selection import Post
from tg_migrator.state import MigrationState


class FakeClient:
    def __init__(self, edit_error=None):
        self.forwarded = []
        self.edits = []
        self.edit_error = edit_error

    async def forward_messages(self, destination, ids, **kwargs):
        self.forwarded.append((destination, ids, kwargs))
        return [
            SimpleNamespace(id=100, raw_text="Мы в Максе: жирный", entities=[]),
        ]

    async def edit_message(self, destination, message, **kwargs):
        self.edits.append((destination, message, kwargs))
        if self.edit_error is not None:
            raise self.edit_error


class MigratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_copy_edits_forwarded_text_before_marking_state(self):
        source_message = SimpleNamespace(
            id=1,
            raw_text="Мы в Максе: жирный",
            message="Мы в Максе: жирный",
            entities=[],
            date=datetime(2025, 6, 1, tzinfo=timezone.utc),
        )
        post = Post("message:1", (source_message,))
        client = FakeClient()

        with tempfile.TemporaryDirectory() as directory:
            state = MigrationState(Path(directory) / "state.sqlite3")
            result = await migrate_posts(
                client,
                "source",
                "destination",
                [post],
                state,
            )
            self.assertEqual(result.transferred_posts, 1)
            self.assertEqual(client.edits[0][2]["text"], "жирный")
            self.assertEqual(
                state.transferred_ids("source", "destination", [1]),
                {1},
            )
            state.close()

    async def test_edit_failure_does_not_mark_post_transferred(self):
        source_message = SimpleNamespace(
            id=1,
            raw_text="Мы в Максе: текст",
            message="Мы в Максе: текст",
            entities=[],
            date=datetime(2025, 6, 1, tzinfo=timezone.utc),
        )
        post = Post("message:1", (source_message,))
        client = FakeClient(edit_error=RuntimeError("edit failed"))

        with tempfile.TemporaryDirectory() as directory:
            state = MigrationState(Path(directory) / "state.sqlite3")
            with self.assertRaises(RuntimeError):
                await migrate_posts(
                    client,
                    "source",
                    "destination",
                    [post],
                    state,
                )
            self.assertEqual(
                state.transferred_ids("source", "destination", [1]),
                set(),
            )
            state.close()


if __name__ == "__main__":
    unittest.main()
