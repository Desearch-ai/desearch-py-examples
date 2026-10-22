"""Every test is offline, including accidental live-client paths."""
import socket
import pytest


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.delenv('VERCEL', raising=False)
    monkeypatch.delenv('VERCEL_ENV', raising=False)
    for name in ("DESEARCH_API_KEY", "DEMO_STATE", "UPSTASH_REDIS_REST_URL",
                 "UPSTASH_REDIS_REST_TOKEN", "KV_REST_API_URL", "KV_REST_API_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("DEMO_X_FILTER", raising=False)
    def blocked(*args, **kwargs):
        raise AssertionError("Network access is forbidden in tests")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
