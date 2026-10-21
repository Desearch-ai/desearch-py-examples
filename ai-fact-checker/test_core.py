"""Offline tests (no key, no network): python3 -m pytest -q"""
import contextlib, io, json, os, pathlib, sys, tempfile, unittest
from unittest.mock import patch
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from factcheck import core
from factcheck.service import Checker, client_ip, parse_query

KEY = "dsk-test-SECRET-1234567890"


def src(url, title="", snippet="", highlights=()):
    return {"link": url, "title": title, "snippet": snippet, "highlights": list(highlights)}


def test_clean_claim_rejects_bad_input():
    for bad in ("", "   ", "short", "x" * 201, "the of and is it"):
        with unittest.TestCase().assertRaises(core.FormError):
            core.clean_claim(bad)
    assert core.clean_claim("  Honey   never spoils ") == "Honey never spoils"


def test_cache_key_normalizes():
    assert core.cache_key("Honey never spoils!") == core.cache_key("  honey NEVER   spoils ")
    assert core.cache_key("honey never spoils", True).endswith("|wiki")


def test_bodies():
    b = core.ai_body("Honey never spoils if stored sealed")
    assert b["tools"] == ["web"] and b["streaming"] is False and b["count"] == 10
    assert "exclude_domains" not in b
    assert b["prompt"] == "Honey never spoils if stored sealed"
    assert b["result_type"] == "LINKS_WITH_FINAL_SUMMARY"
    assert "neutral summary of what the sources say" in b["system_message"]
    assert "citing sources" in b["system_message"] and "Do not judge whether the claim is true or false" in b["system_message"]
    assert core.ai_body("x y z", "wikipedia")["tools"] == ["wikipedia"]
    assert core.ai_body("x y z", "wikipedia")["system_message"] == b["system_message"]
    assert core.x_params("Honey never spoils if it is stored sealed") == {"query": "honey never spoils stored", "sort": "Top", "count": 10}


def test_wiki_pages_skipped_and_deduped():
    items = [src("https://en.wikipedia.org/wiki/Honey", "Honey"), src("https://en.m.wikipedia.org/wiki/Honey", "Honey"),
             src("https://en.wikipedia.org/wiki/File:Honey.jpg"), src("https://pt.wikipedia.org/wiki/Mel"),
             src("https://en.wikipedia.org/wiki/Talk:Honey"), src("https://example.org/honey", "Honey facts")]
    out, st = core.clean_sources(items, "Honey never spoils")
    assert [s["url"] for s in out] == ["https://en.wikipedia.org/wiki/Honey", "https://example.org/honey"]
    assert st["duplicates"] == 1 and st["skipped"] == {"wiki non-article page": 2, "wiki non-English page": 1}
    assert out[0]["type"] == "wikipedia" and out[1]["type"] == "web"


def test_citations_keep_only_returned_links():
    sources = [{"url": "https://a.org/x"}, {"url": "https://en.wikipedia.org/wiki/Science_(journal)"}]
    comp = ("Uncited verdict sentence. Fact one [1](https://a.org/x). Fact two [2](https://made.up/page). "
            "Fact three [3](https://en.wikipedia.org/wiki/Science_%28journal%29).")
    r = core.check_citations(comp, sources)
    assert [l["text"] for l in r["lines"]] == ["Fact one.", "Fact three."]
    assert r["hidden"] == 2


def test_no_strong_sources():
    s, _ = core.clean_sources([src("https://a.org", "Science news")], "Zorblaxian crystals cure qwintel fever")
    assert core.strength(s)["no_strong_sources"] is True


def test_posts_anonymized_and_filtered():
    body = [{"id": "123", "text": "Honey never spoils if stored well", "user": {"username": "someone"}, "like_count": 3},
            {"id": "456", "text": "unrelated", "user": {"username": "other"}},
            {"id": "789", "text": "@someone honey spoils? no", "user": {"username": "x"}}]
    posts, dropped = core.clean_posts(body, ["honey", "spoils"])
    assert dropped == 2 and len(posts) == 1 and posts[0]["author"] == "a user" and "someone" not in json.dumps(posts)
    assert posts[0]["url"] == "https://x.com/i/status/123"


