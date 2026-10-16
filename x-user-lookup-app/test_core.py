import json, pathlib, pytest, core, app


def tw(i, day, likes=0, **k):
    return {"id": i, "created_at": f"Thu Oct {day:02d} 10:00:00 +0000 2026", "like_count": likes, "text": "hi @someone", **k}


@pytest.mark.parametrize("raw,want", [("desearch_ai", "desearch_ai"), ("@desearch_ai", "desearch_ai"),
                                      ("https://x.com/desearch_ai", "desearch_ai"), ("twitter.com/desearch_ai/", "desearch_ai")])
def test_clean_username_ok(raw, want):
    assert core.clean_username(raw) == want


@pytest.mark.parametrize("raw", ["", "   ", "@", "has space", "a" * 16, "bad-dash", "x.com/"])
def test_clean_username_rejects(raw):
    with pytest.raises(core.FormError):
        core.clean_username(raw)


def test_pages_value():
    assert core.pages_value("") == 3 and core.pages_value("1") == 1
    for bad in ("0", "4", "-1", "x"):
        with pytest.raises(core.FormError):
            core.pages_value(bad)


def test_params_no_extras():
    assert core.params("a") == {"username": "a"}
    assert core.params("a", "c1") == {"username": "a", "cursor": "c1"}
    assert "exclude_domains" not in core.params("a", "c")


def test_should_follow_stops():
    assert core.should_follow({"next_cursor": "c1"}, set(), 1, 3) == "c1"
    assert core.should_follow({"next_cursor": "c1"}, {"c1"}, 1, 3) is None
    assert core.should_follow({"next_cursor": None}, set(), 1, 3) is None
    assert core.should_follow({"next_cursor": "c2"}, set(), 3, 3) is None


def test_merge_dedupes_and_masks():
    rows, rep = core.merge([[tw(1, 15), tw(2, 14)], [tw(2, 14), tw(3, 13)]])
    assert [r["id"] for r in rows] == ["1", "2", "3"] and rep == 1
    assert rows[0]["text"] == "hi @user" and rows[0]["link"] == "https://x.com/i/status/1"
    assert rows[2]["page"] == 2


def test_kind():
    assert core.row(tw(1, 1, is_retweet=True), 1)["kind"] == "repost"
    assert core.row(tw(1, 1, in_reply_to_status_id="9"), 1)["kind"] == "reply"
    assert core.row(tw(1, 1), 1)["kind"] == "post"


def test_stats_and_order():
    rows, _ = core.merge([[tw(1, 15, 10), tw(2, 11, 2), tw(3, 13, 4)]])
    s = core.stats(rows)
    assert s["posts"] == 3 and s["median_likes"] == 4 and s["per_day"] == 0.75
    assert core.out_of_order(rows) == 1
    assert core.stats([])["posts"] == 0


def test_profile_missing():
    assert core.profile({}, "nobody")["found"] is False
    p = core.profile({"user": {"username": "desearch_ai", "followers_count": 5, "created_at": "Tue Jan 14 20:08:24 +0000 2025"}}, "x")
    assert p["found"] and p["created"] == "2025-01-14"


def test_csv_and_html_escape():
    rows, _ = core.merge([[tw(1, 1, text="<b>x</b>")]])
    assert core.to_csv(rows).splitlines()[0] == ",".join(core.CSV_FIELDS)
    page = core.render_page({"username": "<x>"}, rows=rows)
    assert "<b>x</b>" not in page and "&lt;x&gt;" in page


class FakeClient:
    def __init__(self, bodies):
        self.bodies, self.calls = bodies, []

    def user_posts(self, p, tag):
        self.calls.append(p)
        return 200, self.bodies[len(self.calls) - 1], {}


def test_lookup_follows_cursor_and_stops_on_repeat():
    b = [{"user": {"username": "o"}, "tweets": [tw(1, 3)], "next_cursor": "c1"},
         {"tweets": [tw(1, 3), tw(2, 2)], "next_cursor": "c1"}]
    c = FakeClient(b)
    st, prof, rows, s, info = app.lookup(c, "o", 3)
    assert len(c.calls) == 2 and c.calls[1]["cursor"] == "c1"
    assert info["repeats"] == 1 and len(rows) == 2


def test_client_refuses_key_in_file(tmp_path):
    c = app.Client("SECRETKEY123", tmp_path)
    with pytest.raises(RuntimeError):
        c._write(tmp_path / "x", "Authorization: SECRETKEY123")
