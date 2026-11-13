"""Supervise the existing worker without sharing or reopening Telegram sessions."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime

POLL_SECONDS = 30
STALE_SECONDS = 300
STARTUP_SECONDS = 240
STOP_SECONDS = 20
MAX_BACKOFF_SECONDS = 300
MARKER = 'Runtime guard: interrupted delivery; reconcile receipts before retry'


def log(event, **fields):
    print(json.dumps(dict(event=event, **fields)), flush=True)


def stale_reason(values, *, now, started):
    if now - started < STARTUP_SECONDS:
        return None
    for key in ('worker_heartbeat_at', 'scheduler_heartbeat_at'):
        try:
            value = values[key]
            if not isinstance(value, str):
                return key
            stamp = datetime.fromisoformat(value).timestamp()
            if stamp < started or not -120 <= now - stamp <= STALE_SECONDS:
                return key
        except (KeyError, ValueError, TypeError, OverflowError):
            return key
    return None


def quarantine(cursor):
    # Called only before child launch or after it has been reaped: no send race.
    cursor.execute("UPDATE automation_queue SET status='ambiguous', error=%s WHERE status='processing'", (MARKER,))
    cursor.execute("UPDATE automation_actions SET status='failed', error=%s, completed_at=%s WHERE status='processing'",
                   (MARKER, datetime.now().astimezone().isoformat()))


def connection(*, readonly=False):
    import psycopg
    return psycopg.connect(os.environ['DATABASE_URL'], connect_timeout=5,
                          options='-c statement_timeout=5000 -c lock_timeout=3000' +
                          (' -c default_transaction_read_only=on' if readonly else ''))


def stop_child(child):
    if child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(timeout=STOP_SECONDS)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=STOP_SECONDS)


def main():
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    child = None
    backoff = 10
    try:
        while not stop.is_set():
            try:
                with connection() as db, db.cursor() as cursor:
                    quarantine(cursor)
            except Exception as exc:
                log('guard_start_deferred', error_type=type(exc).__name__)
                stop.wait(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                continue
            if stop.is_set():
                break
            started = time.time()
            child = subprocess.Popen([sys.executable, '-m', 'tg_migrator', 'watch'])
            log('guard_child_started', pid=child.pid)
            while not stop.wait(POLL_SECONDS):
                if child.poll() is not None:
                    log('guard_child_exited', exit_code=child.returncode)
                    break
                try:
                    with connection(readonly=True) as db, db.cursor() as cursor:
                        cursor.execute("SELECT key,value FROM automation_settings WHERE key IN ('worker_heartbeat_at','scheduler_heartbeat_at')")
                        reason = stale_reason(dict(cursor.fetchall()), now=time.time(), started=started)
                except Exception as exc:
                    # Database outage alone is not evidence of a stuck Telegram task.
                    log('guard_probe_failed', error_type=type(exc).__name__)
                    continue
                if reason:
                    log('guard_stale', heartbeat=reason)
                    break
            stop_child(child)
            child = None
            if time.time() - started >= STALE_SECONDS:
                backoff = 10
            if not stop.is_set():
                stop.wait(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
    finally:
        if child is not None:
            stop_child(child)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