def test_rate_limiter_and_cap():
    t = [0.0]
    rl = core.RateLimiter(per_ip=2, window=600, per_ip_day=3, global_window=10, clock=lambda: t[0])
    assert rl.allow("a") and rl.allow("a") and not rl.allow("a")
    t[0] = 700
    assert rl.allow("a") and not rl.allow("a")       # 3 per day
    assert rl.allow("b")
    cap = core.DailyCap(0.01, clock=lambda: t[0])
    cap.add(0.006); assert cap.ok(); cap.add(0.006); assert not cap.ok()
    t[0] = 86400 * 2
    assert cap.ok()                                  # new UTC day


def test_ttl_cache():
    t = [0.0]
    c = core.TTLCache(ttl=10, clock=lambda: t[0], max_items=2)
    c.put("a", 1); c.put("b", 2); c.put("c", 3)
    assert c.get("a") is None and c.get("c") == 3
    t[0] = 11
    assert c.get("c") is None


class FakeClient:
    """Stands in for the Desearch client; echoes the key nowhere."""
    key = KEY

    def __init__(self):
        self.calls, self.x_calls = 0, 0

    def ai_search(self, payload, tag=""):
        self.calls += 1
        return 200, {"search": [src("https://a.org/honey", "Honey never spoils", "Honey never spoils when sealed")],
                     "completion": "Honey keeps for years [1](https://a.org/honey)."}, {"cost": 0.004, "latency_s": 1}

    def x_search(self, params, tag=""):
        self.calls += 1
        self.x_calls += 1
        return 200, [{"id": "1", "text": "honey never spoils stored right", "user": {"username": "u"}}], {"cost": 0.0015, "latency_s": 1}


def mk(**kw):
    kw.setdefault("x_enabled", False)
    return Checker(client=FakeClient(), live=True, **kw)


def test_handle_flow_cache_headers_and_no_key_leak():
    ch = mk()
    code, h, body = ch.handle({"claim": "Honey never spoils if stored sealed"}, "1.2.3.4")
    assert code == 200 and "s-maxage=21600" in h["Cache-Control"]
    d = json.loads(body)
    assert d["cached"] is False and d["cost_usd"] == 0.004 and d["x_enabled"] is False and "posts" not in d
    code2, _, body2 = ch.handle({"claim": "honey never   spoils if stored sealed!"}, "1.2.3.4")
    assert code2 == 200 and json.loads(body2)["cached"] is True and ch._client.calls == 1
    for b, hh in ((body, h), (body2, h)):
        assert KEY not in b and KEY not in json.dumps(hh) and KEY[:8] not in b


def test_handle_bad_input_makes_no_call():
    ch = mk()
    code, h, body = ch.handle({"claim": ""}, "ip")
    assert code == 400 and h["Cache-Control"] == "no-store" and ch._client.calls == 0


def test_kill_switch_cap_and_rate_limit():
    ch = Checker(client=FakeClient(), live=False)
    assert ch.handle({"claim": "Honey never spoils if stored"}, "ip")[0] == 503 and ch._client.calls == 0
    ch = mk(cap=core.DailyCap(0.0))
    assert ch.handle({"claim": "Honey never spoils if stored"}, "ip")[0] == 503 and ch._client.calls == 0
    ch = mk(limiter=core.RateLimiter(per_ip=1))
    assert ch.handle({"claim": "Honey never spoils if stored"}, "ip")[0] == 200
    code, h, _ = ch.handle({"claim": "Octopuses have three hearts"}, "ip")
    assert code == 429 and h["Cache-Control"] == "no-store"


class NoCostClient(FakeClient):
    """API answers 200 but sends no cost header and no body cost_usd."""
    def ai_search(self, payload, tag=""):
        st, body, _ = super().ai_search(payload, tag)
        return st, body, {"cost": 0.0, "cost_known": False, "latency_s": 1}

    def x_search(self, params, tag=""):
        st, body, _ = super().x_search(params, tag)
        return st, body, {"cost": 0.0, "cost_known": False, "latency_s": 1}


