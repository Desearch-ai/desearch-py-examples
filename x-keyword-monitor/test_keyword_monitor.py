import json
import socket
from pathlib import Path

import keyword_monitor as K

ROOT = Path(__file__).resolve().parent
PUBLIC = ["README.md", "saved-prompt.md", "usecase.md", "sample-output.md", "config.json", "keyword_monitor.py"]


class FakeResponse:
    def __init__(self, body, status=200):
        self.status_code = status
        self._body = body
        self.headers = {}
        self.text = ""

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, body):
        self.headers = {}
        self.calls = []
        self.body = body

    def get(self, url, params=None, timeout=None):
        self.calls.append({"method": "GET", "url": url, "params": params})
        return FakeResponse(self.body)


def cfg():
    return {
        "keywords": ["home espresso", "espresso machine", "latte art"],
        "min_likes": 5,
        "count": 20,
        "last_check": "2026-10-14T11:35:00Z",
        "now": "2026-10-15T11:35:00Z",
    }


def posts():
    return [
        {
            "id": "1",
            "text": "I almost paid $289 for an espresso machine.",
            "created_at": "2026-10-15T08:20:00Z",
            "like_count": 42,
            "url": "https://x.com/zz_handle/status/1",
            "user": {"username": "zz_handle"},
        },
        {
            "id": "2",
            "text": "home espresso at the exact check time",
            "created_at": "2026-10-14T11:35:00Z",
            "like_count": 9,
            "user": {"username": "zz_other"},
        },
        {
            "id": "3",
            "text": "premier latte art de la journee @zz_handle",
            "created_at": "Thu Oct 15 07:04:00 +0000 2026",
            "like_count": 7,
            "url": "https://x.com/zz_other/status/3",
            "user": {"username": "zz_other"},
        },
        {
            "id": "4",
            "text": "https://example.com/only-a-link",
            "created_at": "2026-10-15T04:00:00Z",
            "like_count": 6,
            "user": {"username": "zz_link"},
        },
        {
            "id": "5",
            "text": "nice weather on the coast today",
            "created_at": "2026-10-15T03:00:00Z",
            "like_count": 8,
            "user": {"username": "zz_weather"},
        },
        {
            "id": "1",
            "text": "duplicate espresso machine row",
            "created_at": "2026-10-15T09:00:00Z",
            "like_count": 1,
            "user": {"username": "zz_handle"},
        },
    ]


def test_query_keeps_or_group():
    query = K.keyword_query(cfg()["keywords"])
    assert query == '("home espresso" OR "espresso machine" OR "latte art")'
    assert query.startswith("(") and query.endswith(")")
    params = K.x_params(cfg(), K.parse_time(cfg()["now"]))
    assert params["sort"] == "Latest"
    assert params["start_date"] == "2026-10-14"
    assert params["end_date"] == "2026-10-15"
    assert params["min_likes"] == 5
    assert "exclude_domains" not in params


def test_fetch_and_build_filters(monkeypatch, tmp_path):
    def boom(*_a, **_k):
        raise AssertionError("network call")

    monkeypatch.setattr(socket, "create_connection", boom)
    session = FakeSession(posts())
    monkeypatch.setenv("DESEARCH_API_KEY", "test-key-value")
    raw, key = K.run_live(cfg(), session=session)
    assert session.headers["Authorization"] == "test-key-value"
    assert session.calls[0]["url"] == "https://api.desearch.ai/twitter"
    assert "exclude_domains" not in json.dumps(session.calls)
    returned, new, kept = K.build(raw, str(tmp_path), key=key)
    assert [row["id"] for row in returned] == ["1", "2", "3", "4", "5"]
    assert len(new) == 4
    assert [row["keyword"] for row in kept] == ["espresso machine", "latte art"]
    assert kept[0]["time"] == "2026-10-15 08:20"
    text = (tmp_path / "monitor.md").read_text() + (tmp_path / "posts.csv").read_text()
    assert "a user" in text
    assert "zz_handle" not in text
    assert "zz_other" not in text
    assert "zz_link" not in text
    assert "zz_weather" not in text
    assert "https://x.com/i/status/1" in text
    assert "x.com/zz_handle" not in text
    assert "Next LAST CHECK: 2026-10-15T11:35:00+00:00" in text
    assert "\u2014" not in text
    assert text.count("## Summary") == 1


def test_link_only_and_keyword():
    assert K.link_only("https://t.co/abc")
    assert not K.link_only("LATTE ART photo")
    assert K.matched_keyword("The Meraki Espresso Machine is good", ["home espresso", "espresso machine"]) == "espresso machine"


def test_build_redacts_key(tmp_path):
    raw = {
        "cfg": cfg(),
        "last_check": cfg()["last_check"],
        "now": cfg()["now"],
        "x": {"body": [{
            "id": "9",
            "text": "espresso machine leak super-secret-key",
            "created_at": "2026-10-15T08:00:00Z",
            "like_count": 5,
            "user": {"username": "zz_handle"},
        }]},
    }
    K.build(raw, str(tmp_path), key="super-secret-key")
    blob = (tmp_path / "monitor.md").read_text() + (tmp_path / "posts.csv").read_text()
    assert "super-secret-key" not in blob
    assert "<redacted>" in blob


def test_api_key_from_env(monkeypatch):
    monkeypatch.setenv("DESEARCH_API_KEY", "test-key")
    monkeypatch.delenv("DESEARCH_API_KEY_FILE", raising=False)
    assert K.api_key() == "test-key"


def test_api_key_from_file(monkeypatch, tmp_path):
    monkeypatch.delenv("DESEARCH_API_KEY", raising=False)
    path = tmp_path / "key"
    path.write_text("from-file\n")
    monkeypatch.setenv("DESEARCH_API_KEY_FILE", str(path))
    assert K.api_key() == "from-file"


def test_api_key_missing(monkeypatch):
    monkeypatch.delenv("DESEARCH_API_KEY", raising=False)
    monkeypatch.delenv("DESEARCH_API_KEY_FILE", raising=False)
    try:
        K.api_key()
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
