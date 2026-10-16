import json
import socket
from pathlib import Path

import guest_shortlist as G

ROOT = Path(__file__).resolve().parent
PUBLIC = ["README.md", "saved-prompt.md", "usecase.md", "sample-output.md", "config.json", "guest_shortlist.py"]


class FakeResponse:
    def __init__(self, body, status=200):
        self.status_code = status
        self._body = body
        self.text = ""

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, search, users, web):
        self.headers = {}
        self.calls = []
        self.search = search
        self.users = users
        self.web = web

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params})
        if url.endswith("/twitter/post/user"):
            return FakeResponse(self.users[params["user"]])
        if url.endswith("/twitter"):
            return FakeResponse(self.search)
        if url.endswith("/web"):
            return FakeResponse({"data": self.web[params["query"]]})
        raise AssertionError(url)


def cfg():
    return {
        "topic_terms": ["sourdough", "levain", "bread baking"],
        "topic_name": "sourdough",
        "today": "2026-10-14",
        "days": 30,
        "min_likes": 20,
        "count": 50,
        "max_people": 15,
        "per_user": 10,
        "brand_words": ["recipe", "recipes", "shop"],
    }


def post(account, name, description, text, created, likes, pid):
    return {
        "id": pid,
        "text": text,
        "created_at": created,
        "like_count": likes,
        "url": "https://x.com/%s/status/%s" % (account, pid),
        "user": {"username": account, "name": name, "description": description},
    }


def search_posts():
    return [
        post("ada_baker", "Ada Baker", "teaches baking", "Teaches a sourdough class and mails starter", "2026-10-11T10:00:00Z", 40, "1"),
        post("ada_baker", "Ada Baker", "teaches baking", "mailing sourdough starter to readers", "2026-09-20T10:00:00Z", 22, "2"),
        post("recipe_daily", "Daily Recipes", "recipe page", "sourdough recipe dump for the week", "2026-10-10T10:00:00Z", 50, "3"),
        post("recipe_daily", "Daily Recipes", "recipe page", "another sourdough loaf recipe", "2026-10-01T10:00:00Z", 15, "4"),
        post("solo_baker", "Solo Person", "weekend baker", "freshly milled sourdough at home", "2026-10-07T10:00:00Z", 20, "5"),
        post("old_baker", "Old Baker", "baker", "sourdough from last season", "2026-09-01T10:00:00Z", 30, "6"),
        post("weather_fan", "Weather Fan", "skies", "nice weather on the coast", "2026-10-10T10:00:00Z", 40, "7"),
    ]


def users():
    return {
        "ada_baker": [
            post("ada_baker", "Ada Baker", "teaches baking", "Teaches a sourdough class and mails starter", "2026-10-11T10:00:00Z", 40, "11"),
            post("ada_baker", "Ada Baker", "teaches baking", "mailing sourdough starter to readers", "2026-09-20T10:00:00Z", 22, "12"),
        ],
        "solo_baker": [
            post("solo_baker", "Solo Person", "weekend baker", "freshly milled sourdough at home", "2026-10-07T10:00:00Z", 20, "21"),
        ],
    }


def web():
    return {
        "Ada Baker podcast": [{"title": "A country music podcast", "snippet": "tour dates", "link": "https://example.com/music"}],
        "Ada Baker sourdough podcast": [{"title": "Baker on a local sourdough podcast", "snippet": "bread classes", "link": "https://example.com/show"}],
        "Solo Person podcast": [{"title": "Another podcast", "snippet": "unrelated show", "link": "https://example.com/other"}],
        "Solo Person sourdough podcast": [{"title": "Sourdough weekly", "snippet": "no names here", "link": "https://example.com/weekly"}],
    }


def test_query_keeps_or_group():
    query = G.topic_query(cfg()["topic_terms"])
    assert query == '(sourdough OR levain OR "bread baking")'
    assert query.startswith("(") and query.endswith(")")
    start, end = G.window(cfg())
    params = G.search_params(cfg(), start, end)
    assert params["sort"] == "Latest"
    assert params["min_likes"] == 20
    assert params["count"] == 50
    assert params["start_date"] == "2026-09-14"
    assert params["end_date"] == "2026-10-14"
    assert "exclude_domains" not in params
    assert G.user_params(cfg(), "ada_baker")["query"] == query


