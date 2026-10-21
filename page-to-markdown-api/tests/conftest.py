"""All demo tests are offline, including accidental unmocked calls."""
import socket
import sys
from pathlib import Path
import urllib.request
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.delenv('DESEARCH_API_KEY', raising=False)
    monkeypatch.delenv('DESEARCH_API_KEY_FILE', raising=False)
    def blocked(*args, **kwargs):
        raise AssertionError('Network calls are forbidden in tests')
    monkeypatch.setattr(socket, 'getaddrinfo', blocked)
    monkeypatch.setattr(urllib.request.OpenerDirector, 'open', blocked)
    monkeypatch.setattr(urllib.request, 'urlopen', blocked)
