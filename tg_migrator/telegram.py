from __future__ import annotations

import getpass
from pathlib import Path

from telethon import TelegramClient

from .config import Credentials, SESSION_FILE


def build_client(credentials: Credentials) -> TelegramClient:
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    return TelegramClient(
        str(SESSION_FILE),
        credentials.api_id,
        credentials.api_hash,
        flood_sleep_threshold=120,
    )


async def authorize(client: TelegramClient, credentials: Credentials) -> None:
    await client.connect()
    if not await client.is_user_authorized():
        await client.start(
            phone=credentials.phone,
            code_callback=lambda: getpass.getpass(
                "Код подтверждения из Telegram: "
            ),
            password=lambda: getpass.getpass("Пароль двухэтапной защиты: "),
        )
    session_path = Path(str(SESSION_FILE) + ".session")
    if session_path.exists():
        session_path.chmod(0o600)