def test_fetch_and_build(monkeypatch, tmp_path):
    def boom(*_a, **_k):
        raise AssertionError("network call")

    monkeypatch.setattr(socket, "create_connection", boom)
    session = FakeSession(search_posts(), users(), web())
    monkeypatch.setenv("DESEARCH_API_KEY", "test-key-value")
    raw, key = G.run_live(cfg(), session=session)
    assert session.headers["Authorization"] == "test-key-value"
    urls = [call["url"] for call in session.calls]
    assert urls[0] == "https://api.desearch.ai/twitter"
    assert "https://api.desearch.ai/twitter/post/user" in urls
    assert "https://api.desearch.ai/web" in urls
    accounts = [call["params"].get("user") for call in session.calls if call["url"].endswith("/twitter/post/user")]
    assert accounts == ["ada_baker", "solo_baker"]
    queries = [call["params"].get("query") for call in session.calls if call["url"].endswith("/web")]
    assert queries == [
        "Ada Baker podcast",
        "Ada Baker sourdough podcast",
        "Solo Person podcast",
        "Solo Person sourdough podcast",
    ]
    assert "exclude_domains" not in json.dumps(session.calls)
    rows, skipped = G.build(raw, str(tmp_path), key=key)
    assert raw["search_kept"] == 5
    assert skipped == ["brand-style account"]
    assert [row["podcast"] for row in rows] == ["found after adding the topic", "none found"]
    assert [row["label"] for row in rows] == ["person", "one post only"]
    assert rows[0]["on_topic"] == 2 and rows[0]["newest"] == "2026-10-11"
    assert rows[1]["on_topic"] == 1 and rows[1]["newest"] == "2026-10-07"
    assert all(row["person"] == "a user" for row in rows)
    text = (tmp_path / "shortlist.md").read_text() + (tmp_path / "guests.csv").read_text()
    for hidden in ("ada_baker", "solo_baker", "recipe_daily", "old_baker", "Ada Baker", "Solo Person", "Daily Recipes"):
        assert hidden not in text
    assert "a user" in text
    assert "no contact details" in text
    assert "https://x.com/ada_baker" not in text
    assert "\u2014" not in text


def test_build_redacts_key(tmp_path):
    raw = {
        "cfg": cfg(),
        "start_date": "2026-09-14",
        "end_date": "2026-10-14",
        "search_kept": 1,
        "people": [{
            "account": "ada_baker",
            "name": "Ada Baker",
            "brand": False,
            "tokens": ["baker"],
        }],
        "user_calls": [{
            "account": "ada_baker",
            "body": [{
                "text": "sourdough leak super-secret-key",
                "created_at": "2026-10-11T10:00:00Z",
                "user": {"username": "ada_baker", "name": "Ada Baker"},
            }],
        }],
        "web_calls": [],
    }
    G.build(raw, str(tmp_path), key="super-secret-key")
    blob = (tmp_path / "shortlist.md").read_text() + (tmp_path / "guests.csv").read_text()
    assert "super-secret-key" not in blob
    assert "ada_baker" not in blob
    assert "<redacted>" in blob


def test_api_key_from_env(monkeypatch):
    monkeypatch.setenv("DESEARCH_API_KEY", "test-key")
    monkeypatch.delenv("DESEARCH_API_KEY_FILE", raising=False)
    assert G.api_key() == "test-key"


def test_api_key_from_file(monkeypatch, tmp_path):
    monkeypatch.delenv("DESEARCH_API_KEY", raising=False)
    path = tmp_path / "key"
    path.write_text("from-file\n")
    monkeypatch.setenv("DESEARCH_API_KEY_FILE", str(path))
    assert G.api_key() == "from-file"


def test_api_key_missing(monkeypatch):
    monkeypatch.delenv("DESEARCH_API_KEY", raising=False)
    monkeypatch.delenv("DESEARCH_API_KEY_FILE", raising=False)
    try:
        G.api_key()
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
