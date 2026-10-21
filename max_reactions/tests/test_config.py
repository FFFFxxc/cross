import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from max_reactions.__main__ import AuthRequired, QRFile, read_target, service_lock
from max_reactions.config import CHANNEL_URL, Settings, session_ready


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def load(self, text):
        path = self.root / "settings.toml"
        path.write_text(text, encoding="utf-8")
        return Settings.load(path)

    def test_defaults_are_single_channel_and_one_reaction_per_poll(self):
        settings = self.load("")
        self.assertEqual(settings.channel_url, CHANNEL_URL)
        self.assertEqual(settings.max_per_poll, 1)
        self.assertEqual(settings.emoji, "👍")

    def test_other_channel_and_bad_numeric_settings_are_rejected(self):
        for content in (
            'channel_url="https://max.ru/other"', 'poll_seconds=0',
            'max_per_poll=100', 'max_per_poll=true', 'unknown=1', 'emoji=""',
        ):
            with self.subTest(content=content), self.assertRaises((ValueError, TypeError)):
                self.load(content)

    def test_missing_session_probe_does_not_create_files(self):
        self.assertFalse(session_ready(self.root))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_session_readiness_reads_only_its_own_file(self):
        path = self.root / "max-session.db"
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE sessions(token TEXT)")
            db.execute("INSERT INTO sessions VALUES ('')")
        db.close()
        self.assertFalse(session_ready(self.root))
        with sqlite3.connect(path) as db:
            db.execute("UPDATE sessions SET token='test-token'")
        db.close()
        before = path.read_bytes()
        self.assertTrue(session_ready(self.root))
        self.assertEqual(before, path.read_bytes())

    def test_invalid_session_is_not_authenticated(self):
        (self.root / "max-session.db").write_bytes(b"not sqlite")
        self.assertFalse(session_ready(self.root))

    def test_target_is_bound_to_configured_channel_and_account(self):
        path = self.root / "target.json"
        valid = {"channel_url": CHANNEL_URL, "chat_id": -42, "account_id": 123}
        path.write_text(json.dumps(valid), encoding="utf-8")
        self.assertEqual(read_target(self.root, Settings()), valid)
        for field, value in (("channel_url", "other"), ("chat_id", 0), ("account_id", True)):
            path.write_text(json.dumps({**valid, field: value}), encoding="utf-8")
            with self.subTest(field=field), self.assertRaises(AuthRequired):
                read_target(self.root, Settings())

    def test_qr_is_forbidden_in_background_worker(self):
        path = self.root / "connect.png"
        with self.assertRaises(AuthRequired):
            asyncio.run(QRFile(path, False).show_qr("https://example.test/qr"))
        self.assertFalse(path.exists())

    def test_auth_qr_provider_creates_real_png(self):
        path = self.root / "connect.png"
        with patch("sys.stdin.isatty", return_value=False):
            asyncio.run(QRFile(path, True).show_qr("https://example.test/qr"))
        self.assertTrue(path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))

    def test_session_lock_prevents_two_workers(self):
        path = self.root / "service.lock"
        with service_lock(path), self.assertRaises(OSError), service_lock(path):
            self.fail("Second process must not share the session")
        with service_lock(path):
            pass