class ErrorClient(FakeClient):
    """Desearch answers every call with one HTTP status and a positive known cost."""
    def __init__(self, status):
        super().__init__()
        self.status = status

    def _err(self):
        self.calls += 1
        return self.status, {"detail": "error"}, {"cost": 0.004, "cost_known": True, "latency_s": 1}

    def ai_search(self, payload, tag=""):
        return self._err()

    def x_search(self, params, tag=""):
        return self._err()


def test_key_or_balance_error_serves_paused_sample():
    for status in (401, 402, 403):
        ch = Checker(client=ErrorClient(status), live=True)
        code, headers, body = ch.handle({"claim": "Honey never spoils if stored"}, "ip")
        assert code == 503 and headers["Cache-Control"] == "no-store"
        assert json.loads(body) == {"error": "The live demo is paused. See the saved sample run.", "sample": "/sample.json"}
        assert ch.cap.spent == 0.0


def test_upstream_500_still_returns_502():
    ch = Checker(client=ErrorClient(500), live=True)
    code, _, body = ch.handle({"claim": "Honey never spoils if stored"}, "ip")
    assert code == 502 and json.loads(body) == {"error": "Search API returned 500. Try again later."}


def test_cap_still_trips_when_cost_headers_are_missing():
    ch = Checker(client=NoCostClient(), live=True, x_enabled=False, cap=core.DailyCap(0.005))
    assert ch.handle({"claim": "Honey never spoils if stored"}, "a")[0] == 200   # one call at 0.005 fallback
    assert abs(ch.cap.spent - 0.005) < 1e-9
    assert ch.handle({"claim": "Octopuses have three hearts"}, "b")[0] == 503 and ch._client.calls == 1
    assert ch.cap_cost(401, {"cost": 0.0, "cost_known": False}) == 0.0


def test_client_cost_header_then_body():
    import io, urllib.request
    from factcheck import client as fcm

    class R(io.BytesIO):
        status = 200
        def __init__(self, body, headers):
            super().__init__(body); self.headers = headers

    def run(body, headers):
        with patch.object(urllib.request, "urlopen", lambda req, timeout=0: R(body, headers)):
            return fcm.Client(KEY, quiet=True).ai_search({"prompt": "x"})[2]
    assert run(b'{"cost_usd": 0.004}', {"X-Desearch-Cost-USD": "0.003"})["cost"] == 0.003
    r = run(b'{"cost_usd": 0.004}', {})
    assert r["cost"] == 0.004 and r["cost_known"] is True
    assert run(b'[]', {})["cost_known"] is False


def test_missing_key_is_500_without_details():
    with patch("factcheck.service.api_key", return_value=None):
        code, _, body = Checker(live=True).handle({"claim": "Honey never spoils if stored"}, "ip")
    assert code == 500 and "configured" in body


def test_client_ip_and_query():
    assert client_ip({"x-forwarded-for": "9.9.9.9, 10.0.0.1"}) == "9.9.9.9"
    assert client_ip({}, "127.0.0.1") == "127.0.0.1"
    assert parse_query("/api/check?claim=a+b&wiki=1") == {"claim": "a b", "wiki": "1"}


def test_client_refuses_to_log_key():
    from factcheck.client import Client
    with tempfile.TemporaryDirectory() as tmp:
        c = Client(KEY, log_dir=tmp)
        with unittest.TestCase().assertRaises(RuntimeError):
            c._write(pathlib.Path(tmp) / "x.json", "leak " + KEY)


def test_vercel_files():
    root = pathlib.Path(__file__).parent
    v = json.loads((root / "vercel.json").read_text())
    assert "api/check.py" in v["functions"]
    assert (root / "public" / "index.html").is_file() and (root / "api" / "check.py").is_file()
    assert "Made by Desearch" in (root / "public" / "index.html").read_text()


