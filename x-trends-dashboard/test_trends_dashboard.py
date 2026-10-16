import trends_dashboard as T


def body(woeid, names, returned=None):
    return {
        "params": {"woeid": woeid, "count": 30},
        "status": 200,
        "seconds": 0.4,
        "cost_usd": "0.0045",
        "body": {
            "woeid": woeid if returned is None else returned,
            "trends": [{"name": n, "tweet_volume": None} for n in names],
        },
    }


def raw():
    return {
        "run_at": "2026-10-16T11:51:43+04:00",
        "label": "run-1",
        "cfg": {
            "places": {"1": "Worldwide", "23424977": "United States", "23424848": "India"},
            "count": 30,
            "sample_top_shared": 3,
            "x_count": 10,
        },
        "trends": [
            body(1, ["Tesla", "Local Only"]),
            body(23424977, ["#Tesla", "Dodgers"]),
            body(23424848, ["Tesla"], returned=1),
        ],
        "x": [{
            "params": {"query": "Tesla"},
            "body": [{
                "created_at": "Fri Oct 16 07:51:39 +0000 2026",
                "like_count": 1,
                "text": "love @alice this https://x.com/a \u2014 car",
            }],
        }],
    }


def previous():
    cfg = raw()["cfg"]
    return {
        "run_at": "2026-10-16T11:00:00+04:00",
        "label": "run-0",
        "cfg": cfg,
        "trends": [
            body(1, ["Local Only", "Tesla"]),
            body(23424977, ["Dodgers"]),
        ],
        "x": [],
    }


def test_shared_ignores_case_hash_and_mismatch(tmp_path):
    summary = T.build(raw(), str(tmp_path), previous(), key="super-secret-key")
    shared = {item["trend"]: item["places"] for item in summary["shared"]}
    assert shared["Tesla"] == ["United States", "Worldwide"]
    assert "India" not in shared["Tesla"]
    assert summary["woeid_mismatch"] == ["India"]
    html = (tmp_path / "dashboard-run-1.html").read_text()
    assert "Account A" in html and "alice" not in html
    assert "[account]" in html and "[link]" in html
    assert "\u2014" not in html
    assert "class='s'" in html
    moves = (tmp_path / "moves-run-1.csv").read_text()
    assert "new" in moves
    rows = (tmp_path / "trends-run-1.csv").read_text()
    assert "Local Only" in rows


def test_build_redacts_key(tmp_path):
    body = raw()
    body["x"][0]["body"][0]["text"] = "Tesla leak super-secret-key"
    T.build(body, str(tmp_path), key="super-secret-key")
    blob = "".join(p.read_text() for p in tmp_path.iterdir())
    assert "super-secret-key" not in blob
    assert "<redacted>" in blob


def test_save_raw_redacts_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    T.save_raw({"run_at": "2026-10-16T00:00:00", "label": "run-1", "note": "secret-key-value"}, "secret-key-value")
    text = (tmp_path / "evidence" / "raw-run-1.json").read_text()
    assert "secret-key-value" not in text
    assert "<redacted>" in text


def test_api_key_from_env(monkeypatch):
    monkeypatch.setenv("DESEARCH_API_KEY", "test-key")
    monkeypatch.delenv("DESEARCH_API_KEY_FILE", raising=False)
    assert T.api_key() == "test-key"


def test_api_key_from_file(monkeypatch, tmp_path):
    monkeypatch.delenv("DESEARCH_API_KEY", raising=False)
    path = tmp_path / "key"
    path.write_text("from-file\n")
    monkeypatch.setenv("DESEARCH_API_KEY_FILE", str(path))
    assert T.api_key() == "from-file"


def test_api_key_missing(monkeypatch):
    monkeypatch.delenv("DESEARCH_API_KEY", raising=False)
    monkeypatch.delenv("DESEARCH_API_KEY_FILE", raising=False)
    try:
        T.api_key()
    except SystemExit as exc:
        assert "DESEARCH_API_KEY" in str(exc)
    else:
        raise AssertionError("expected SystemExit")
