import social_listening as S


def raw():
    return {
        "run_at": "2026-10-15T12:00:00+00:00",
        "since": "2026-10-08",
        "cfg": {
            "brand": "Duolingo",
            "x_query": '(duolingo OR "duo owl") lang:en',
            "web_query": "duolingo",
            "on_topic_words": ["duolingo", "duo"],
        },
        "x": [{
            "params": {"query": "duolingo", "sort": "Latest"},
            "status": 200,
            "seconds": 1.1,
            "cost_usd": "0.003",
            "body": [
                {
                    "id": "1",
                    "created_at": "Thu Oct 15 11:27:39 +0000 2026",
                    "text": "super Duolingo is loud @alice \u2014 again",
                    "like_count": 3,
                    "retweet_count": 1,
                    "reply_count": 0,
                    "view_count": 20,
                    "user": {"username": "alice"},
                    "url": "https://x.com/i/status/1",
                },
                {
                    "id": "1",
                    "created_at": "Thu Oct 15 11:27:39 +0000 2026",
                    "text": "duplicate",
                    "user": {"username": "alice"},
                },
                {
                    "id": "2",
                    "created_at": "Wed Oct 14 09:00:00 +0000 2026",
                    "text": "unrelated weather chat",
                    "like_count": 1,
                    "user": {"username": "bob"},
                },
            ],
        }],
        "web": [
            {
                "params": {"start": 0},
                "status": 200,
                "seconds": 0.8,
                "cost_usd": "0.001",
                "body": {"data": [
                    {"title": "Duolingo", "link": "https://www.duolingo.com/learn", "snippet": "Learn a language"},
                    {"title": "Same page", "link": "https://www.duolingo.com/learn", "snippet": "dup"},
                ]},
            },
            {
                "params": {"start": 10},
                "status": 200,
                "seconds": 0.7,
                "cost_usd": "0.001",
                "body": {"data": [
                    {"title": "Forum thread", "link": "https://www.reddit.com/r/duolingo/comments/1", "snippet": "streak help"},
                ]},
            },
        ],
    }


def test_build_dedupes_and_tags(tmp_path):
    rows, stats, byday = S.build(raw(), str(tmp_path), key="super-secret-key")
    x = [r for r in rows if r["source"] == "x"]
    web = [r for r in rows if r["source"] == "web"]
    assert [r["id"] for r in x] == ["1", "2"]
    assert x[0]["on_topic"] is True and x[1]["on_topic"] is False
    assert len(web) == 2
    assert stats[0]["new_urls"] == 1 and stats[1]["new_urls"] == 1
    assert byday["2026-10-15"] == 1
    mentions = (tmp_path / "mentions.csv").read_text()
    assert "alice" not in mentions
    assert "Account 1" in mentions
    report = (tmp_path / "report.md").read_text()
    assert "Account A" in report
    assert "\u2014" not in report
    assert "duolingo.com" in report


def test_build_redacts_key(tmp_path):
    body = raw()
    body["x"][0]["body"][0]["text"] = "duolingo leak super-secret-key"
    S.build(body, str(tmp_path), key="super-secret-key")
    blob = (tmp_path / "report.md").read_text() + (tmp_path / "mentions.csv").read_text()
    assert "super-secret-key" not in blob
    assert "<redacted>" in blob


def test_api_key_from_env(monkeypatch):
    monkeypatch.setenv("DESEARCH_API_KEY", "test-key")
    monkeypatch.delenv("DESEARCH_API_KEY_FILE", raising=False)
    assert S.api_key() == "test-key"


def test_api_key_missing(monkeypatch):
    monkeypatch.delenv("DESEARCH_API_KEY", raising=False)
    monkeypatch.delenv("DESEARCH_API_KEY_FILE", raising=False)
    try:
        S.api_key()
    except SystemExit as exc:
        assert "DESEARCH_API_KEY" in str(exc)
    else:
        raise AssertionError("expected SystemExit")
