"""Offline tests (no key, no network): python3 -m pytest -q"""
import datetime as dt, io, json, os, pathlib, sys, urllib.request
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from searchapp import core, client as client_mod
from searchapp.client import Client
from searchapp.service import Engine, CACHE_HEADER, client_ip, parse_query

KEY = "dsk-test-SECRET-1234567890"
TODAY = dt.date(2026, 10, 19)


def res(url, title="T", date=None, hl=("passage",)):
    return {"url": url, "title": title, "published_date": date, "highlights": list(hl) if hl is not None else None}


def test_clean_query_rejects_bad_input():
    for bad in ("", "   ", "a", "x" * 301, "?!"):
        with pytest.raises(core.FormError):
            core.clean_query(bad)
    assert core.clean_query("  rate   limiting ") == "rate limiting"


def test_mode_and_count():
    assert core.parse_mode(None) == "fast" and core.parse_mode("Balanced") == "balanced"
    assert core.parse_count(None) == 10 and core.parse_count("20") == 20
    for bad in ("deep", "x"):
        with pytest.raises(core.FormError):
            core.parse_mode(bad)
    for bad in ("12", "abc", "0"):
        with pytest.raises(core.FormError):
            core.parse_count(bad)


def test_date_window_ranges():
    assert core.date_window(None, today=TODAY) == (None, None)
    assert core.date_window("any", today=TODAY) == (None, None)
    assert core.date_window("day", today=TODAY) == ("2026-10-18", None)
    assert core.date_window("week", today=TODAY) == ("2026-10-12", None)
    assert core.date_window("year", today=TODAY) == ("2025-10-19", None)
    assert core.date_window("custom", "2026-10-01", "2026-10-10", today=TODAY) == ("2026-10-01", "2026-10-10")
    assert core.date_window(None, "", "2026-10-10", today=TODAY) == (None, "2026-10-10")


def test_date_window_rejects():
    for args in (("fortnight", None, None), (None, "2026-10-18", "2026-10-01"), (None, "10/01/2026", None),
                 (None, "2026-02-30", None), ("week", "2026-10-01", None)):
        with pytest.raises(core.FormError):
            core.date_window(*args, today=TODAY)


def test_search_body():
    b = core.search_body("q x", "fast", 10, "2026-10-12", None)
    assert b == {"query": "q x", "mode": "fast", "count": 10, "highlights": True, "start_date": "2026-10-12"}
    assert set(b) == {"query", "mode", "count", "highlights", "start_date"}
    a = core.answer_body("q x")
    assert a["tools"] == ["web"] and a["streaming"] is False and a["result_type"] == "LINKS_WITH_FINAL_SUMMARY"


def test_clean_results_dates_dedupe_window():
    body = {"results": [res("https://www.a.org/x/", "A", "2026-10-15"), res("https://www.a.org/x", "A again", "2026-10-15"),
                        res("https://b.org/y", "B", None), res("https://c.org/z", "C", "2026-09-01T00:00:00Z"), {"title": "no url"}]}
    out, st = core.clean_results(body, "2026-10-12", None)
    assert [r["url"] for r in out] == ["https://www.a.org/x/", "https://b.org/y", "https://c.org/z"]
    assert out[0]["domain"] == "a.org" and out[0]["in_window"] is True
    assert out[1]["published_date"] is None and out[1]["in_window"] is None
    assert out[2]["published_date"] == "2026-09-01" and out[2]["in_window"] is False
    assert st == {"returned": 5, "shown": 3, "duplicates": 1, "no_date": 1, "outside_window": 1}


def test_passage_collapses_and_trims():
    assert core.passage(["  a\n\n b  "]) == "a b"
    assert core.passage(None) == "" and core.passage([]) == ""
    long = core.passage(["word " * 200])
    assert len(long) <= core.PASSAGE_CHARS + 4 and long.endswith(" ...")
    assert core.passage(["text,with no space"]) == "text,with no space"   # shown as returned


def test_citations_keep_only_own_links():
    links = ["https://a.org/x", "https://en.wikipedia.org/wiki/Science_(journal)"]
    comp = ("Uncited opener. Fact one [1](https://a.org/x). Fact two [2](https://made.up/page). "
            "Fact three [3](https://en.wikipedia.org/wiki/Science_%28journal%29).")
    r = core.check_citations(comp, links)
    assert [l["text"] for l in r["lines"]] == ["Fact one.", "Fact three."]
    assert r["hidden"] == 2


def test_build_answer_declined_template():
    body = {"search": [{"link": "https://a.org/py", "title": "Python 3.14 free threading benchmarks", "snippet": "performance"},
                       {"link": "https://b.org/py", "title": "Python 3.14 free threading performance", "snippet": ""}],
            "completion": "\n\nThe sources do not provide specific information. Closest on-topic source reviewed: [1](https://a.org/py)."}
    a = core.build_answer("python 3.14 free threading performance", body, ["https://a.org/py/", "https://z.org"])
    assert a["declined"] is True and a["summary"]["lines"] == []
    assert a["declined_text"] == "The sources do not provide specific information."
    assert a["strong"] == 2 and a["no_strong_sources"] is False and a["also_in_search_results"] == 1


