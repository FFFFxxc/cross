from __future__ import annotations

import getpass
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / ".data"
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

