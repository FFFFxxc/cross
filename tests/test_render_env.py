import subprocess
import unittest
from dataclasses import replace
from unittest.mock import patch

from tg_migrator.config import ConfigError
from tg_migrator.render_env import (
    RenderEnvValues,
    build_render_env,
    copy_to_clipboard,
)


def values(**overrides):
    base = RenderEnvValues(
        api_id="12345",
        api_hash="api-hash",
        phone="+1 555 123 4567",
        session="session-value",
        database_url="postgresql://owner:password@host/db?sslmode=require",
        max_token="max token #1",
    )
    return replace(base, **overrides)


class RenderEnvTests(unittest.TestCase):
    def test_builds_complete_disabled_render_block_with_quoted_secrets(self):
        block = build_render_env(values())

        self.assertEqual(
            block,
            """TG_API_ID=\"12345\"
TG_API_HASH=\"api-hash\"
TG_PHONE=\"+1 555 123 4567\"
TG_SESSION_STRING=\"session-value\"
TG_AUTOMATION_ENABLED=\"false\"
TG_OWNER_IDS=\"8235497168\"
TG_DESTINATION=\"webnmy\"
TG_INITIAL_SOURCE=\"animeworldmem\"
DATABASE_URL=\"postgresql://owner:password@host/db?sslmode=require\"
MAX_BOT_TOKEN=\"max token #1\"
MAX_CHANNEL=\"channel_animenaruto\"
MAX_API_BASE=\"https://platform-api2.max.ru\"
MAX_SIGNATURE_TEXT=\"НАШ ТГК\"
MAX_SIGNATURE_URL=\"https://t.me/webm4ik\"
TG_QUEUE_MINIMUM=\"18\"
TG_REFILL_INTERVAL=\"900\"
TG_SCAN_LIMIT=\"120\"
TG_FRESH_DAYS=\"30\"
TG_TARGET_SCAN_LIMIT=\"1000\"
PORT=\"10000\"
""",
        )

    def test_rejects_empty_required_secret_without_echoing_other_values(self):
        with self.assertRaisesRegex(ConfigError, "DATABASE_URL") as raised:
            build_render_env(values(database_url=""))

        self.assertNotIn("api-hash", str(raised.exception))
        self.assertNotIn("session-value", str(raised.exception))

    @patch("tg_migrator.render_env.subprocess.run")
    def test_copies_block_to_pbcopy_without_returning_it(self, run):
        block = "TG_SESSION_STRING=secret\n"

        result = copy_to_clipboard(block)

        self.assertIsNone(result)
        run.assert_called_once_with(
            ["pbcopy"],
            input=block,
            text=True,
            check=True,
            capture_output=True,
        )

    @patch(
        "tg_migrator.render_env.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, ["pbcopy"]),
    )
    def test_clipboard_failure_is_safe_config_error(self, _run):
        with self.assertRaisesRegex(ConfigError, "буфер обмена") as raised:
            copy_to_clipboard("TG_SESSION_STRING=secret\n")

        self.assertNotIn("secret", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
