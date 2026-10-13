import datetime as dt
import replyledger as r

H = "acme"
def tw(i, user=H, to=None, rt=False, likes=0, replies=0, conv=None, day="Wed Oct 01 16:36:07 +0000 2026", views=None):
    return {"id": str(i), "user": {"username": user}, "in_reply_to_status_id": "p%s" % i if to else None,
            "in_reply_to_screen_name": to, "is_retweet": rt, "like_count": likes, "reply_count": replies,
            "retweet_count": 0, "quote_count": 0, "bookmark_count": 1, "view_count": views,
            "conversation_id": conv or str(i), "created_at": day, "text": "t%s" % i, "url": "u%s" % i}

def test_kind():
    assert r.kind(tw(1), H) == "original"
    assert r.kind(tw(2, rt=True), H) == "retweet"
    assert r.kind(tw(3, to="ACME"), H) == "self_reply"
    assert r.kind(tw(4, to="bob"), H) == "reply"

def test_engagement():
    assert r.engagement(tw(1, likes=3, replies=2)) == 3 + 4 + 1

def test_merge_dedupes_and_own_only():
    a = [tw(1), tw(2)]; b = [tw(2), tw(3, user="other")]
    m = r.merge(a, b)
    assert [t["id"] for t in m] == ["1", "2", "3"]
    assert [t["id"] for t in r.own_only(m, "ACME")] == ["1", "2"]

def test_window_and_parse():
    old = tw(1, day="Sat May 05 22:24:49 +0000 2018"); new = tw(2)
    since = dt.datetime(2026, 9, 7, tzinfo=dt.timezone.utc)
    assert r.in_window([old, new, {"id": "x"}], since) == [new]
    assert r.parse_time("garbage") is None

def test_targets_volume_fill():
    reps = [tw(1, to="bob", likes=10), tw(2, to="bob"), tw(3, to="amy", views=5)]
    t = r.top_targets(reps)
    assert t[0]["account"] == "bob" and t[0]["replies"] == 2
    v = r.volume_by_day(reps + [tw(4)], H)
    assert v["2026-10-01"]["reply"] == 3 and v["2026-10-01"]["original"] == 1
    f = r.fill_rates(reps)
    assert f["view_count"] == {"n": 3, "present": 1, "nonzero": 1}

def test_notable_threads():
    busy = tw(1, replies=50); answered = tw(2, replies=80); my_reply = tw(3, to="bob", conv="2")
    out = r.notable_threads([busy, answered, my_reply, tw(4, replies=0)], H)
    assert [t["id"] for t in out] == ["1"]

def test_render_and_cost():
    calls = [{"cost_usd": 0.003, "units": 20}, {"cost_usd": None, "units": None}]
    assert r.cost_line(calls).startswith("2 Desearch calls, 20 billed units, $0.00300")
    md = r.render(H, dt.datetime(2026, 9, 7, tzinfo=dt.timezone.utc), [tw(1, to="bob", likes=5), tw(2)], calls, {}, "now")
    assert "@bob" in md and "## Cost" in md and "\u2014" not in md
    assert "(no replies" in r.render(H, dt.datetime(2026, 9, 7, tzinfo=dt.timezone.utc), [], [], {}, "now")
