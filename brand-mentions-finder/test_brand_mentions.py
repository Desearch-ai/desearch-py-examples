import json
import socket
from pathlib import Path

import brand_mentions as B

ROOT = Path(__file__).resolve().parent
PUBLIC = ["README.md", "saved-prompt.md", "usecase.md", "sample-output.md", "config.json", "brand_mentions.py"]


class FakeResponse:
    def __init__(self, body, status=200):
        self.status_code = status
        self._body = body
        self.headers = {}
        self.text = json.dumps(body) if not isinstance(body, str) else body

    def json(self):
        if isinstance(self._body, str):
            raise ValueError("not json")
        return self._body


class FakeSession:
    def __init__(self, ai_body, x_body):
        self.headers = {}
        self.calls = []
        self.ai_body = ai_body
        self.x_body = x_body

    def post(self, url, json=None, timeout=None):
        self.calls.append({"method": "POST", "url": url, "json": json})
        return FakeResponse(self.ai_body)

    def get(self, url, params=None, timeout=None):
        self.calls.append({"method": "GET", "url": url, "params": params})
        return FakeResponse(self.x_body)


def cfg():
    return {
        "brand": "Raycast",
        "what_it_is": "the Mac launcher app",
        "brand_terms": ["Raycast", "raycast app"],
        "own_account": "raycast",
        "own_domains": ["raycast.com"],
        "product_words": ["mac", "launcher", "app"],
        "other_meaning_words": ["unity", "godot"],
        "today": "2026-10-15",
        "days": 30,
        "min_likes": 5,
        "x_count": 20,
    }


def bodies():
    ai = {
        "search": [
            {"title": "Raycast Review", "link": "https://www.raycast.com/pricing", "snippet": "Pro pricing"},
            {"title": "Raycast Review: The macOS Launcher", "link": "https://pickuma.com/raycast", "snippet": "Developers keep it"},
            {"title": "Same review", "link": "https://pickuma.com/raycast", "snippet": "dup"},
            {"title": "Launcher notes", "link": "https://dev.to/raycast-notes", "snippet": "Raycast replaced four apps"},
        ],
        "tweets": [
            {
                "id": "10",
                "text": "asked Raycast to find what was using memory",
                "created_at": "Wed Oct 15 08:00:00 +0000 2026",
                "url": "https://x.com/someone/status/10",
                "user": {"username": "someone"},
            },
            {
                "id": "11",
                "text": "shipping day at the company account",
                "created_at": "Wed Oct 15 09:00:00 +0000 2026",
                "url": "https://x.com/raycast/status/11",
                "user": {"username": "raycast"},
            },
        ],
    }
    x_body = [
        {
            "id": "10",
            "text": "asked Raycast to find what was using memory",
            "created_at": "Wed Oct 15 08:00:00 +0000 2026",
            "url": "https://x.com/someone/status/10",
            "user": {"username": "someone"},
        },
        {
            "id": "12",
            "text": "Unity raycast hit detection for a game object",
            "created_at": "Tue Oct 14 08:00:00 +0000 2026",
            "url": "https://x.com/gamedev/status/12",
            "user": {"username": "gamedev"},
        },
        {
            "id": "13",
            "text": "I'm uninstalling Raycast after years of heavy use",
            "created_at": "Mon Sep 15 12:00:00 +0000 2026",
            "url": "https://x.com/person/status/13",
            "user": {"username": "person"},
        },
        {
            "id": "14",
            "text": "weather is nice today",
            "created_at": "Mon Sep 15 12:00:00 +0000 2026",
            "user": {"username": "person"},
        },
    ]
    return ai, x_body


def test_query_keeps_or_group_and_skips_domain_param():
    query = B.x_query(cfg())
    assert query == '(Raycast OR "raycast app") -from:raycast'
    assert query.startswith("(") and " OR " in query
    payload = B.ai_payload(cfg(), *B.window(cfg()))
    assert "exclude_domains" not in payload
    assert payload["tools"] == ["web", "twitter"]
    assert payload["result_type"] == "ONLY_LINKS"
    assert payload["streaming"] is False
    assert payload["start_date"] == "2026-09-15T00:00:00Z"
    assert payload["end_date"] == "2026-10-15T23:59:59Z"