def test_build_answer_no_strong_sources():
    body = {"search": [{"link": f"https://w{i}.org", "title": "Fever Cure game wiki", "snippet": ""} for i in range(5)],
            "completion": "Pages describe a game item [1](https://w0.org)."}
    a = core.build_answer("zorblaxian qwintel glorpton crystal fever cure", body)
    assert a["no_strong_sources"] is True and a["declined"] is False and len(a["summary"]["lines"]) == 1
    assert a["also_in_search_results"] is None


def test_cache_key_normalizes():
    k = lambda q: core.cache_key("search", q=q, mode="fast", count=10, start=None, end=None)
    assert k("Desearch search API!") == k("  desearch SEARCH api ")
    assert k("x y") != core.cache_key("search", q="x y", mode="balanced", count=10)
    assert core.cache_key("answer", q="x y") != k("x y")


def test_rate_limiter_and_cap():
    now = [1000.0]
    rl = core.RateLimiter(per_ip=2, per_ip_day=3, global_window=100, clock=lambda: now[0])
    assert rl.allow("a") and rl.allow("a") and not rl.allow("a") and rl.allow("b")
    now[0] += 601
    assert rl.allow("a") and not rl.allow("a")       # daily per-IP limit (3) reached
    cap = core.DailyCap(0.01, clock=lambda: now[0])
    assert cap.ok(); cap.add(0.005); assert cap.ok(); cap.add(0.005); assert not cap.ok()
    now[0] += 86400
    assert cap.ok()                                   # new UTC day


def test_ttl_cache():
    t = [0.0]
    c = core.TTLCache(ttl=10, clock=lambda: t[0], max_items=2)
    c.put("a", 1); c.put("b", 2); c.put("c", 3)
    assert c.get("a") is None and c.get("c") == 3
    t[0] = 11
    assert c.get("c") is None


class FakeClient:
    def __init__(self, status=200, cost=0.005):
        self.calls, self.status, self.cost = [], status, cost

    def search(self, payload, tag="search"):
        self.calls.append(("search", payload))
        body = {"results": [res("https://a.org/1", "A", "2026-10-15"), res("https://b.org/2", "B", None)], "cost_usd": self.cost}
        return self.status, body, {"cost": self.cost, "latency_s": 0.3}

    def ai_search(self, payload, tag="answer"):
        self.calls.append(("answer", payload))
        body = {"search": [{"link": "https://a.org/1", "title": "rate limiting guide", "snippet": "rate limiting"}],
                "completion": "Use a token bucket [1](https://a.org/1)."}
        return self.status, body, {"cost": 0.004, "latency_s": 9.0}


def engine(**kw):
    return Engine(client=kw.pop("client", FakeClient()), live=kw.pop("live", True), **kw)


def test_handle_search_validates_before_paying():
    e = engine()
    for q in ({"q": ""}, {"q": "   "}, {"q": "rate limiting", "count": "12"}, {"q": "rate limiting", "from": "2026-10-18", "to": "2026-10-01"}):
        code, h, _ = e.handle_search(q, "1.1.1.1")
        assert code == 400 and h["Cache-Control"] == "no-store"
    assert e._client.calls == []


def test_handle_search_ok_then_cache():
    e = engine()
    code, h, text = e.handle_search({"q": "rate limiting", "mode": "balanced", "range": "week"}, "1.1.1.1")
    d = json.loads(text)
    assert code == 200 and h["Cache-Control"] == CACHE_HEADER and d["cached"] is False and d["cost_usd_this_request"] == 0.005
    sent = e._client.calls[0][1]
    assert sent["mode"] == "balanced" and "start_date" in sent and sent["highlights"] is True
    assert d["stats"]["no_date"] == 1
    code, _, text = e.handle_search({"q": "Rate Limiting!", "mode": "balanced", "range": "week"}, "2.2.2.2")
    assert code == 200 and json.loads(text)["cached"] is True and len(e._client.calls) == 1
    assert KEY not in text


def test_handle_kill_switch_cap_limit_and_upstream_error():
    code, _, text = engine(live=False).handle_search({"q": "rate limiting"}, "ip")
    assert code == 503 and json.loads(text)["sample"] == "/sample.json"
    capped = engine(cap=core.DailyCap(0.0))
    assert capped.handle_search({"q": "rate limiting"}, "ip")[0] == 503
    lim = engine(limiter=core.RateLimiter(per_ip=1))
    assert lim.handle_search({"q": "one query"}, "ip")[0] == 200
    assert lim.handle_search({"q": "another query"}, "ip")[0] == 429
    assert engine(client=FakeClient(status=500)).handle_search({"q": "rate limiting"}, "ip")[0] == 502


def test_handle_answer():
    e = engine()
    assert e.handle_answer({"q": ""}, "ip")[0] == 400
    code, h, text = e.handle_answer({"q": "rate limiting"}, "ip")
    d = json.loads(text)
    assert code == 200 and h["Cache-Control"] == CACHE_HEADER and d["summary"]["lines"][0]["text"] == "Use a token bucket."
    assert e._client.calls[0][1]["tools"] == ["web"]


