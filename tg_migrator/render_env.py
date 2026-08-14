from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

from .config import ConfigError


@dataclass(frozen=True)
class RenderEnvValues:
    api_id: str
    api_hash: str
    phone: str
    session: str
    database_url: str
    max_token: str


def build_render_env(values: RenderEnvValues) -> str:
    required = {
        "TG_API_ID": values.api_id,
        "TG_API_HASH": values.api_hash,
        "TG_PHONE": values.phone,
        "TG_SESSION_STRING": values.session,
        "DATABASE_URL": values.database_url,
        "MAX_BOT_TOKEN": values.max_token,
    }
    for key, value in required.items():
        if not str(value).strip():
            raise ConfigError(f"Обязательное значение {key} пусто.")

    items = (
        ("TG_API_ID", values.api_id),
        ("TG_API_HASH", values.api_hash),
        ("TG_PHONE", values.phone),
        ("TG_SESSION_STRING", values.session),
        ("TG_AUTOMATION_ENABLED", "false"),
        ("TG_OWNER_IDS", "8235497168"),
        ("TG_DESTINATION", "webnmy"),
        ("TG_INITIAL_SOURCE", "animeworldmem"),
        ("DATABASE_URL", values.database_url),
        ("MAX_BOT_TOKEN", values.max_token),
        ("MAX_CHANNEL", "channel_animenaruto"),
        ("MAX_API_BASE", "https://platform-api2.max.ru"),
        ("MAX_SIGNATURE_TEXT", "НАШ ТГК"),
        ("MAX_SIGNATURE_URL", "https://t.me/webm4ik"),
        ("TG_QUEUE_MINIMUM", "18"),
        ("TG_REFILL_INTERVAL", "900"),
        ("TG_SCAN_LIMIT", "120"),
        ("TG_FRESH_DAYS", "30"),
        ("TG_TARGET_SCAN_LIMIT", "1000"),
        ("PORT", "10000"),
    )
    return "".join(
        f"{key}={json.dumps(str(value), ensure_ascii=False)}\n"
        for key, value in items
    )


def copy_to_clipboard(block: str) -> None:
    try:
        subprocess.run(
            ["pbcopy"],
            input=block,
            text=True,
            check=True,
            capture_output=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise ConfigError("Не удалось скопировать env в буфер обмена.") from exc