def test_eiffel_berlin_sources_are_neutral():
    import app
    # Minimal excerpt of the actual failed QA output, copied into the repo.
    fixture = json.loads((pathlib.Path(__file__).parent / "samples/fixtures/eiffel-summary.json").read_text())
    lines = fixture["summary"]["lines"]
    assert "is true;" in lines[0]["text"]
    completion = " ".join(l["text"] + " " + " ".join(f"[{i}]({u})" for i, u in enumerate(l["cites"], 1)) for l in lines)
    ai = {"status": 200, "cost": 0.004, "latency_s": 10, "body": {
        "search": fixture["sources"], "completion": completion}}
    res = core.build_result(fixture["claim"] + ".", ai)
    assert [l["text"] for l in res["summary"]["lines"]] == [l["text"] for l in lines[1:]]
    assert res["summary"]["verdict_hidden"] == 1 and res["summary"]["hidden"] == 0
    assert not any(core.is_verdict(l["text"]) for l in res["summary"]["lines"])
    assert lines[0]["cites"][0] not in res["summary"]["cited_urls"]
    assert res["x_enabled"] is False and "posts" not in res
    assert "labels" not in res and all("label" not in s for s in res["sources"])
    ch = mk()
    with patch.object(app, "api_key", return_value=KEY), patch.object(app, "Client", return_value=ch._client), \
         patch.object(app, "Checker", return_value=ch), patch.object(ch, "run", return_value=(200, res, {})), \
         contextlib.redirect_stdout(io.StringIO()) as output:
        assert app.main(["--cli", res["claim"]]) == 0
    for text in (output.getvalue(), core.render_html(res)):
        assert "supports" not in text.lower() and "contradicts" not in text.lower() and "unclear" not in text.lower()
        assert "Eiffel Tower" in text and "Berlin" in text
        assert "is true" not in text.lower() and lines[1]["text"] in text
        assert "key words" not in text.lower() and "contain most" not in text.lower()
        assert "3 sources returned." in text
        assert "1 summary sentence(s) that judged the claim were hidden." in text


def test_verdict_detection_positive_words_and_phrases():
    words = ("true", "false", "correct", "incorrect", "accurate", "inaccurate", "right", "wrong",
             "confirmed", "debunked", "myth", "misconception", "untrue", "indeed")
    phrases = ("is not", "isn't", "isn’t", "are not", "aren't", "was not", "wasn't", "were not",
               "the statement that the Eiffel Tower is in Berlin is", "the claim is",
               "this claim is", "the assertion is", "it is a fact")
    for phrase in words + phrases:
        for variant in (phrase, phrase.upper(), phrase.title()):
            text = f"({variant}) [1](https://a.org/source)."
            assert core.is_verdict(text), text
            r = core.check_citations(text, [{"url": "https://a.org/source"}])
            assert r["lines"] == [] and r["verdict_hidden"] == 1 and r["hidden"] == 0, text


def test_verdict_detection_negatives_and_word_boundaries():
    for text in ("The Funkturm was built in 1926.", "The Eiffel Tower opened in 1889.",
                 "Berlin has several towers inspired by the Eiffel Tower.",
                 "The museum displays the statement beside a photograph.",
                 "The bright tower rises above the rightmost building.",
                 "The catalogue includes mythical figures and falsehoods."):
        assert not core.is_verdict(text), text
        r = core.check_citations(text + " [1](https://a.org/true)", [{"url": "https://a.org/true"}])
        assert [l["text"] for l in r["lines"]] == [text]
        assert r["verdict_hidden"] == 0 and r["hidden"] == 0


def test_verdict_sentences_split_without_leaking_trailing_citations():
    url = "https://a.org/tower"
    completion = (f"The Funkturm was built in 1926 [1]({url}). "
                  f"this claim is correct. [2]({url}) "
                  f"berlin has observation decks [3]({url}). "
                  f"indeed [4]({url}). An uncited sentence.")
    r = core.check_citations(completion, [{"url": url}])
    assert [l["text"] for l in r["lines"]] == ["The Funkturm was built in 1926.", "berlin has observation decks."]
    assert r["verdict_hidden"] == 2 and r["hidden"] == 1
    r = core.check_citations(f"This is false. [1]({url}) A neutral uncited sentence.", [{"url": url}])
    assert r == {"lines": [], "hidden": 1, "verdict_hidden": 1, "cited_urls": []}
    assert core.check_citations("", []) == {"lines": [], "hidden": 0, "verdict_hidden": 0, "cited_urls": []}


