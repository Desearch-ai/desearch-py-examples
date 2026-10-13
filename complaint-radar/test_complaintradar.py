"""Offline tests for the pure logic in complaintradar.py (no API calls)."""
import datetime as dt
import complaintradar as cr


def tw(i, text, created="Thu Oct 08 04:15:08 +0000 2026", user="someone", **kw):
    t = {"id": str(i), "text": text, "created_at": created, "user": {"username": user}, "url": f"https://x.com/{user}/status/{i}"}
    t.update(kw)
    return t


def test_build_query_quotes_phrases_and_excludes():
    q = cr.build_query("Spotify", [], ["not working", "refund"], handle="@SpotifyCares", exclude=["streams"])
    assert q == 'Spotify ("not working" OR refund) -from:SpotifyCares -streams'
    q2 = cr.build_query("PlayStation", ["PSN"], ["down"])
    assert q2 == "(PlayStation OR PSN) (down)"


def test_day_windows_are_utc_midnights_oldest_first():
    now = dt.datetime(2026, 10, 8, 5, 30, tzinfo=dt.timezone.utc)
    w = cr.day_windows(3, now)
    assert [d for d, _, _ in w] == ["2026-10-06", "2026-10-07", "2026-10-08"]
    assert w[0][1:] == ("2026-10-06T00:00:00Z", "2026-10-07T00:00:00Z")
    assert w[-1][2] == "2026-10-09T00:00:00Z"


def test_next_page_query_uses_oldest_id_minus_one_and_replaces_old_max_id():
    q = cr.next_page_query("Spotify broken max_id:5", [tw(30, "a"), tw(12, "b"), tw(20, "c")])
    assert q == "Spotify broken max_id:11"
    assert cr.next_page_query("x", []) is None


def test_parse_time_both_formats():
    assert cr.parse_time("Thu Oct 08 04:15:08 +0000 2026") == dt.datetime(2026, 10, 8, 4, 15, 8, tzinfo=dt.timezone.utc)
    assert cr.parse_time("2026-10-08T04:15:08Z").hour == 4
    assert cr.parse_time("nope") is None and cr.parse_time(None) is None


def test_theme_rules_order_and_idioms():
    assert cr.theme_of("Spotify is down again")[0] == "outage"
    assert cr.theme_of("can't log in to PSN since this morning")[0] == "account"
    assert cr.theme_of("still waiting on my refund")[0] == "billing"
    assert cr.theme_of("the app keeps crashing on my phone")[0] == "bug"
    assert cr.theme_of("customer service never answered")[0] == "support"
    assert cr.theme_of("please add a sleep timer")[0] == "feature request"
    assert cr.theme_of("this album has broken the record again")[0] == "other"
    assert cr.theme_of("Patch 4: bug fixes and more")[0] == "other"
    assert cr.theme_of("lovely day")[0] == "other"


def test_dedupe_ids_and_copy_paste_texts():
    a = tw(1, "Spotify is down for everyone right now @a https://t.co/x")
    b = tw(1, "same id again")
    c = tw(2, "Spotify is down for everyone right now @b https://t.co/y")
    d = tw(3, "short")
    e = tw(4, "short")
    kept, d_id, d_txt = cr.dedupe([a, b, c, d, e])
    assert [t["id"] for t in kept] == ["1", "3", "4"]
    assert (d_id, d_txt) == (1, 1)


def test_keep_post_drops_reposts_and_brand_handle():
    assert not cr.keep_post(tw(1, "x", is_retweet=True))
    assert not cr.keep_post(tw(2, "x", user="SpotifyCares"), "@spotifycares")
    assert cr.keep_post(tw(3, "x"), "SpotifyCares")


def test_engagement_and_top_complaints():
    rows = [cr.to_row(tw(1, "Spotify is down", like_count=5, reply_count=2)),
            cr.to_row(tw(2, "nice playlist", like_count=500)),
            cr.to_row(tw(3, "refund please", like_count=1, reply_count=0, bookmark_count=1))]
    assert rows[0]["score"] == 9
    top = cr.top_complaints(rows, 5)
    assert [r["id"] for r in top] == ["1", "3"]          # 'other' is not ranked
    assert [r["id"] for r in cr.top_complaints(rows, 5, with_replies=True)] == ["1"]


def test_volume_by_day_and_fill_rates():
    rows = [cr.to_row(tw(1, "down", "Tue Oct 06 10:00:00 +0000 2026")), cr.to_row(tw(2, "refund")), cr.to_row(tw(3, "bug"))]
    v = cr.volume_by_day(rows)
    assert list(v) == ["2026-10-06", "2026-10-08"]
    assert v["2026-10-08"]["billing"] == 1 and v["2026-10-08"]["bug"] == 1
    f = cr.fill_rates([tw(1, "a", view_count=3), tw(2, "b", view_count=None)], fields=("view_count", "text"))
    assert f == {"view_count": (1, 2), "text": (2, 2)}


def test_render_has_sections_and_cost_line():
    rows = [cr.to_row(tw(1, "Spotify is down", like_count=3))]
    meta = {"brand": "Spotify", "handle": "SpotifyCares", "query": "q", "lang": None, "days": 1,
            "window": ("a", "b"), "generated": "now", "dropped_ids": 0, "dropped_texts": 0}
    calls = [{"status": 200, "cost_usd": 0.003, "units": 20}]
    md = cr.render(meta, rows, cr.volume_by_day(rows), calls, cr.fill_rates([]), 5, None,
                   {"2026-10-08": {"pages": 1, "fetched": 1, "oldest": "2026-10-08T04:15:08+00:00", "capped": False}})
    for s in ("## Themes", "## Volume by day (UTC)", "## Top 5 complaint posts", "## Cost", "$0.00300", "04:15 (whole day)"):
        assert s in md
