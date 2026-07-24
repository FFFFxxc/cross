"""Мини HTTP-сервер статуса для облачных платформ.

Hugging Face Spaces (и похожие PaaS) считают контейнер работающим,
только если он отвечает по HTTP на заданном порту. Сервер отдаёт
«ok» на любой GET-запрос и работает в фоновом потоке, не мешая
основному циклу Telethon.
"""

from __future__ import annotations

import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_BODY = b"tg-migrator: ok\n"


class _HealthHandler(BaseHTTPRequestHandler):
    def _respond(self, include_body: bool) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(_BODY)))
        self.end_headers()
        if include_body:
            self.wfile.write(_BODY)

    def do_GET(self) -> None:  # noqa: N802 (API BaseHTTPRequestHandler)
        self._respond(include_body=True)

    def do_HEAD(self) -> None:  # noqa: N802
        self._respond(include_body=False)

    def log_message(self, *args) -> None:
        # Не засорять журнал переносчика записями о пингах.
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
    """Запустить сервер, если задан TG_HEALTH_PORT (или PORT)."""
    raw = os.getenv("TG_HEALTH_PORT") or os.getenv("PORT")
    if not raw:
        return None
    try:
        port = int(raw)
    except ValueError:
        return None
    return start_health_server(port)
