"""Every test is offline, including accidental live-client paths."""
import socket
import pytest


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.delenv("DESEARCH_API_KEY", raising=False)
    monkeypatch.delenv("DEMO_X_FILTER", raising=False)
    def blocked(*args, **kwargs):
        raise AssertionError("Network access is forbidden in tests")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