def test_missing_key_is_a_clean_500(monkeypatch):
    monkeypatch.delenv("DESEARCH_API_KEY", raising=False)
    monkeypatch.delenv("DESEARCH_API_KEY_FILE", raising=False)
    code, _, text = Engine(live=True).handle_search({"q": "rate limiting"}, "ip")
    assert code == 500 and json.loads(text) == {"error": "The demo is not configured."}


class _Resp(io.BytesIO):
    status = 200
    headers = {"Content-Type": "application/json"}   # POST /search sends no X-Desearch-* headers


def test_client_reads_cost_from_body_and_redacts(monkeypatch, tmp_path):
    seen = {}

    def fake_urlopen(req, timeout=0):
        seen["ua"], seen["auth"] = req.get_header("User-agent"), req.get_header("Authorization")
        return _Resp(json.dumps({"results": [], "cost_usd": 0.005, "usage_count": 10}).encode())
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    c = Client(KEY, log_dir=tmp_path, quiet=True)
    st, body, rec = c.search({"query": "x"})
    assert st == 200 and rec["cost"] == 0.005 and rec["cost_source"] == "body"
    assert seen["ua"].startswith("ai-search-engine-web-app/") and seen["auth"] == KEY
    logged = "".join(p.read_text() for p in tmp_path.rglob("*") if p.is_file())
    assert KEY not in logged and "<redacted>" in logged
    with pytest.raises(RuntimeError):
        c._write(tmp_path / "leak.txt", "x " + KEY)


def test_client_cost_header_then_body_then_unknown(monkeypatch):
    def run(body, headers):
        r = _Resp(body); r.headers = {"Content-Type": "application/json", **headers}
        monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=0: r)
        return Client(KEY, quiet=True).search({"query": "x"})[2]
    h = run(b'{"cost_usd": 0.005}', {"X-Desearch-Cost-USD": "0.004"})
    assert h["cost"] == 0.004 and h["cost_source"] == "header" and h["cost_known"] is True
    b = run(b'{"cost_usd": 0.005}', {})
    assert b["cost"] == 0.005 and b["cost_source"] == "body" and b["cost_known"] is True
    z = run(b'{"detail": "x", "cost_usd": 0.0}', {})   # the 503 for a blank query reports cost_usd 0.0: known, zero
    assert z["cost"] == 0.0 and z["cost_known"] is True
    n = run(b'{"results": []}', {})
    assert n["cost"] == 0.0 and n["cost_source"] == "none" and n["cost_known"] is False


def test_cap_counts_fallback_when_cost_unknown(monkeypatch):
    class NoCost(FakeClient):
        def search(self, payload, tag="search"):
            st, body, _ = super().search(payload, tag)
            body.pop("cost_usd")
            return st, body, {"cost": 0.0, "cost_known": False, "latency_s": 0.3}
    e = engine(client=NoCost(), cap=core.DailyCap(0.01))
    assert e.fallback_cost == 0.005
    assert e.handle_search({"q": "first query"}, "a")[0] == 200
    assert e.handle_search({"q": "second query"}, "b")[0] == 200
    assert abs(e.cap.spent - 0.01) < 1e-9
    assert e.handle_search({"q": "third query"}, "c")[0] == 503 and len(e._client.calls) == 2
    assert e.cap_cost(401, {"cost": 0.0, "cost_known": False}) == 0.0
    assert e.cap_cost(503, {"cost": 0.0, "cost_known": False}) == 0.0
    assert e.cap_cost(200, {"cost": 0.004, "cost_known": True}) == 0.004
    monkeypatch.setenv("DEMO_FALLBACK_COST_USD", "0.02")
    assert Engine(client=NoCost(), live=True).fallback_cost == 0.02


def test_vercel_functions_import_without_key(monkeypatch):
    monkeypatch.delenv("DESEARCH_API_KEY", raising=False)
    monkeypatch.setenv("DEMO_LIVE", "0")
    import importlib.util
    for name in ("search", "answer"):
        spec = importlib.util.spec_from_file_location(f"api_{name}", pathlib.Path(__file__).parent / "api" / f"{name}.py")
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        fn = m.ENGINE.handle_search if name == "search" else m.ENGINE.handle_answer
        assert fn({"q": "rate limiting"}, "ip")[0] == 503


def test_helpers():
    assert client_ip({"x-forwarded-for": "9.9.9.9, 10.0.0.1"}) == "9.9.9.9"
    assert client_ip({}, "127.0.0.1") == "127.0.0.1"
    assert parse_query("/api/search?q=a+b&mode=fast") == {"q": "a b", "mode": "fast"}


def test_public_page_and_sample():
    root = pathlib.Path(__file__).parent
    page = (root / "public" / "index.html").read_text()
    assert "Made by Desearch" in page and "https://desearch.ai" in page and "\u2014" not in page
    s = json.loads((root / "public" / "sample.json").read_text())
    assert s["search"]["results"] and "links" in s["answer"]
