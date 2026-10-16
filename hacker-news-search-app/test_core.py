import json, pathlib, re
import pytest
import core, app

HERE = pathlib.Path(__file__).parent


def it(url, title="T | Hacker News", **kw):
    return {"link": url, "title": title, "snippet": "s", "highlights": ["h1", " h2 "], **kw}


def test_clean_query_collapses_space():
    assert core.clean_query("  rust   async ") == "rust async"


@pytest.mark.parametrize("bad", ["", "   ", None, "x" * 301, "(a OR b"])
def test_clean_query_rejects(bad):
    with pytest.raises(core.FormError):
        core.clean_query(bad)


def test_or_query_groups_in_parentheses():
    assert core.or_query(["sqlite", " duckdb "]) == "(sqlite OR duckdb)"
    assert core.or_query(["one"]) == "one"
    with pytest.raises(core.FormError):
        core.or_query(["", " "])


@pytest.mark.parametrize("v,exp", [(None, 10), ("", 10), ("20", 20), (30, 30)])
def test_count_ok(v, exp):
    assert core.count_value(v) == exp


@pytest.mark.parametrize("v", ["5", "11", "200", "x", "-10"])
def test_count_bad(v):
    with pytest.raises(core.FormError):
        core.count_value(v)


def test_date_value():
    assert core.date_value("past_year") == "PAST_YEAR"
    assert core.date_value(None) == ""
    with pytest.raises(core.FormError):
        core.date_value("PAST_24_HOURS")


def test_body_shape():
    b = core.body("q", 20, "PAST_WEEK")
    assert b == {"prompt": "q", "tools": ["hackernews"], "streaming": False, "result_type": "ONLY_LINKS",
                 "count": 20, "date_filter": "PAST_WEEK"}
    assert "date_filter" not in core.body("q")
    assert "exclude_domains" not in json.dumps(b)


@pytest.mark.parametrize("url,exp", [
    ("https://news.ycombinator.com/item?id=123", "123"),
    ("http://news.ycombinator.com/item?id=9&p=2", "9"),
    ("https://news.ycombinator.com/item?p=2&id=77", "77"),
    ("https://news.ycombinator.com/user?id=pg", None),
    ("https://news.ycombinator.com/item?id=12x", None),
    ("https://example.com/item?id=1", None),
    ("", None)])
def test_item_id(url, exp):
    assert core.item_id(url) == exp


@pytest.mark.parametrize("t,exp", [("A | Hacker News", "A"), ("Long comment... | Hack", "Long comment..."),
                                   ("x | Hacker N", "x"), ("A | B", "A | B"), ("Plain", "Plain")])
def test_strip_suffix(t, exp):
    assert core.strip_suffix(t) == exp


def test_raw_items_reads_any_list_field():
    resp = {"search": [it("https://news.ycombinator.com/item?id=1"), "junk", {"title": "no link"}],
            "hacker_news_search": [it("https://news.ycombinator.com/item?id=2")], "completion": "x", "cost_usd": 0.004}
    assert len(core.raw_items(resp)) == 2
    assert core.raw_items("text") == [] and core.raw_items(None) == []


def test_filter_keeps_items_dedupes_and_counts():
    items = [it("https://news.ycombinator.com/item?id=5"), it("https://news.ycombinator.com/item?id=5&p=2"),
             it("https://news.ycombinator.com/user?id=x"), it("https://example.com/a"), it("https://news.ycombinator.com/item?id=6")]
    res, st = core.filter_items(items)
    assert [r["item_id"] for r in res] == ["5", "6"]
    assert [r["rank"] for r in res] == [1, 2]
    assert res[0]["url"] == "https://news.ycombinator.com/item?id=5"
    assert res[0]["title"] == "T" and res[0]["highlights"] == ["h1", "h2"]
    assert st == {"returned": 5, "kept": 2, "non_item_links": 2, "duplicates": 1}


def test_csv_export():
    res, _ = core.filter_items([it("https://news.ycombinator.com/item?id=5", highlights=["a", "b", "c", "d"])])
    rows = core.to_csv(res).splitlines()
    assert rows[0] == ",".join(core.FIELDS)
    assert rows[1].endswith("a | b | c")


def test_html_escapes_and_empty():
    page = core.render_page({"q": "<x>"}, [], {"kept": 0, "returned": 0, "cached": False, "cost_usd": 0.004, "q": "<x>", "count": 10}, None)
    assert "<x>" not in page and "&lt;x&gt;" in page and "No Hacker News items returned." in page
    assert "class=err" in core.render_page({}, error="bad")


class FakeClient:
    def __init__(self, resp, status=200):
        self.resp, self.status, self.calls = resp, status, []

    def search(self, payload, tag="search"):
        self.calls.append(payload)
        return self.status, self.resp, {"cost": 0.004, "latency_s": 1.0}


def test_service_cache_and_ttl():
    now = [0.0]
    fc = FakeClient({"search": [it("https://news.ycombinator.com/item?id=1")]})
    svc = app.HNSearch(fc, ttl=600, clock=lambda: now[0])
    st, out = svc.search("q", 10)
    assert st == 200 and out["kept"] == 1 and not out["cached"]
    st, out = svc.search("q", 10)
    assert out["cached"] and len(fc.calls) == 1
    now[0] = 601
    svc.search("q", 10)
    assert len(fc.calls) == 2


def test_service_error_passthrough():
    st, out = app.HNSearch(FakeClient({"detail": "nope"}, 401)).search("q")
    assert st == 401 and out["error"] == "nope"


def test_invalid_input_makes_no_call():
    fc = FakeClient({})
    with pytest.raises(core.FormError):
        q, c, d = app.parse({"q": " ", "count": "10"})
        app.HNSearch(fc).search(q, c, d)
    assert fc.calls == []


def test_client_refuses_to_log_key(tmp_path):
    c = app.Client("SECRETKEY123", tmp_path)
    with pytest.raises(RuntimeError):
        c._write(tmp_path / "x.json", "has SECRETKEY123 inside")


def test_api_key_prefers_file(tmp_path, monkeypatch):
    f = tmp_path / "k"
    f.write_text(" filekey \n")
    monkeypatch.setenv("DESEARCH_API_KEY", "envkey")
    monkeypatch.setenv("DESEARCH_API_KEY_FILE", str(f))
    assert app.api_key() == "filekey"
    monkeypatch.delenv("DESEARCH_API_KEY_FILE")
    assert app.api_key() == "envkey"


BANNED = re.compile(r"\u2014|real-time|unreliable|every mention|viral", re.I)


def own_prose(text):
    """Our own words only: drops fenced blocks (quoted API output) from a markdown file."""
    return re.sub(r"```.*?```", "", text, flags=re.S)


@pytest.mark.parametrize("name", ["README.md", "sample-output.md"])
def test_public_copy_rules(name):
    assert not BANNED.search(own_prose((HERE / name).read_text()))
