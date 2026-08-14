import unittest
from unittest.mock import patch

from tg_migrator.config import Credentials
from tg_migrator.telegram import build_client


class TelegramClientTests(unittest.TestCase):
    @patch("tg_migrator.telegram.TelegramClient")
    def test_build_client_leaves_reconnect_to_application_supervisor(self, client):
        build_client(
            Credentials(12345, "api-hash", "+1 555 123 4567"),
            fresh_string_session=True,
        )

        self.assertFalse(client.call_args.kwargs["auto_reconnect"])


if __name__ == "__main__":
    unittest.main()
