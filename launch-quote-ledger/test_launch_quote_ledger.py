import launch_quote_ledger as L


def raw():
    return {
        "run_at": "2026-10-15T12:00:00+00:00",
        "count": 20,
        "launches": [{
            "label": "Launch A",
            "id": "100",
            "user": "maker",
            "calls": {
                "post": {"body": {"id": "100"}, "status": 200, "seconds": 0.4, "cost_usd": "0.0015"},
                "quoted_id_quote": {
                    "status": 200,
                    "seconds": 1.2,
                    "cost_usd": "0.003",
                    "body": [
                        {
                            "id": "200",
                            "quoted_status_id": "100",
                            "is_quote_tweet": True,
                            "user": {"username": "alice", "is_blue_verified": True},
                            "created_at": "Wed Oct 14 15:05:24 +0000 2026",
                            "like_count": 2,
                            "view_count": 10,
                            "text": "Not sponsored, just sharing @alice \u2014 hello",
                        },
                        {
                            "id": "201",
                            "quoted_status_id": "999",
                            "is_quote_tweet": True,
                            "user": {"username": "bob", "is_blue_verified": False},
                            "created_at": "Wed Oct 14 16:00:00 +0000 2026",
                            "like_count": 1,
                            "view_count": 3,
                            "text": "quotes something else",
                        },
                    ],
                },
            },
        }],
    }


def test_build_keeps_quotes_of_this_launch(tmp_path):
    ledger, stats = L.build(raw(), str(tmp_path), key="super-secret-key")
    assert [r["quote_id"] for r in ledger] == ["200"]
    assert ledger[0]["negated"] is True
    assert "sponsored" in ledger[0]["disclosure_wording"]
    assert stats[0]["quote_this_launch"] == 1
    md = (tmp_path / "quotes.md").read_text()
    assert "Account A" in md and "alice" not in md
    assert "\u2014" not in md
    assert "@account" in md and "hello" in md
    csv_text = (tmp_path / "quotes.csv").read_text()
    assert "201" not in csv_text


def test_build_redacts_key(tmp_path):
    body = raw()
    body["launches"][0]["calls"]["quoted_id_quote"]["body"][0]["text"] = "leak super-secret-key please"
    L.build(body, str(tmp_path), key="super-secret-key")
    blob = (tmp_path / "quotes.md").read_text() + (tmp_path / "quotes.csv").read_text()
    assert "super-secret-key" not in blob
    assert "<redacted>" in blob


def test_save_raw_redacts_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    L.save_raw({"run_at": "2026-10-15T00:00:00", "note": "secret-key-value"}, "secret-key-value")
    text = (tmp_path / "evidence" / "raw-2026-10-15.json").read_text()
    assert "secret-key-value" not in text
    assert "<redacted>" in text


def test_api_key_from_env(monkeypatch):
    monkeypatch.setenv("DESEARCH_API_KEY", "test-key")
    monkeypatch.delenv("DESEARCH_API_KEY_FILE", raising=False)
    assert L.api_key() == "test-key"


def test_api_key_from_file(monkeypatch, tmp_path):
    monkeypatch.delenv("DESEARCH_API_KEY", raising=False)
    path = tmp_path / "key"
    path.write_text("from-file\n")
    monkeypatch.setenv("DESEARCH_API_KEY_FILE", str(path))
    assert L.api_key() == "from-file"


def test_api_key_missing(monkeypatch):
    monkeypatch.delenv("DESEARCH_API_KEY", raising=False)
    monkeypatch.delenv("DESEARCH_API_KEY_FILE", raising=False)
    try:
        L.api_key()
    except SystemExit as exc:
        assert "DESEARCH_API_KEY" in str(exc)
    else:
        raise AssertionError("expected SystemExit")
