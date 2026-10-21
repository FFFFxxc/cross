from __future__ import annotations

import argparse
import asyncio
import contextlib
import getpass
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

from .config import Settings, session_ready
from .worker import ReactionState, ReactionWorker, bind_scoped_history, event


class AuthRequired(RuntimeError):
    pass


class QRFile:
    def __init__(self, path: Path, allowed: bool):
        self.path = path
        self.allowed = allowed

    async def show_qr(self, qr_url: str) -> None:
        if not self.allowed:
            raise AuthRequired("AUTH_REQUIRED: run the separate auth command")
        import qrcode
        image = qrcode.make(qr_url)
        image.save(self.path)
        self.path.chmod(0o600)
        if sys.stdin.isatty():
            code = qrcode.QRCode()
            code.add_data(qr_url)
            code.print_ascii()
        event("qr_ready", expires_within_seconds=180)


class TerminalPassword:
    async def get_password(self, hint: str | None) -> str:
        if not sys.stdin.isatty():
            raise AuthRequired("2FA_REQUIRES_INTERACTIVE_TERMINAL")
        return await asyncio.to_thread(getpass.getpass, "MAX 2FA (terminal only): ")


@contextlib.contextmanager
def service_lock(path: Path):
    with path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            stream.seek(0)
            if not stream.read(1):
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def read_target(data_dir: Path, settings: Settings) -> dict:
    target = json.loads((data_dir / "target.json").read_text(encoding="utf-8"))
    if (
        target.get("channel_url") != settings.channel_url
        or type(target.get("chat_id")) is not int or target["chat_id"] == 0
        or type(target.get("account_id")) is not int or target["account_id"] <= 0
    ):
        raise AuthRequired("TARGET_BINDING_INVALID")
    return target


async def connected_job(command: str, settings: Settings, data_dir: Path, dry_run: bool) -> None:
    from pymax import WebClient
    from pymax.auth.qr import QrAuthFlow
    from pymax.config import ExtraConfig

    auth = command == "auth"
    qr_path = data_dir / "connect.png"
    flow = QrAuthFlow(QRFile(qr_path, auth), password_provider=TerminalPassword())
    client = WebClient(
        work_dir=str(data_dir), session_name="max-session.db", auth_flow=flow,
        extra_config=ExtraConfig(relogin=False, reconnect=False, log_level="CRITICAL"),
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    state = None
    try:
        await asyncio.wait_for(
            client.connect(),
            timeout=settings.auth_timeout_seconds if auth else settings.request_timeout_seconds,
        )
        me = client.me
        account_id = getattr(getattr(me, "contact", None), "id", None)
        if type(account_id) is not int or account_id <= 0:
            raise AuthRequired("ACCOUNT_ID_MISSING")
        if auth:
            # Only this explicitly requested channel may be joined.
            chat = await asyncio.wait_for(
                client.join_channel(settings.channel_url), settings.request_timeout_seconds,
            )
            if chat is None or type(chat.id) is not int or chat.id == 0:
                raise AuthRequired("CHANNEL_NOT_RESOLVED")
            await asyncio.wait_for(
                client.fetch_history(chat.id, backward=1), settings.request_timeout_seconds,
            )
            write_json(data_dir / "target.json", {
                "account_id": account_id, "chat_id": chat.id,
                "channel_url": settings.channel_url,
            })
            event("auth_complete", account_id=account_id, chat_id=chat.id)
            return

        target = read_target(data_dir, settings)
        if target["account_id"] != account_id:
            raise AuthRequired("ACCOUNT_BINDING_MISMATCH")
        state = ReactionState(data_dir / "reactions.sqlite3")
        worker = ReactionWorker(
            client, state, channel_id=target["chat_id"], emoji=settings.emoji,
            started_at_ms=int(time.time() * 1000),
            max_age_ms=settings.max_age_seconds * 1000,
            max_per_poll=settings.max_per_poll, dry_run=dry_run,
        )
        event("worker_ready", chat_id=target["chat_id"], dry_run=dry_run)
        first_poll = True
        while not stop.is_set():
            if not client.is_connected:
                raise ConnectionError("MAX_CONNECTION_CLOSED")
            messages = await asyncio.wait_for(
                client.fetch_history(target["chat_id"], backward=settings.history_limit),
                settings.request_timeout_seconds,
            )
            messages = bind_scoped_history(messages, target["chat_id"])
            if first_poll:
                event(
                    "history_ready", chat_id=target["chat_id"],
                    message_count=len(messages),
                    bound_to_target=sum(m.chat_id == target["chat_id"] for m in messages),
                )
                first_poll = False
            await asyncio.wait_for(
                worker.tick(messages, now_ms=int(time.time() * 1000)),
                settings.request_timeout_seconds,
            )
            write_json(data_dir / "heartbeat.json", {"time": time.time()})
            try:
                await asyncio.wait_for(stop.wait(), settings.poll_seconds)
            except TimeoutError:
                pass
    finally:
        qr_path.unlink(missing_ok=True)
        if state is not None:
            state.close()
        await client.close()


def main() -> int:
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("auth", "run", "status", "health"))
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("settings.toml"))
    parser.add_argument("--data-dir", type=Path, default=Path("/data"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        settings = Settings.load(args.config)
        data_dir = args.data_dir.resolve()
        if args.command in {"status", "health", "run"}:
            if not session_ready(data_dir):
                event("auth_required")
                return 2
            read_target(data_dir, settings)
        if args.command == "status":
            event("session_ready")
            return 0
        if args.command == "health":
            heartbeat = json.loads((data_dir / "heartbeat.json").read_text(encoding="utf-8"))
            return 0 if 0 <= time.time() - heartbeat["time"] < 180 else 1
        data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        with service_lock(data_dir / "service.lock"):
            asyncio.run(connected_job(args.command, settings, data_dir, args.dry_run))
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        event("service_failed", error_type=type(error).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
