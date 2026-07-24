import tempfile
import unittest
from pathlib import Path

from tg_migrator.state import MigrationState


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


if __name__ == "__main__":
    unittest.main()

