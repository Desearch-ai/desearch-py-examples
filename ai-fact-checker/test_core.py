"""Offline tests (no key, no network): python3 -m pytest -q"""
import hashlib, io, json, pathlib, sys, time, urllib.error, urllib.request
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


class NoCostClient(FakeClient):
    """API answers 200 but sends no cost header and no body cost_usd."""
    def ai_search(self, payload, tag=""):
        st, body, _ = super().ai_search(payload, tag)
        return st, body, {"cost": 0.0, "cost_known": False, "latency_s": 1}

    def x_search(self, params, tag=""):
        st, body, _ = super().x_search(params, tag)
        return st, body, {"cost": 0.0, "cost_known": False, "latency_s": 1}


def test_cap_still_trips_when_cost_headers_are_missing():
    ch = Checker(client=NoCostClient(), live=True, cap=core.DailyCap(0.01))
    assert ch.handle({"claim": "Honey never spoils if stored"}, "a")[0] == 200   # 2 calls x 0.005 fallback
    assert abs(ch.cap.spent - 0.01) < 1e-9
    assert ch.handle({"claim": "Octopuses have three hearts"}, "b")[0] == 503 and ch._client.calls == 2
    assert ch.cap_cost(401, {"cost": 0.0, "cost_known": False}) == 0.0


def test_client_cost_header_then_body(monkeypatch):
    import io, urllib.request
    from factcheck import client as fcm

    class R(io.BytesIO):
        status = 200
        def __init__(self, body, headers):
            super().__init__(body); self.headers = headers

    def run(body, headers):
        monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=0: R(body, headers))
        return fcm.Client(KEY, quiet=True).ai_search({"prompt": "x"})[2]
    assert run(b'{"cost_usd": 0.004}', {"X-Desearch-Cost-USD": "0.003"})["cost"] == 0.003
    r = run(b'{"cost_usd": 0.004}', {})
    assert r["cost"] == 0.004 and r["cost_known"] is True
    assert run(b'[]', {})["cost_known"] is False


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


NOW = 1700000100
TOKEN = "super-secret-token"
SALT = "test-salt"


def claim_n(i):
    return f"Honey never spoils in test case {i}"


class FakeRedis:
    """In-memory stand-in for the Upstash REST transaction endpoint. Speaks the HTTP layer."""

    def __init__(self, fail=None):
        self.fail, self.values, self.seen = fail, {}, []

    def __call__(self, req, timeout=0):
        body = json.loads(req.data.decode())
        self.seen.append({"url": req.full_url, "body": body, "auth": req.get_header("Authorization")})
        if self.fail == "network":
            raise urllib.error.URLError("down")
        if self.fail == "redis":
            return io.BytesIO(b'{"error":"ERR down"}')
        out = []
        for cmd in body:
            op = cmd[0].upper()
            key = cmd[1]
            if op == "INCR":
                self.values[key] = int(self.values.get(key, 0)) + 1
                out.append({"result": self.values[key]})
            elif op == "INCRBYFLOAT":
                self.values[key] = round(float(self.values.get(key, 0) or 0) + float(cmd[2]), 6)
                out.append({"result": str(self.values[key])})
            elif op == "GET":
                out.append({"result": None if key not in self.values else str(self.values[key])})
            elif op == "EXPIRE":
                out.append({"result": 1 if key in self.values else 0})
            else:
                out.append({"error": "unknown"})
        return io.BytesIO(json.dumps(out).encode())


def use_store(monkeypatch, fake, *, kv=True, **env):
    from factcheck import limits
    limits._warned = False
    if kv:
        monkeypatch.setenv("KV_REST_API_URL", "https://kv.example.upstash.io")
        monkeypatch.setenv("KV_REST_API_TOKEN", TOKEN)
        monkeypatch.setenv("UPSTASH_REDIS_REST_URL", "https://other.example.upstash.io")
        monkeypatch.setenv("UPSTASH_REDIS_REST_TOKEN", "other-token")
    else:
        monkeypatch.delenv("KV_REST_API_URL", raising=False)
        monkeypatch.delenv("KV_REST_API_TOKEN", raising=False)
        monkeypatch.setenv("UPSTASH_REDIS_REST_URL", "https://upstash.example.upstash.io")
        monkeypatch.setenv("UPSTASH_REDIS_REST_TOKEN", TOKEN)
    monkeypatch.setenv("DEMO_IP_SALT", SALT)
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    monkeypatch.setattr(urllib.request, "urlopen", fake)


