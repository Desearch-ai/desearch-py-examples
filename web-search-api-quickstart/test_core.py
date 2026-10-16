import json, pytest
import core, app


def test_clean_query_ok():
    assert core.clean_query("  web   search\napi ") == "web search api"


@pytest.mark.parametrize("bad", ["", "   ", None, "x" * 301])
def test_clean_query_rejects(bad):
    with pytest.raises(core.FormError):
        core.clean_query(bad)


@pytest.mark.parametrize("v,ok", [("", 1), ("2", 2), ("3", 3)])
def test_pages_ok(v, ok):
    assert core.pages_value(v) == ok


@pytest.mark.parametrize("bad", ["0", "4", "-1", "abc", "1.5"])
def test_pages_bad(bad):
    with pytest.raises(core.FormError):
        core.pages_value(bad)


def test_starts_step_20():
    assert core.starts(3) == [0, 20, 40]


def test_params_no_exclude_domains():
    p = core.params("q", 20)
    assert p == {"query": "q", "start": 20} and "exclude_domains" not in p


def test_domain_and_norm():
    assert core.domain_of("https://WWW.Example.com/a/") == "example.com"
    assert core.norm_url("https://www.example.com/a/#x") == core.norm_url("http://example.com/a")


def test_normalize_shape():
    r = core.normalize({"title": " A \n B ", "link": "https://docs.desearch.ai/x", "snippet": "s"})
    assert r == {"title": "A B", "url": "https://docs.desearch.ai/x", "snippet": "s", "domain": "docs.desearch.ai"}


def test_items_of_tolerant():
    assert core.items_of({"data": [{"a": 1}, "x"]}) == [{"a": 1}]
    assert core.items_of("oops") == [] and core.items_of({"data": None}) == []


def test_merge_dedupes_and_ranks():
    p1 = [{"link": "https://a.com/1"}, {"link": "https://b.com/"}, {"link": ""}]
    p2 = [{"link": "https://www.a.com/1/"}, {"link": "https://c.com"}]
    res, per, rep = core.merge([p1, p2])
    assert [r["url"] for r in res] == ["https://a.com/1", "https://b.com/", "https://c.com"]
    assert [r["rank"] for r in res] == [1, 2, 3] and per == [2, 1] and rep == 1


def test_cache_ttl():
    t = [0.0]
    c = core.TTLCache(ttl=600, clock=lambda: t[0])
    c.put("k", 1)
    t[0] = 599
    assert c.get("k") == 1
    t[0] = 600
    assert c.get("k") is None


def test_cache_evicts_oldest():
    t = [0.0]
    c = core.TTLCache(clock=lambda: t[0], max_items=2)
    for k in "abc":
        c.put(k, k); t[0] += 1
    assert c.get("a") is None and c.get("c") == "c"


def test_render_escapes():
    h = core.render_page({"q": "<x>"}, [{"url": "https://a.com", "title": "<b>", "snippet": "", "domain": "a.com"}],
                         {"count": 1, "cached": False, "calls": 1, "json_href": "/search?q=x"})
    assert "&lt;b&gt;" in h
    assert "&lt;x&gt;" in h


class FakeClient:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def web(self, params, tag="web"):
        self.calls.append(params)
        items = self.pages[len(self.calls) - 1]
        return 200, {"data": items}, {"billing_headers": {"x-desearch-cost-usd": "0.001"}, "latency_s": 1.0}


def test_service_cache_hit_makes_no_call():
    fc = FakeClient([[{"link": "https://a.com", "title": "A"}]])
    svc = app.SearchService(fc)
    st, out = svc.search("q", 1)
    assert st == 200 and out["calls"] == 1 and not out["cached"] and out["cost_usd"] == 0.001
    st, out2 = svc.search("Q", 1)
    assert out2["cached"] and out2["calls"] == 0 and len(fc.calls) == 1


def test_service_stops_on_empty_page():
    fc = FakeClient([[{"link": "https://a.com"}], [], [{"link": "https://z.com"}]])
    st, out = app.SearchService(fc).search("q", 3)
    assert [c["start"] for c in fc.calls] == [0, 20] and out["count"] == 1


def test_client_refuses_to_write_key(tmp_path):
    c = app.Client("SECRETKEY123", tmp_path)
    with pytest.raises(RuntimeError):
        c._write(tmp_path / "x.json", json.dumps({"k": "SECRETKEY123"}))


def test_cli_rejects_blank_without_key(monkeypatch):
    monkeypatch.delenv("DESEARCH_API_KEY", raising=False)
    monkeypatch.delenv("DESEARCH_API_KEY_FILE", raising=False)
    assert app.main(["--cli", "   "]) == 2
    assert app.main(["--cli", "ok", "--pages", "9"]) == 2


def test_key_file_wins(tmp_path, monkeypatch):
    f = tmp_path / "k"; f.write_text("FILEKEY\n")
    monkeypatch.setenv("DESEARCH_API_KEY", "ENVKEY")
    assert app.api_key(str(f)) == "FILEKEY"