def test_source_count_uses_returned_sources_only():
    for count in (0, 1, 2, 9):
        sources = [src(f"https://a.org/{n}", "General source") for n in range(count)]
        res = core.build_result("The Eiffel Tower is in Berlin.", {"body": {"search": sources}})
        # Legacy overlap metadata must have no effect on display copy.
        res.update(strong=99, no_strong_sources=True)
        for text in (core.render_text(res), core.render_html(res)):
            assert f"{count} sources returned." in text
            assert ("Few sources returned. Read them before you share anything." in text) == (count < 2)
            for forbidden in ("key words", "contain most", "No strong sources found", "keyword overlap"):
                assert forbidden not in text


def test_posts_need_two_meaningful_claim_terms():
    body = [{"text": "War is what happens when words fail."},
            {"text": "The Eiffel Tower is in Paris."}, {"text": "Berliners love towers."},
            {"text": "The tower looks lovely."}, {"text": "Eiffel tower Berlin city view"}]
    posts, dropped = core.clean_posts(body, core.key_terms("The Eiffel Tower is in Berlin"))
    assert [p["text"] for p in posts] == [body[1]["text"], body[4]["text"]] and dropped == 3
    posts, dropped = core.clean_posts([{"text": "honey"}, {"text": "the and"}], ["the", "honey", "and"])
    assert len(posts) == 1 and dropped == 1
    assert core.clean_posts([{"text": "anything"}], ["the", "and"])[0] == []


def test_posts_drop_profanity_and_simple_obfuscations():
    words = ("fuck", "FUCKING", "f*ck", "shit", "sh!t", "sh*t", "bitch", "b!tch", "asshole", "nigger", "faggot")
    body = [{"text": "Eiffel tower " + w} for w in words]
    body += [{"text": "Eiffel tower architecture classes in Scunthorpe"}]
    posts, dropped = core.clean_posts(body, ["eiffel", "tower"], limit=len(body))
    assert dropped == len(words) and len(posts) == 1 and "architecture" in posts[0]["text"]


def test_x_off_by_default_never_calls_twitter():
    with patch.dict(os.environ, {}, clear=True):
        ch = Checker(client=FakeClient(), live=True)
    code, _, text = ch.handle({"claim": "Honey never spoils if stored sealed"}, "ip")
    d = json.loads(text)
    assert code == 200 and ch._client.calls == 1 and ch._client.x_calls == 0
    assert d["calls"] == 1 and d["cost_usd"] == 0.004 and d["x_enabled"] is False
    assert "posts" not in d and "x_query" not in d and "How it is discussed on X" not in core.render_html(d)


def test_x_environment_flag_calls_twitter_only_when_truthy():
    for value in ("1", "true", "TRUE", "0", "false", "yes", ""):
        with patch.dict(os.environ, {"DEMO_X_ENABLED": value}):
            ch = Checker(client=FakeClient(), live=True)
        code, res, calls = ch.run("Honey never spoils if stored sealed")
        enabled = value.lower() in ("1", "true")
        assert code == 200 and ch._client.x_calls == int(enabled) and res["x_enabled"] == enabled
        assert ("x" in calls) == enabled
        assert res["cost_usd"] == (0.0055 if enabled else 0.004)
        if enabled:
            assert res["posts"][0]["author"] == "a user" and res["x_returned"] == 1


def test_wikipedia_cost_without_x():
    ch = mk()
    code, d, calls = ch.run("Honey never spoils if stored sealed", wiki=True)
    assert code == 200 and d["cost_usd"] == 0.008 and d["calls"] == 2
    assert set(calls) == {"ai", "wiki"} and ch._client.x_calls == 0


def test_cli_x_flag():
    import app
    for args, expected in (([], 0), (["--x"], 1)):
        client = FakeClient()
        with patch.object(app, "api_key", return_value=KEY), patch.object(app, "Client", return_value=client), \
             patch.dict(os.environ, {"DEMO_X_ENABLED": "true"}), contextlib.redirect_stdout(io.StringIO()):
            assert app.main(["--cli", "Honey never spoils if stored sealed"] + args) == 0
        assert client.x_calls == expected