def pin(ch, now=NOW):
    clock = lambda: now
    ch.limiter.clock = clock
    ch.cap.clock = clock


def test_redis_sixth_request_from_one_ip_is_429(monkeypatch, capsys):
    from factcheck import limits
    fake = FakeRedis()
    use_store(monkeypatch, fake)
    ch = Checker(client=FakeClient(), live=True)
    assert limits._warned is False
    pin(ch)
    ip, other = "1.2.3.4", "5.6.7.8"
    for i in range(1, 6):
        code, _, _ = ch.handle({"claim": claim_n(i)}, ip)
        assert code == 200
    assert ch._client.calls == 10
    code, h, body = ch.handle({"claim": claim_n(6)}, ip)
    assert code == 429 and h["Cache-Control"] == "no-store" and ch._client.calls == 10
    assert "Too many checks" in body and TOKEN not in body and ip not in body
    code_b, _, _ = ch.handle({"claim": claim_n(7)}, other)
    assert code_b == 200 and ch._client.calls == 12

    hsh = hashlib.sha256(f"{SALT}\n{ip}".encode()).hexdigest()
    assert limits.ip_hash(ip) == hsh and ip not in hsh
    start = NOW // 600 * 600
    day = time.strftime("%Y-%m-%d", time.gmtime(NOW))
    first = [r["body"] for r in fake.seen[:6]]
    assert first[0] == [["GET", f"factcheck:usd:{day}"]]
    assert first[1] == [["INCR", f"factcheck:ip10:{hsh}:{start}"], ["EXPIRE", f"factcheck:ip10:{hsh}:{start}", 600, "NX"]]
    assert first[2][0][1] == f"factcheck:ipday:{hsh}:{day}" and first[2][1][2:] == [86400, "NX"]
    assert first[3] == [["INCR", f"factcheck:g10:{start}"], ["EXPIRE", f"factcheck:g10:{start}", 600, "NX"]]
    assert [c[0] for c in first[4]] == ["INCRBYFLOAT", "EXPIRE"] and first[4][1][2:] == [86400, "NX"]
    assert [c[0] for c in first[5]] == ["INCRBYFLOAT", "EXPIRE"]
    blob = json.dumps(fake.seen)
    assert ip not in blob and other not in blob
    assert all(r["url"] == "https://kv.example.upstash.io/multi-exec" for r in fake.seen)
    assert all(r["auth"] == "Bearer " + TOKEN for r in fake.seen)
    assert all(TOKEN not in r["url"] for r in fake.seen)
    err = capsys.readouterr().err
    assert TOKEN not in err and ip not in err and "Honey never spoils" not in err


def test_redis_global_limit_and_upstash_env_names(monkeypatch):
    fake = FakeRedis()
    use_store(monkeypatch, fake, kv=False, DEMO_GLOBAL_10MIN=2)
    ch = Checker(client=FakeClient(), live=True)
    pin(ch)
    assert ch.handle({"claim": claim_n(1)}, "10.0.0.1")[0] == 200
    assert ch.handle({"claim": claim_n(2)}, "10.0.0.2")[0] == 200
    code, h, body = ch.handle({"claim": claim_n(3)}, "10.0.0.3")
    assert code == 429 and h["Cache-Control"] == "no-store" and "Too many checks" in body
    assert ch._client.calls == 4
    assert fake.seen[0]["url"] == "https://upstash.example.upstash.io/multi-exec"
    assert any(cmd[0] == "INCR" and cmd[1].startswith("factcheck:g10:") for r in fake.seen for cmd in r["body"])


def test_redis_cap_blocks_once_reached(monkeypatch):
    fake = FakeRedis()
    use_store(monkeypatch, fake, DEMO_DAILY_CAP_USD="0.0055")
    ch = Checker(client=FakeClient(), live=True)
    pin(ch)
    assert ch.handle({"claim": claim_n(1)}, "1.1.1.1")[0] == 200
    assert abs(ch.cap.spent - 0.0055) < 1e-9
    before = len(fake.seen)
    code, h, body = ch.handle({"claim": claim_n(2)}, "2.2.2.2")
    assert code == 503 and h["Cache-Control"] == "no-store" and "used up" in body and '"sample": "/sample.json"' in body
    assert ch._client.calls == 2
    new = fake.seen[before:]
    assert len(new) == 1 and new[0]["body"][0][0] == "GET"


