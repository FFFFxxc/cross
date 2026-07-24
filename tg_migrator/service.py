from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path

from .config import DATA_DIR, PROJECT_DIR


LABEL = "com.codex.telegram-post-migrator"
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
PLIST_PATH = LAUNCH_AGENTS / f"{LABEL}.plist"


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _target() -> str:
    return f"{_domain()}/{LABEL}"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=False, capture_output=True, text=True)


def install_service() -> None:
    if os.uname().sysname != "Darwin":
        raise RuntimeError("Автозапуск этим способом поддерживается только в macOS.")
    python = PROJECT_DIR / ".venv" / "bin" / "python"
    if not python.exists():
        raise RuntimeError("Сначала установите зависимости в папку .venv.")
    LAUNCH_AGENTS.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.chmod(0o700)
    plist = {
        "Label": LABEL,
        "ProgramArguments": [
            "/usr/bin/env",
            "-i",
            f"PATH=/usr/bin:/bin:/usr/sbin:/sbin",
            f"HOME={Path.home()}",
            "PYTHONUNBUFFERED=1",
            str(python),
            "-m",
            "tg_migrator",
            "watch",
        ],
        "WorkingDirectory": str(PROJECT_DIR),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Interactive",
        "StandardOutPath": str(DATA_DIR / "launchd.log"),
        "StandardErrorPath": str(DATA_DIR / "launchd.error.log"),
    }
    PLIST_PATH.write_bytes(plistlib.dumps(plist))
    PLIST_PATH.chmod(0o600)

    _run("launchctl", "bootout", _target())
    loaded = _run("launchctl", "bootstrap", _domain(), str(PLIST_PATH))
    if loaded.returncode != 0:
        raise RuntimeError(
            "Не удалось зарегистрировать автозапуск: "
            + (loaded.stderr.strip() or loaded.stdout.strip())
        )
    enabled = _run("launchctl", "enable", _target())
    if enabled.returncode != 0:
        raise RuntimeError(
            "Автозапуск зарегистрирован, но не включён: "
            + (enabled.stderr.strip() or enabled.stdout.strip())
        )
    _run("launchctl", "kickstart", "-k", _target())


def uninstall_service() -> None:
    if os.uname().sysname == "Darwin":
        _run("launchctl", "bootout", _target())
    PLIST_PATH.unlink(missing_ok=True)


def service_status() -> str:
    if not PLIST_PATH.exists():
        return "Автозапуск не установлен."
    result = _run("launchctl", "print", _target())
    if result.returncode == 0:
        return "Автозапуск установлен и работает."
    return "Автозапуск установлен, но процесс сейчас не запущен."
