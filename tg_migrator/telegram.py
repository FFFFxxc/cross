from __future__ import annotations

import getpass
import sys
from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession

from .config import ConfigError, Credentials, SESSION_FILE, load_session_string

_ENV_SESSION_FLAG = "_tg_migrator_env_session"


def build_client(
    credentials: Credentials,
    *,
    fresh_string_session: bool = False,
) -> TelegramClient:
    from_env = False
    if fresh_string_session:
        session: StringSession | str = StringSession()
    else:
        session_string = load_session_string()
        if session_string is not None:
            try:
                session = StringSession(session_string)
            except Exception as exc:
                raise ConfigError(
                    "TG_SESSION_STRING имеет неверный формат. Сгенерируйте "
                    "строку заново: tg-migrator export-session"
                ) from exc
            from_env = True
        else:
            SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
            session = str(SESSION_FILE)
    client = TelegramClient(
        session,
        credentials.api_id,
        credentials.api_hash,
        flood_sleep_threshold=120,
        # Telethon's internal reconnect can remain stuck after a transport
        # disconnect. watch.maintain_connection owns the retry loop instead.
        auto_reconnect=False,
    )
    setattr(client, _ENV_SESSION_FLAG, from_env)
    return client


async def authorize(client: TelegramClient, credentials: Credentials) -> None:
    await client.connect()
    if not await client.is_user_authorized():
        if getattr(client, _ENV_SESSION_FLAG, False):
            raise ConfigError(
                "Строка сессии недействительна или отозвана Telegram. "
                "Сгенерируйте новую локально (tg-migrator export-session) "
                "и обновите секрет TG_SESSION_STRING."
            )
        if not sys.stdin.isatty():
            raise ConfigError(
                "Нужен интерактивный вход, а терминал недоступен. "
                "Авторизуйтесь локально (tg-migrator auth) и перенесите "
                ".data/ на сервер, либо задайте TG_SESSION_STRING "
                "(tg-migrator export-session)."
            )
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


def session_to_string(client: TelegramClient) -> str:
    """Представить текущую авторизованную сессию как StringSession."""
    return StringSession.save(client.session)
