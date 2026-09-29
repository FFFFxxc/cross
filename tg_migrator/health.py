"""Health endpoint и защищённый HTTPS-мост к приватной PostgreSQL."""

from __future__ import annotations

import base64
import hmac
import json
import os
import re
import threading
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psycopg
from psycopg.rows import dict_row

_BODY = b"tg-migrator: ok\n"


def _json_value(value):
    if isinstance(value, bytes):
        return {
            "__type": "Buffer",
            "data": base64.b64encode(value).decode("ascii"),
        }
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    return value


def _convert_query(sql: str, values: list):
    params = []

    def replace(match):
        index = int(match.group(1))
        if index < 1 or index > len(values):
            raise ValueError(f"Нет значения для ${index}")
        params.append(values[index - 1])
        return "%s"

    converted = re.sub(r"\$(\d+)", replace, sql)
    return converted, params


class _HealthHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload) -> None:
        body = json.dumps(
            payload,
            ensure_ascii=False,
            default=_json_value,
        ).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        expected = (os.getenv("DB_BRIDGE_TOKEN") or "").strip()
        if not expected:
            return False

        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return False

        return hmac.compare_digest(expected, header[7:])

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(200, {"ok": True})
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(_BODY)))
        self.end_headers()
        self.wfile.write(_BODY)

    def do_HEAD(self) -> None:
        self.send_response(200)
        self.end_headers()

    def do_POST(self) -> None:
        if self.path != "/v1/query":
            self._send_json(404, {"error": "Not found"})
            return

        if not self._authorized():
            self._send_json(401, {"error": "Unauthorized"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1_000_000:
                raise ValueError("Некорректный размер запроса.")

            payload = json.loads(self.rfile.read(length))
            sql = str(payload.get("sql") or "").strip()
            values = payload.get("values") or []

            if not sql or not isinstance(values, list):
                raise ValueError("Некорректный SQL-запрос.")

            command = sql.split(None, 1)[0].upper()
            if command not in {"SELECT", "INSERT", "UPDATE", "DELETE", "WITH"}:
                raise ValueError("Этот тип SQL-запроса запрещён.")

            converted, params = _convert_query(sql, values)

            database_url = (os.getenv("DATABASE_URL") or "").strip()
            if not database_url:
                raise RuntimeError("DATABASE_URL не задан.")

            with psycopg.connect(database_url, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(converted, params)
                    rows = cur.fetchall() if cur.description else []

            self._send_json(
                200,
                {
                    "rows": _json_value(rows),
                    "rowCount": len(rows),
                },
            )

        except Exception as exc:
            self._send_json(400, {"error": str(exc)[:1000]})

    def log_message(self, *args) -> None:
        pass


def start_health_server(port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("0.0.0.0", port), _HealthHandler)
    thread = threading.Thread(
        target=server.serve_forever,
        name="health-server",
        daemon=True,
    )
    thread.start()
    return server


def maybe_start_health_server() -> ThreadingHTTPServer | None:
    raw = os.getenv("TG_HEALTH_PORT") or os.getenv("PORT")
    if not raw:
        return None

    try:
        port = int(raw)
    except ValueError:
        return None

    return start_health_server(port)
