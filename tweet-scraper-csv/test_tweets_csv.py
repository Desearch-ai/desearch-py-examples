import csv, io, json, pathlib
import pytest
import core, tweets_csv


def post(pid, created, user="someone", text="hi", likes=1):
    return {"id": pid, "created_at": created, "text": text, "like_count": likes, "retweet_count": 2,
            "reply_count": 3, "user": {"username": user}}


def test_or_terms_in_parentheses():
    assert core.build_query(["home espresso", "grinder"]) == '("home espresso" OR grinder)'
    assert core.build_query(["a", "b"], "lang:en") == "(a OR b) lang:en"


def test_blank_terms_rejected():
    with pytest.raises(ValueError):
        core.build_query(["  "])


def test_day_before_edge_post_dropped():
    edge = post("1", "Wed Oct 07 23:19:00 +0000 2026")
    ok = post("2", "Thu Oct 08 00:01:00 +0000 2026")
    kept, dropped = core.clean([edge, ok], "2026-10-08")
    assert [p["id"] for p in kept] == ["2"] and dropped == ["1"]


def test_edge_post_with_offset_uses_utc_day():
    # 01:30 at +03:00 is 22:30 UTC on the previous day
    assert not core.in_window(post("1", "2026-10-08T01:30:00+03:00"), "2026-10-08")


def test_end_date_and_dedupe_and_order():
    ps = [post("1", "2026-10-09T10:00:00Z"), post("2", "2026-10-11T10:00:00Z"), post("1", "2026-10-09T10:00:00Z"),
          post("3", "2026-10-10T10:00:00Z")]
    kept, dropped = core.clean(ps, "2026-10-08", "2026-10-10")
    assert [p["id"] for p in kept] == ["3", "1"] and dropped == ["2"]


def test_row_public_masks_handles_vendors_and_dashes():
    p = post("42", "2026-10-09T10:00:00Z", user="jane", text="@bob tried apify \u2014 nice https://t.co/abc")
    r = core.row(p)
    assert r["author"] == "a user" and r["link"] == "https://x.com/i/status/42"
    assert r["text"] == "@user tried [tool], nice"
    assert r["date"] == "2026-10-09 10:00 UTC" and (r["likes"], r["reposts"], r["replies"]) == (1, 2, 3)


def test_org_named():
    assert core.author_label(post("1", "", user="DesearchAI"), ["@desearchai"]) == "DesearchAI"


def test_csv_columns():
    out = core.to_csv([core.row(post("1", "2026-10-09T10:00:00Z", text='a, "b"\nc'))])
    rows = list(csv.DictReader(io.StringIO(out)))
    assert list(rows[0]) == core.COLUMNS and rows[0]["text"] == 'a, "b" c'


def test_cost_header():
    assert core.cost_of({"X-Desearch-Cost-Usd": "0.0015"}) == (0.0015, "header")
    assert core.cost_of({}) == (0.0, "none")


def test_client_refuses_to_write_key(tmp_path):
    c = tweets_csv.Client("SECRETKEY123", tmp_path)
    with pytest.raises(RuntimeError):
        c._save(tmp_path / "x.json", {"leak": "SECRETKEY123"})


def test_main_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("DESEARCH_API_KEY", "k")
    monkeypatch.delenv("DESEARCH_API_KEY_FILE", raising=False)
    import datetime as dt
    today = dt.datetime.now(dt.timezone.utc).date()
    good = post("9", today.isoformat() + "T08:00:00Z", user="x", text="espresso @y")
    old = post("8", (today - dt.timedelta(days=8)).isoformat() + "T23:50:00Z")
    monkeypatch.setattr(tweets_csv.Client, "get", lambda self, path, p, tag: (200, [good, old]))
    tweets_csv.main(["espresso", "--days", "7", "--out", str(tmp_path)])
    run = next(tmp_path.iterdir())
    snap = json.loads((run / "snapshot.json").read_text())
    assert snap["returned"] == 2 and snap["kept"] == 1 and snap["dropped_outside_window"] == ["8"]
    assert "@user" in (run / "posts.csv").read_text()
