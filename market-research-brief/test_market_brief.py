import market_brief as M


def raw():
    page = (
        "The Breville Bambino holds temperature well. "
        "Street price is $500 for a home machine. "
        + ("Extra review notes about the shot and the wand. " * 8)
    )
    return {
        "run_at": "2026-10-15T12:00:00+00:00",
        "cfg": {
            "market": "home espresso machines",
            "web_query": "best home espresso machine",
            "brands": ["breville", "gaggia"],
            "brand_domains": ["amazon", "breville"],
            "complaint_words": ["temperature", "leak"],
        },
        "web": [{
            "params": {"start": 0},
            "status": 200,
            "seconds": 1.0,
            "cost_usd": "0.001",
            "body": {"data": [
                {"title": "Shop \u2014 machines", "link": "https://www.amazon.com/espresso-machine", "snippet": "buy"},
                {"title": "Best home machine", "link": "https://www.reddit.com/r/espresso/best", "snippet": "Breville"},
                {"title": "Same thread", "link": "https://www.reddit.com/r/espresso/best/", "snippet": "dup"},
                {"title": "Guide", "link": "https://reviews.example/guide", "snippet": "short page"},
            ]},
        }],
        "extract": [
            {
                "params": {"url": "https://www.reddit.com/r/espresso/best"},
                "status": 200,
                "seconds": 1.4,
                "cost_usd": "0.0005",
                "body": {"content": page},
            },
            {
                "params": {"url": "https://reviews.example/guide"},
                "status": 200,
                "seconds": 0.4,
                "cost_usd": "0.0005",
                "body": {"content": "menu only"},
            },
        ],
        "x": [{
            "status": 200,
            "body": [{"text": "temperature swings on my machine", "user": {"username": "alice"}}],
        }],
    }


def test_build_counts_brands_and_skips_stores(tmp_path):
    rows, stats, ex, bc, cc, prices = M.build(raw(), str(tmp_path), key="super-secret-key")
    assert len(rows) == 3
    assert stats[0]["new_urls"] == 3
    assert sum(r["brand_owned"] for r in rows) == 1
    assert bc["breville"] == 1
    assert cc["temperature"] == 1
    assert prices == [500.0]
    assert sum(e["empty"] for e in ex) == 1
    brief = (tmp_path / "brief.md").read_text()
    assert "breville" in brief and "temperature" in brief
    assert "\u2014" not in brief
    pages = (tmp_path / "web-pages.csv").read_text()
    assert "\u2014" not in pages
    assert "Shop" in pages and "machines" in pages


def test_build_redacts_key(tmp_path):
    body = raw()
    body["web"][0]["body"]["data"][1]["snippet"] = "leak super-secret-key in a breville note"
    M.build(body, str(tmp_path), key="super-secret-key")
    blob = (tmp_path / "brief.md").read_text() + (tmp_path / "web-pages.csv").read_text()
    assert "super-secret-key" not in blob
    assert "<redacted>" in blob


def test_api_key_from_env(monkeypatch):
    monkeypatch.setenv("DESEARCH_API_KEY", "test-key")
    monkeypatch.delenv("DESEARCH_API_KEY_FILE", raising=False)
    assert M.api_key() == "test-key"


def test_api_key_from_file(monkeypatch, tmp_path):
    monkeypatch.delenv("DESEARCH_API_KEY", raising=False)
    path = tmp_path / "key"
    path.write_text("from-file\n")
    monkeypatch.setenv("DESEARCH_API_KEY_FILE", str(path))
    assert M.api_key() == "from-file"


def test_api_key_missing(monkeypatch):
    monkeypatch.delenv("DESEARCH_API_KEY", raising=False)
    monkeypatch.delenv("DESEARCH_API_KEY_FILE", raising=False)
    try:
        M.api_key()
    except SystemExit as exc:
        assert "DESEARCH_API_KEY" in str(exc)
    else:
        raise AssertionError("expected SystemExit")
