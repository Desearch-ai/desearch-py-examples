import datetime as dt
import pytest
import core
import find_hashtags

NOW = dt.datetime(2026, 10, 16, 12, 0, tzinfo=dt.timezone.utc)


def post(i, minutes_ago, user="u1", likes=0, tags=(), text="hi", rt=False):
    t = (NOW - dt.timedelta(minutes=minutes_ago)).strftime(core.X_TIME)
    return {"id": str(i), "created_at": t, "user": {"id": user}, "like_count": likes, "lang": "en",
            "text": text, "is_retweet": rt, "entities": {"hashtags": [{"text": x} for x in tags]}}


def test_is_hashtag():
    assert core.is_hashtag("#Abc") and not core.is_hashtag("Abc") and not core.is_hashtag("#") and not core.is_hashtag("$FTR")


def test_hashtags_by_country_and_merge():
    us = {"trends": [{"name": "Tesla", "rank": 1}, {"name": "#Foo", "rank": 3}, {"name": "#Bar", "rank": 9}]}
    gb = {"trends": [{"name": "#foo", "rank": 2}]}
    by, counts = core.hashtags_by_country({"US": us, "GB": gb, "XX": {"detail": "err"}})
    assert counts == {"US": (2, 3), "GB": (1, 1), "XX": (0, 0)}
    rows = core.merge_countries(by)
    assert rows[0]["hashtag"] == "#Foo" and rows[0]["countries"] == {"US": 3, "GB": 2} and rows[0]["best_rank"] == 2
    assert rows[1]["hashtag"] == "#Bar"


def test_build_query_parentheses():
    assert core.build_query(["#a"]) == "#a"
    assert core.build_query(["#a", "#b"]) == "(#a OR #b)"
    with pytest.raises(ValueError):
        core.build_query([])


def test_keep_after_drops_edge_posts():
    posts = [post(1, 10), post(2, 200), {"id": "3", "created_at": "bad"}]
    kept, dropped = core.keep_after(posts, NOW - dt.timedelta(hours=2))
    assert [p["id"] for p in kept] == ["1"] and dropped == 2


def test_post_stats():
    ps = [post(1, 10, "a", 4, ["Foo", "Other"]), post(2, 70, "b", 2, ["Other"]), post(3, 130, "c", 0)]
    s = core.post_stats("#Foo", ps, NOW)
    assert s["sample"] == 3 and s["authors"] == 3 and s["newest_min"] == 10 and s["oldest_min"] == 130
    assert s["posts_per_hour"] == 1.5 and s["median_likes"] == 2 and s["co_hashtags"] == ["#Other"]
    assert s["examples"] == ["https://x.com/i/status/1", "https://x.com/i/status/2"]
    assert core.post_stats("#x", [], NOW)["sample"] == 0


def test_verdicts():
    row1 = {"countries": {"US": 1}}
    row2 = {"countries": {"US": 1, "GB": 4}}
    good = core.post_stats("#Foo", [post(1, 5, "a"), post(2, 6, "b")], NOW)
    assert core.verdict(row2, good).startswith("use: trending in several")
    assert core.verdict(row1, good) == "use: local"
    assert core.verdict(row1, core.post_stats("#F", [post(1, 5, "a", text="giveaway"), post(2, 6, "b", text="airdrop")], NOW)).startswith("skip (looks")
    assert core.verdict(row1, core.post_stats("#F", [post(i, 5, "a") for i in range(4)], NOW)).startswith("skip (few")
    assert core.verdict(row1, core.post_stats("#F", [post(1, 300, "a")], NOW)).startswith("cooling")
    assert core.verdict(row1, None) == "no recent posts found"


def test_render_md_no_handles():
    rows = [{"hashtag": "#Foo", "countries": {"US": 3}, "best_rank": 3}]
    s = core.post_stats("#Foo", [post(1, 5, "a")], NOW)
    md = core.render_md(rows, {"#foo": s}, {"US": (1, 30)}, "2026-10-16")
    assert "#Foo" in md and "use: local" in md and "x.com/" not in md.split("Shortlist")[1].split("|")[0]


def test_parse_woeids():
    assert find_hashtags.parse_countries("US=23424977,GB=23424975") == [("US", 23424977), ("GB", 23424975)]
    assert find_hashtags.parse_countries("1") == [("1", 1)]


def test_client_refuses_key(tmp_path):
    c = find_hashtags.Client("SECRETKEY123", tmp_path)
    with pytest.raises(RuntimeError):
        c._save(tmp_path / "x.json", {"a": "SECRETKEY123"})
