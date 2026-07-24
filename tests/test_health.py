from __future__ import annotations

import urllib.request

from tg_migrator.health import maybe_start_health_server, start_health_server


def test_health_server_responds() -> None:
    server = start_health_server(0)
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/health"
        ) as response:
            assert response.status == 200
            assert b"ok" in response.read()
    finally:
        server.shutdown()
        server.server_close()


def test_disabled_without_env(monkeypatch) -> None:
    monkeypatch.delenv("TG_HEALTH_PORT", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    assert maybe_start_health_server() is None


def test_enabled_with_env(monkeypatch) -> None:
    monkeypatch.setenv("TG_HEALTH_PORT", "0")
    server = maybe_start_health_server()
    assert server is not None
    server.shutdown()
    server.server_close()


def test_invalid_port_ignored(monkeypatch) -> None:
    monkeypatch.setenv("TG_HEALTH_PORT", "not-a-port")
    monkeypatch.delenv("PORT", raising=False)
    assert maybe_start_health_server() is None
