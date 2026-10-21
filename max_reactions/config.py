from __future__ import annotations

import sqlite3
import tomllib
from dataclasses import dataclass
from pathlib import Path


CHANNEL_URL = "https://max.ru/channel_animenaruto"


@dataclass(frozen=True)
class Settings:
    channel_url: str = CHANNEL_URL
    emoji: str = "👍"
    poll_seconds: int = 30
    history_limit: int = 20
    max_age_seconds: int = 900
    max_per_poll: int = 1
    request_timeout_seconds: int = 30
    auth_timeout_seconds: int = 180

    @classmethod
    def load(cls, path: Path) -> Settings:
        with path.open("rb") as stream:
            settings = cls(**tomllib.load(stream))
        if settings.channel_url != CHANNEL_URL:
            raise ValueError("Only channel_animenaruto is configured for this service")
        if not isinstance(settings.emoji, str) or not 1 <= len(settings.emoji) <= 16:
            raise ValueError("Invalid reaction")
        for name, minimum, maximum in (
            ("poll_seconds", 15, 3600), ("history_limit", 1, 100),
            ("max_age_seconds", 60, 3600), ("max_per_poll", 1, 5),
            ("request_timeout_seconds", 5, 120), ("auth_timeout_seconds", 30, 600),
        ):
            value = getattr(settings, name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"Invalid {name}")
        return settings


def session_ready(data_dir: Path) -> bool:
    path = data_dir / "max-session.db"
    if not path.is_file():
        return False
    try:
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)
        try:
            return bool(connection.execute(
                "SELECT EXISTS(SELECT 1 FROM sessions WHERE length(token) > 0)"
            ).fetchone()[0])
        finally:
            connection.close()
    except sqlite3.Error:
        return False