def test_x_and_wiki_cache_entries_are_separate():
    cache = core.TTLCache()
    off, on = mk(cache=cache), mk(cache=cache, x_enabled=True)
    claim = {"claim": "Honey never spoils if stored sealed"}
    off.handle(claim, "ip")
    assert json.loads(on.handle(claim, "ip")[2])["x_enabled"] is True and on._client.x_calls == 1
    assert core.cache_key(claim["claim"]) != core.cache_key(claim["claim"], x=True)
    assert core.cache_key(claim["claim"], wiki=True) != core.cache_key(claim["claim"], x=True)


def test_html_is_stripped_from_all_display_text():
    url = "https://a.org/water"
    raw = "<p>Water &amp; salt</p>"
    encoded = "&lt;p&gt;x&lt;/p&gt;"
    ai = {"status": 200, "cost": 0.004, "latency_s": 10, "body": {
        "search": [src(url, encoded, raw, [raw + " " + encoded + " " + "long highlight " * 4])],
        "completion": raw + " [1](" + url + ")."}}
    x = {"status": 200, "cost": 0.0015, "body": [{"id": "123", "text": raw, "created_at": encoded}]}
    d = core.build_result("Water contains salt", ai, x)
    assert core._txt(raw) == "Water & salt" and core._txt(encoded) == "x"
    assert core._txt("&amp;lt;p&amp;gt;x&amp;lt;/p&amp;gt;") == "x"
    assert d["sources"][0]["title"] == "x" and d["sources"][0]["snippet"] == "Water & salt"
    assert "<" not in d["sources"][0]["quote"] and "&amp;" not in d["sources"][0]["quote"]
    assert d["summary"]["lines"][0]["text"] == "Water & salt."
    assert d["posts"][0]["text"] == "Water & salt" and d["posts"][0]["created_at"] == "x"
    assert "Water &amp; salt" in core.render_html(d)


def test_summary_punctuation_and_duplicate_citations():
    url = "https://a.org/x"
    comp = "Water &amp; salt [1](" + url + "),,,. Salt [source] [source] [source] [2](" + url + ") [2](" + url + "),."
    r = core.check_citations(comp, [{"url": url}])
    assert [l["text"] for l in r["lines"]] == ["Water & salt.", "Salt [source]."]
    assert all(l["cites"] == [url] for l in r["lines"]) and r["cited_urls"] == [url]
    assert core.clean_summary("Text,,,. More,. End:.") == "Text. More. End."


def test_unsafe_urls_are_not_rendered_as_links():
    sources, stats = core.clean_sources([src("javascript:alert(1)", "Water salt"), src("https://a.org", "Water salt")], "Water contains salt")
    assert len(sources) == 1 and stats["skipped"] == {"invalid URL": 1}
    assert core.safe_url("javascript:alert(1)") == "" and core.safe_url("https://a.org") == "https://a.org"


def test_index_has_neutral_sources_and_safe_interpolation():
    text = (pathlib.Path(__file__).parent / "public/index.html").read_text()
    assert "Cue label" not in text and "9 seconds" not in text and "about 10 to 15 seconds" in text
    for token in ("supports", "contradicts", "unclear", "s.label", "${s.rank}", "${d.summary.hidden}",
                  "key words", "contain most", "No strong sources found", "d.no_strong_sources", "d.strong"):
        assert token not in text
    assert "${esc(d.sources.length)} sources returned." in text and "d.sources.length < 2" in text
    assert "Few sources returned. Read them before you share anything." in text
    assert "${esc(d.summary.verdict_hidden)} summary sentence(s) that judged the claim were hidden." in text
    assert "d.x_enabled && d.posts?.length" in text
    for token in ("esc(s.rank)", "esc(s.title || s.url)", "esc(s.domain)", "esc(d.cost_usd)", "esc(d.calls)", "link(s.url)"):
        assert token in text


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(unittest.FunctionTestCase(fn) for name, fn in sorted(globals().items()) if name.startswith("test_"))


if __name__ == "__main__":
    unittest.main()
