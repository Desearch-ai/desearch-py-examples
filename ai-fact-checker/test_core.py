"""Offline tests (no key, no network): python3 -m pytest -q"""
import json, pathlib, sys
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from factcheck import core
from factcheck.service import Checker, client_ip, parse_query

KEY = "dsk-test-SECRET-1234567890"


def src(url, title="", snippet="", highlights=()):
    return {"link": url, "title": title, "snippet": snippet, "highlights": list(highlights)}


def test_clean_claim_rejects_bad_input():
    for bad in ("", "   ", "short", "x" * 201, "the of and is it"):
        with pytest.raises(core.FormError):
            core.clean_claim(bad)
    assert core.clean_claim("  Honey   never spoils ") == "Honey never spoils"


def test_cache_key_normalizes():
    assert core.cache_key("Honey never spoils!") == core.cache_key("  honey NEVER   spoils ")
    assert core.cache_key("honey never spoils", True).endswith("|wiki")


def test_bodies():
    b = core.ai_body("Honey never spoils if stored sealed")
    assert b["tools"] == ["web"] and b["streaming"] is False and b["count"] == 10
    assert "exclude_domains" not in b and "system_message" not in b
    assert core.ai_body("x y z", "wikipedia")["tools"] == ["wikipedia"]
    assert core.x_params("Honey never spoils if it is stored sealed") == {"query": "honey never spoils stored", "sort": "Top", "count": 10}


def test_wiki_pages_skipped_and_deduped():
    items = [src("https://en.wikipedia.org/wiki/Honey", "Honey"), src("https://en.m.wikipedia.org/wiki/Honey", "Honey"),
             src("https://en.wikipedia.org/wiki/File:Honey.jpg"), src("https://pt.wikipedia.org/wiki/Mel"),
             src("https://en.wikipedia.org/wiki/Talk:Honey"), src("https://example.org/honey", "Honey facts")]
    out, st = core.clean_sources(items, "Honey never spoils")
    assert [s["url"] for s in out] == ["https://en.wikipedia.org/wiki/Honey", "https://example.org/honey"]
    assert st["duplicates"] == 1 and st["skipped"] == {"wiki non-article page": 2, "wiki non-English page": 1}
    assert out[0]["type"] == "wikipedia" and out[1]["type"] == "web"


def test_labels():
    terms = core.key_terms("Great Wall visible from space")
    assert core.label("The Great Wall is visible from space is a myth", terms)[0] == "contradicts"
    assert core.label("The Great Wall is visible from space in photos", terms)[0] == "supports"
    assert core.label("Cooking pasta at home", terms)[0] == "unclear"
    # a cue word that is part of the claim does not flip the label
    t2 = core.key_terms("Honey never spoils")
    assert core.label("Honey never spoils when sealed", t2, "Honey never spoils")[0] == "supports"


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
        self.calls = 0

    def ai_search(self, payload, tag=""):
        self.calls += 1
        return 200, {"search": [src("https://a.org/honey", "Honey never spoils", "Honey never spoils when sealed")],
                     "completion": "Honey keeps for years [1](https://a.org/honey)."}, {"cost": 0.004, "latency_s": 1}

    def x_search(self, params, tag=""):
        self.calls += 1
        return 200, [{"id": "1", "text": "honey never spoils stored right", "user": {"username": "u"}}], {"cost": 0.0015, "latency_s": 1}


def mk(**kw):
    return Checker(client=FakeClient(), live=True, **kw)


def test_handle_flow_cache_headers_and_no_key_leak():
    ch = mk()
    code, h, body = ch.handle({"claim": "Honey never spoils if stored sealed"}, "1.2.3.4")
    assert code == 200 and "s-maxage=21600" in h["Cache-Control"]
    d = json.loads(body)
    assert d["cached"] is False and d["cost_usd"] == 0.0055 and d["posts"][0]["author"] == "a user"
    code2, _, body2 = ch.handle({"claim": "honey never   spoils if stored sealed!"}, "1.2.3.4")
    assert code2 == 200 and json.loads(body2)["cached"] is True and ch._client.calls == 2
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


def test_missing_key_is_500_without_details(monkeypatch):
    monkeypatch.delenv("DESEARCH_API_KEY", raising=False)
    monkeypatch.delenv("DESEARCH_API_KEY_FILE", raising=False)
    code, _, body = Checker(live=True).handle({"claim": "Honey never spoils if stored"}, "ip")
    assert code == 500 and "configured" in body


def test_client_ip_and_query():
    assert client_ip({"x-forwarded-for": "9.9.9.9, 10.0.0.1"}) == "9.9.9.9"
    assert client_ip({}, "127.0.0.1") == "127.0.0.1"
    assert parse_query("/api/check?claim=a+b&wiki=1") == {"claim": "a b", "wiki": "1"}


def test_client_refuses_to_log_key(tmp_path):
    from factcheck.client import Client
    c = Client(KEY, log_dir=tmp_path)
    with pytest.raises(RuntimeError):
        c._write(tmp_path / "x.json", "leak " + KEY)


def test_vercel_files():
    root = pathlib.Path(__file__).parent
    v = json.loads((root / "vercel.json").read_text())
    assert "api/check.py" in v["functions"]
    assert (root / "public" / "index.html").is_file() and (root / "api" / "check.py").is_file()
    assert "Made by Desearch" in (root / "public" / "index.html").read_text()
