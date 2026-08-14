import os
import unittest
from unittest.mock import patch

from tg_migrator.config import load_automation_config


class AutomationConfigTests(unittest.TestCase):
    def test_safe_defaults_keep_new_runtime_disabled(self):
        with patch.dict(os.environ, {}, clear=True):
            config = load_automation_config()

        self.assertFalse(config.enabled)
        self.assertEqual(config.owner_ids, frozenset({8235497168}))
        self.assertEqual(config.destination, "webnmy")
        self.assertEqual(config.initial_source, "animeworldmem")
        self.assertEqual(config.max_channel, "-77809668353385")
        self.assertEqual(config.signature_text, "НАШ ТГК")
        self.assertEqual(config.signature_url, "https://t.me/webm4ik")
        self.assertEqual(config.queue_minimum, 18)
        self.assertEqual(config.target_scan_limit, 1000)

    def test_environment_overrides_runtime_controls(self):
        values = {
            "TG_AUTOMATION_ENABLED": "yes",
            "TG_OWNER_IDS": "11, 22,11",
            "TG_DESTINATION": "@stage",
            "TG_INITIAL_SOURCE": "https://t.me/source",
            "MAX_BOT_TOKEN": " max-secret ",
            "MAX_CHANNEL": "https://max.ru/custom-channel",
            "TG_QUEUE_MINIMUM": "9",
            "TG_REFILL_INTERVAL": "600",
        }
        with patch.dict(os.environ, values, clear=True):
            config = load_automation_config()

        self.assertTrue(config.enabled)
        self.assertEqual(config.owner_ids, frozenset({11, 22}))
        self.assertEqual(config.destination, "stage")
        self.assertEqual(config.initial_source, "source")
        self.assertEqual(config.max_token, "max-secret")
        self.assertEqual(config.max_channel, "custom-channel")
        self.assertEqual(config.queue_minimum, 9)
        self.assertEqual(config.refill_interval, 600)


if __name__ == "__main__":
    unittest.main()
