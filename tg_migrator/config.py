from __future__ import annotations

import getpass
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("TG_DATA_DIR") or PROJECT_DIR / ".data").expanduser()
TARGETS_FILE = DATA_DIR / "targets.json"
SESSION_FILE = DATA_DIR / "telegram"
STATE_FILE = DATA_DIR / "state.sqlite3"
KEYCHAIN_SERVICE = "telegram-post-migrator"


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Credentials:
    api_id: int
    api_hash: str
    phone: str


@dataclass(frozen=True)
class Targets:
    source: int | str
    destination: int | str


@dataclass(frozen=True)
class AutomationConfig:
    enabled: bool
    owner_ids: frozenset[int]
    destination: int | str
    initial_source: int | str
    database_url: str | None
    max_token: str | None
    max_channel: str
    max_api_base: str
    signature_text: str
    signature_url: str
    queue_minimum: int
    refill_interval: int
    scan_limit: int
    fresh_days: int
    target_scan_limit: int


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.chmod(0o700)


def normalize_peer(value: Any) -> int | str:
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        raise ConfigError("Пустой идентификатор Telegram-чата.")
    for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
            break
    text = text.split("?", 1)[0].strip("/").lstrip("@")
    if text.lstrip("-").isdigit():
        return int(text)
    if not text:
        raise ConfigError("Не удалось распознать ссылку Telegram.")
    return text


def _enabled(value: str | None, default: bool = False) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _positive_int(value: str | None, default: int) -> int:
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigError(f"Ожидалось целое число, получено: {value!r}.") from exc
    if parsed <= 0:
        raise ConfigError("Числовая настройка должна быть больше нуля.")
    return parsed


def _owner_ids(value: str | None) -> frozenset[int]:
    raw = value if value and value.strip() else "8235497168"
    try:
        return frozenset(int(item.strip()) for item in raw.split(",") if item.strip())
    except ValueError as exc:
        raise ConfigError("TG_OWNER_IDS должен содержать Telegram ID через запятую.") from exc


def _max_channel(value: str | None) -> str:
    channel = (value or "-77809668353385").strip()
    for prefix in ("https://max.ru/", "http://max.ru/", "max.ru/"):
        if channel.lower().startswith(prefix):
            channel = channel[len(prefix) :]
            break
    channel = channel.split("?", 1)[0].strip("/").lstrip("@")
    if not channel:
        raise ConfigError("MAX_CHANNEL не может быть пустым.")
    return channel


def load_automation_config() -> AutomationConfig:
    database_url = (os.getenv("DATABASE_URL") or "").strip() or None
    max_token = (os.getenv("MAX_BOT_TOKEN") or "").strip() or None
    api_base = (os.getenv("MAX_API_BASE") or "https://platform-api2.max.ru").strip()
    return AutomationConfig(
        enabled=_enabled(os.getenv("TG_AUTOMATION_ENABLED")),
        owner_ids=_owner_ids(os.getenv("TG_OWNER_IDS")),
        destination=normalize_peer(os.getenv("TG_DESTINATION") or "webnmy"),
        initial_source=normalize_peer(
            os.getenv("TG_INITIAL_SOURCE") or "animeworldmem"
        ),
        database_url=database_url,
        max_token=max_token,
        max_channel=_max_channel(os.getenv("MAX_CHANNEL")),
        max_api_base=api_base.rstrip("/"),
        signature_text=(os.getenv("MAX_SIGNATURE_TEXT") or "НАШ ТГК").strip(),
        signature_url=(
            os.getenv("MAX_SIGNATURE_URL") or "https://t.me/webm4ik"
        ).strip(),
        queue_minimum=_positive_int(os.getenv("TG_QUEUE_MINIMUM"), 18),
        refill_interval=_positive_int(os.getenv("TG_REFILL_INTERVAL"), 900),
        scan_limit=_positive_int(os.getenv("TG_SCAN_LIMIT"), 120),
        fresh_days=_positive_int(os.getenv("TG_FRESH_DAYS"), 7),
        target_scan_limit=_positive_int(os.getenv("TG_TARGET_SCAN_LIMIT"), 1000),
    )


def save_targets(source: str | int, destination: str | int) -> Targets:
    targets = Targets(normalize_peer(source), normalize_peer(destination))
    _ensure_data_dir()
    TARGETS_FILE.write_text(
        json.dumps(
            {"source": targets.source, "destination": targets.destination},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    TARGETS_FILE.chmod(0o600)
    return targets


def load_targets(
    source_override: str | int | None = None,
    destination_override: str | int | None = None,
) -> Targets:
    stored: dict[str, Any] = {}
    if TARGETS_FILE.exists():
        stored = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))

    source = source_override or os.getenv("TG_SOURCE") or stored.get("source")
    destination = (
        destination_override
        or os.getenv("TG_DESTINATION")
        or stored.get("destination")
    )
    if source is None or destination is None:
        raise ConfigError(
            "Сначала задайте чаты: tg-migrator configure-targets "
            "--source <источник> --destination <назначение>"
        )
    return Targets(normalize_peer(source), normalize_peer(destination))


def load_session_string() -> str | None:
    """Строка сессии Telethon (StringSession) из окружения.

    Используется на серверах без постоянного диска (например,
    Hugging Face Spaces): секрет TG_SESSION_STRING заменяет файловую
    сессию в .data/.
    """
    value = os.getenv("TG_SESSION_STRING")
    if value is None:
        return None
    value = value.strip()
    return value or None


def _keychain_get(account: str) -> str | None:
    if os.uname().sysname != "Darwin":
        return None
    result = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-s",
            KEYCHAIN_SERVICE,
            "-a",
            account,
            "-w",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.rstrip("\n")


def _keychain_set(account: str, value: str) -> None:
    if os.uname().sysname != "Darwin":
        raise ConfigError(
            "Автосохранение секретов поддерживается только в macOS Keychain. "
            "Используйте TG_API_ID, TG_API_HASH и TG_PHONE."
        )
    result = subprocess.run(
        [
            "security",
            "add-generic-password",
            "-U",
            "-s",
            KEYCHAIN_SERVICE,
            "-a",
            account,
            "-w",
        ],
        input=value + "\n",
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ConfigError(
            "Не удалось сохранить секрет в macOS Keychain: "
            + result.stderr.strip()
        )


def configure_credentials() -> Credentials:
    api_id_text = getpass.getpass("Telegram api_id: ").strip()
    api_hash = getpass.getpass("Telegram api_hash: ").strip()
    phone = getpass.getpass("Номер телефона в международном формате: ").strip()
    try:
        api_id = int(api_id_text)
    except ValueError as exc:
        raise ConfigError("api_id должен состоять из цифр.") from exc
    if not api_hash or not phone:
        raise ConfigError("api_hash и номер телефона обязательны.")
    _keychain_set("api_id", str(api_id))
    _keychain_set("api_hash", api_hash)
    _keychain_set("phone", phone)
    return Credentials(api_id, api_hash, phone)


def load_credentials() -> Credentials:
    api_id_text = os.getenv("TG_API_ID") or _keychain_get("api_id")
    api_hash = os.getenv("TG_API_HASH") or _keychain_get("api_hash")
    phone = os.getenv("TG_PHONE") or _keychain_get("phone")
    if not api_id_text or not api_hash or not phone:
        raise ConfigError(
            "Telegram-доступ не настроен. Запустите "
            "tg-migrator configure-secrets."
        )
    try:
        api_id = int(api_id_text)
    except ValueError as exc:
        raise ConfigError("Сохранённый api_id имеет неверный формат.") from exc
    return Credentials(api_id, api_hash, phone)