def test_redis_store_error_is_503_like_the_kill_switch(monkeypatch, capsys):
    for fail in ("network", "redis"):
        fake = FakeRedis(fail=fail)
        use_store(monkeypatch, fake)
        ch = Checker(client=FakeClient(), live=True)
        code, h, body = ch.handle({"claim": claim_n(1)}, "9.9.9.9")
        paused = Checker(client=FakeClient(), live=False).handle({"claim": claim_n(1)}, "9.9.9.9")
        assert code == 503 and h["Cache-Control"] == "no-store" and body == paused[2]
        assert '"sample": "/sample.json"' in body and ch._client.calls == 0
        bad, hb, _ = ch.handle({"claim": ""}, "9.9.9.9")
        assert bad == 400 and hb["Cache-Control"] == "no-store"
    err = capsys.readouterr().err
    assert TOKEN not in err and "9.9.9.9" not in err and "Honey never spoils" not in err
    assert "shared limit store error" in err


def test_limits_fallback_to_memory_when_store_unset(monkeypatch, capsys):
    from factcheck import limits
    for name in ("KV_REST_API_URL", "KV_REST_API_TOKEN", "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN",
                 "DEMO_IP_SALT", "VERCEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("VERCEL_ENV", "development")  # not production or preview, and VERCEL is unset: local fallback
    monkeypatch.setenv("DEMO_PER_IP_10MIN", "1")
    limits._warned = False
    called = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: called.append(1))
    ch = Checker(client=FakeClient(), live=True)
    assert isinstance(ch.limiter, core.RateLimiter) and isinstance(ch.cap, core.DailyCap)
    assert ch.handle({"claim": claim_n(1)}, "8.8.8.8")[0] == 200
    code, h, _ = ch.handle({"claim": claim_n(2)}, "8.8.8.8")
    assert code == 429 and h["Cache-Control"] == "no-store" and called == []
    digest = limits.ip_hash("8.8.8.8")
    assert digest == hashlib.sha256(f"{limits.FALLBACK_IP_SALT}\n8.8.8.8".encode()).hexdigest()
    assert "8.8.8.8" not in digest
    err = capsys.readouterr().err
    assert "in-memory counters" in err and "8.8.8.8" not in err and TOKEN not in err
    Checker(client=FakeClient(), live=True)
    assert "in-memory counters" not in capsys.readouterr().err


def test_vercel_without_store_fails_closed(monkeypatch, capsys):
    from factcheck import limits
    from factcheck.service import PAUSED
    for name in ("KV_REST_API_URL", "KV_REST_API_TOKEN", "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    called = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: called.append(1))
    for key, val in (("VERCEL", "1"), ("VERCEL_ENV", "production"), ("VERCEL_ENV", "preview")):
        monkeypatch.delenv("VERCEL", raising=False)
        monkeypatch.delenv("VERCEL_ENV", raising=False)
        monkeypatch.setenv(key, val)
        limits._closed_warned = False
        ch = Checker(client=FakeClient(), live=True)
        assert not isinstance(ch.limiter, core.RateLimiter) and not isinstance(ch.cap, core.DailyCap)
        code, h, body = ch.handle({"claim": claim_n(1)}, "1.2.3.4")
        assert code == 503 and h["Cache-Control"] == "no-store" and json.loads(body) == PAUSED
        assert ch._client.calls == 0 and called == []
        code2, h2, _ = ch.handle({"claim": claim_n(2)}, "9.9.9.9")
        assert code2 == 503 and h2["Cache-Control"] == "no-store" and ch._client.calls == 0
        bad, hb, _ = ch.handle({"claim": ""}, "1.2.3.4")
        assert bad == 400 and hb["Cache-Control"] == "no-store"
    err = capsys.readouterr().err
    assert "refusing live checks" in err and "in-memory counters" not in err
    assert "1.2.3.4" not in err and "9.9.9.9" not in err and "Honey never spoils" not in err and TOKEN not in err


def test_vercel_with_store_still_runs(monkeypatch):
    fake = FakeRedis()
    use_store(monkeypatch, fake)
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("VERCEL_ENV", "production")
    ch = Checker(client=FakeClient(), live=True)
    pin(ch)
    assert ch.handle({"claim": claim_n(1)}, "1.2.3.4")[0] == 200 and ch._client.calls == 2
