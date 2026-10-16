import json, pathlib
import core, swipe


def P(i, text="Introducing X", likes=100, created="Tue Oct 13 10:00:00 +0000 2026", media=("video",), user="someone"):
    return {"id": str(i), "text": text, "like_count": likes, "created_at": created,
            "media": [{"type": t} for t in media], "user": {"username": user}}


def test_query_groups_in_parentheses():
    q = core.build_query(["iOS app", "mobile app"])
    assert q == '(launch OR launching OR introducing OR demo) ("iOS app" OR "mobile app")'


def test_in_window_drops_day_before_edge_post():
    assert not core.in_window(P(1, created="Sun Sep 13 23:19:01 +0000 2026"), "2026-09-14")
    assert core.in_window(P(1, created="Mon Sep 14 00:00:01 +0000 2026"), "2026-09-14")


def test_has_video():
    assert core.has_video(P(1)) and core.has_video(P(1, media=("animated_gif",)))
    assert not core.has_video(P(1, media=("photo",))) and not core.has_video(P(1, media=()))


def test_select_filters_and_one_per_author():
    ps = [P(1, likes=10), P(2, likes=500, user="a"), P(3, likes=400, user="a"), P(4, media=("photo",)),
          P(5, created="Sun Sep 13 23:00:00 +0000 2026"), P(6, likes=60, user="b")]
    assert [p["id"] for p in core.select(ps, "2026-09-14", 50)] == ["2", "6"]


def test_openings():
    assert core.opening(P(1, "Before: 3 apps. After: one.")) == "before/after"
    assert core.opening(P(1, "Tired of losing your notes?")) == "problem-first"
    assert core.opening(P(1, "I built my first app in 6 weeks")) == "founder talking"
    assert core.opening(P(1, "Here's how it works 👇 demo")) == "demo-first"
    assert core.opening(P(1, "Introducing Moto, live today")) == "announcement"
    assert core.opening(P(1, "gm")) == "other"


def test_public_labels_and_masking():
    assert core.author_label(P(1, user="jane")) == "a creator"
    assert core.author_label(P(1, user="AcmeApp"), ["acmeapp"]) == "AcmeApp"
    assert core.status_url("9") == "https://x.com/i/status/9"
    assert core.scrub("hi @jane https://t.co/abc") == "hi @user"
    assert core.mask("Built with Claude 4 \u2014 fast") == "Built with [tool], fast"


def test_cost_header_wins_and_calculation_is_labelled():
    assert core.cost_of({"X-Desearch-Cost-Usd": "0.0015"}, 3) == (0.0015, "header")
    assert core.cost_of({}, 3) == (0.0015, "calculated")
    assert core.cost_of({}) == (0.0, "none")


def test_csv_has_no_views_and_md_has_no_banned_words():
    p = P(1, "Introducing Moto @jane")
    p["view_count"] = 99999
    rs = core.rows([p])
    csv_text = core.to_csv(rs)
    assert "view" not in csv_text.lower() and "99999" not in csv_text and "@jane" not in csv_text
    md = core.swipe_md("apps", "(a OR b) (c)", "2026-09-14", 50, [p], "2026-10-14 09:31 +04").lower()
    for bad in ("viral", "real-time", "every mention", "unreliable", "\u2014", "view"):
        assert bad not in md


def test_client_refuses_to_write_key(tmp_path):
    c = swipe.Client("sk-secret-123", tmp_path)
    try:
        c._save(tmp_path / "x.json", {"a": "sk-secret-123"})
        assert False
    except RuntimeError:
        pass