def test_fetch_and_build_filters_in_code(monkeypatch, tmp_path):
    def boom(*_a, **_k):
        raise AssertionError("network call")

    monkeypatch.setattr(socket, "create_connection", boom)
    ai, x_body = bodies()
    session = FakeSession(ai, x_body)
    monkeypatch.setenv("DESEARCH_API_KEY", "test-key-value")
    raw, key = B.run_live(cfg(), session=session)
    assert key == "test-key-value"
    assert session.headers["Authorization"] == "test-key-value"
    assert session.calls[0]["url"] == "https://api.desearch.ai/desearch/ai/search"
    assert session.calls[1]["url"] == "https://api.desearch.ai/twitter"
    assert session.calls[1]["params"]["sort"] == "Latest"
    assert session.calls[1]["params"]["min_likes"] == 5
    assert "exclude_domains" not in json.dumps(session.calls)
    kept, left = B.build(raw, str(tmp_path), key="test-key-value")
    reasons = {row["reason"] for row in left}
    assert "own domain" in reasons
    assert "own account" in reasons
    assert "duplicate" in reasons
    assert "other meaning" in reasons
    links = [row["link"] for row in kept]
    assert "https://pickuma.com/raycast" in links
    assert "https://dev.to/raycast-notes" in links
    assert "https://x.com/i/status/10" in links
    assert "https://x.com/i/status/13" in links
    assert all("x.com/someone" not in row["link"] and "x.com/person" not in row["link"] for row in kept)
    text = (tmp_path / "mentions.md").read_text() + (tmp_path / "mentions.csv").read_text()
    assert "a user" in text
    assert "someone" not in text
    assert "gamedev" not in text
    assert "person" not in text
    assert "uninstalling" in text
    assert "negative" in text
    assert "\u2014" not in text
    tone = {row["link"]: row["tone"] for row in kept}
    assert tone["https://dev.to/raycast-notes"] == "positive"
    assert tone["https://x.com/i/status/13"] == "negative"


def test_build_redacts_key(tmp_path):
    ai, x_body = bodies()
    ai["search"][1]["snippet"] = "leak super-secret-key in a Raycast note"
    raw = {
        "cfg": cfg(),
        "end_date": "2026-10-15",
        "ai": {"body": ai},
        "x": {"body": x_body},
    }
    B.build(raw, str(tmp_path), key="super-secret-key")
    blob = (tmp_path / "mentions.md").read_text() + (tmp_path / "mentions.csv").read_text()
    assert "super-secret-key" not in blob
    assert "<redacted>" in blob


def test_own_subdomain():
    assert B.on_own_domain("https://manual.raycast.com/docs", ["raycast.com"])
    assert B.on_own_domain("https://www.raycast.com/store", ["raycast.com"])
    assert not B.on_own_domain("https://pickuma.com/raycast", ["raycast.com"])


def test_api_key_from_env(monkeypatch):
    monkeypatch.setenv("DESEARCH_API_KEY", "test-key")
    monkeypatch.delenv("DESEARCH_API_KEY_FILE", raising=False)
    assert B.api_key() == "test-key"


def test_api_key_from_file(monkeypatch, tmp_path):
    monkeypatch.delenv("DESEARCH_API_KEY", raising=False)
    path = tmp_path / "key"
    path.write_text("from-file\n")
    monkeypatch.setenv("DESEARCH_API_KEY_FILE", str(path))
    assert B.api_key() == "from-file"


def test_api_key_missing(monkeypatch):
    monkeypatch.delenv("DESEARCH_API_KEY", raising=False)
    monkeypatch.delenv("DESEARCH_API_KEY_FILE", raising=False)
    try:
        B.api_key()
    except SystemExit as exc:
        assert "DESEARCH_API_KEY" in str(exc)
    else:
        raise AssertionError("expected SystemExit")


def test_public_text_rules():
    banned = [
        "\u2014", "real-time", "realtime", "every mention", "exclude_domains",
        "brandwatch", "meltwater", "hootsuite", "tweetdeck", "talkwalker",
        "sprinklr", "brand24", "awario", "podchaser", "dsr_", "dt_",
    ]
    for name in PUBLIC:
        text = (ROOT / name).read_text().lower()
        for phrase in banned:
            assert phrase not in text, "%s contains %s" % (name, phrase)
    joined = "\n".join((ROOT / name).read_text() for name in PUBLIC[:4])
    assert "a user" in joined
    assert "Bearer <key>" in (ROOT / "README.md").read_text()
