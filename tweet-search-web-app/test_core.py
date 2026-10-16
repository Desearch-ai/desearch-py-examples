import datetime as dt, pathlib, pytest
import core, app

TODAY = dt.date(2026, 10, 16)
POST = {"id": "1", "text": "hello\n @someone world", "created_at": "Fri Oct 16 10:33:22 +0000 2026", "lang": "en",
        "like_count": 5, "reply_count": 1, "retweet_count": 0, "user": {"verified": False, "is_blue_verified": True, "username": "someone"},
        "media": [{"type": "photo"}]}


def test_or_terms_are_parenthesized():
    assert core.build_query(["a"]) == "a"
    assert core.build_query(["a", " b "]) == "(a OR b)"
    assert core.validate({"q": "desearch", "any": "api, sdk"}, TODAY)["query"] == "desearch (api OR sdk)"


@pytest.mark.parametrize("form,msg", [
    ({"q": "  "}, "search term"), ({"q": "x", "count": "0"}, "Count"), ({"q": "x", "count": "101"}, "Count"),
    ({"q": "x", "sort": "New"}, "Sort"), ({"q": "x", "min_likes": "-1"}, "whole"), ({"q": "x", "lang": "english"}, "Language"),
    ({"q": "x", "start_date": "2026-10-10", "end_date": "2026-10-01"}, "before"),
    ({"q": "x", "start_date": "2026-13-01"}, "real date"), ({"q": "x", "start_date": "2026-10-20"}, "future")])
def test_bad_input_never_reaches_api(form, msg):
    with pytest.raises(core.FormError, match=msg):
        core.validate(form, TODAY)


def test_params_map_filters():
    p = core.validate({"q": "x", "sort": "Top", "count": "50", "lang": "EN", "min_likes": "10", "min_replies": "0",
                       "is_video": "on", "verified": "", "start_date": "2026-10-10", "end_date": "2026-10-16"}, TODAY)
    assert p == {"query": "x", "sort": "Top", "count": 50, "lang": "en", "min_likes": 10, "is_video": "true",
                 "start_date": "2026-10-10", "end_date": "2026-10-16"}
    assert "exclude_domains" not in p


def test_row_has_no_handle_and_neutral_link():
    r = core.row(POST)
    assert r["link"] == "https://x.com/i/status/1" and "someone" not in str(r)
    assert r["text"] == "hello @user world" and r["image"] and not r["video"] and r["blue"]


def test_check_filters_counts_violations():
    rows = [core.row(POST), core.row({**POST, "like_count": 50, "lang": "es", "media": [{"type": "video"}]})]
    v = core.check_filters({"min_likes": 10, "lang": "en", "is_video": "true", "start_date": "2026-10-17"}, rows)
    assert v == {"min_likes": 1, "is_video": 1, "lang": 1, "date": 2}


def test_csv_and_html_escape():
    out = core.to_csv([core.row({**POST, "text": "a,<b>"})])
    assert out.splitlines()[0].startswith("created_utc,text") and '"a,<b>"' in out
    page = core.render_page({"q": "<x>"}, [core.row({**POST, "text": "<script>"})])
    assert "<script>" not in page.split("</style>")[1] and "&lt;x&gt;" in page


def test_posts_of_shapes():
    assert core.posts_of([POST, "x"]) == [POST] and core.posts_of({"data": [POST]}) == [POST] and core.posts_of("err") == []


def test_client_refuses_to_write_key(tmp_path):
    c = app.Client("SECRETKEY123", tmp_path)
    with pytest.raises(RuntimeError):
        c._write(tmp_path / "f.json", "contains SECRETKEY123")
