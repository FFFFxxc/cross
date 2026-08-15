import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from telethon.errors.common import InvalidBufferError

from tg_migrator.config import AutomationConfig, Targets
from tg_migrator.watch import maintain_connection, run_watcher


class StopSignal(Exception):
    pass


class FakeClient:
    def __init__(self):
        self.run_calls = 0
        self.connect_calls = 0
        self.disconnect_calls = 0

    async def run_until_disconnected(self):
        self.run_calls += 1
        if self.run_calls == 1:
            raise InvalidBufferError(b"HTTP code 429")
        raise StopSignal()

    async def disconnect(self):
        self.disconnect_calls += 1

    async def connect(self):
        self.connect_calls += 1


class IncompleteReadClient(FakeClient):
    async def run_until_disconnected(self):
        self.run_calls += 1
        if self.run_calls == 1:
            raise asyncio.IncompleteReadError(b"", 8)
        raise StopSignal()


class ConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_transient_telegram_disconnect_reconnects_before_retrying(self):
        client = FakeClient()

        async def no_wait(_seconds):
            return None

        with self.assertRaises(StopSignal):
            await maintain_connection(client, sleep=no_wait)

        self.assertEqual(client.run_calls, 2)
        self.assertEqual(client.disconnect_calls, 1)
        self.assertEqual(client.connect_calls, 1)

    async def test_incomplete_telegram_read_reconnects_before_retrying(self):
        client = IncompleteReadClient()

        async def no_wait(_seconds):
            return None

        with self.assertRaises(StopSignal):
            await maintain_connection(client, sleep=no_wait)

        self.assertEqual(client.run_calls, 2)
        self.assertEqual(client.disconnect_calls, 1)
        self.assertEqual(client.connect_calls, 1)

    def automation_config(self, enabled):
        return AutomationConfig(
            enabled=enabled,
            owner_ids=frozenset({8235497168}),
            destination="webnmy",
            initial_source="animeworldmem",
            database_url=None,
            max_token="token",
            max_channel="channel_animenaruto",
            max_api_base="https://platform-api2.max.ru",
            signature_text="НАШ ТГК",
            signature_url="https://t.me/webm4ik",
            queue_minimum=18,
            refill_interval=900,
            scan_limit=120,
            fresh_days=30,
            target_scan_limit=1000,
        )

    async def test_disabled_config_preserves_legacy_watcher(self):
        legacy = AsyncMock()
        automation = AsyncMock()
        with (
            patch("tg_migrator.watch._run_legacy_watcher", legacy),
            patch("tg_migrator.watch._run_automation_watcher", automation),
        ):
            await run_watcher(
                object(),
                Targets("old-source", "webnmy"),
                self.automation_config(False),
            )
        legacy.assert_awaited_once()
        automation.assert_not_awaited()

    async def test_enabled_config_uses_automation_watcher(self):
        legacy = AsyncMock()
        automation = AsyncMock()
        with (
            patch("tg_migrator.watch._run_legacy_watcher", legacy),
            patch("tg_migrator.watch._run_automation_watcher", automation),
        ):
            await run_watcher(
                object(),
                Targets("old-source", "webnmy"),
                self.automation_config(True),
            )
        automation.assert_awaited_once()
        legacy.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
