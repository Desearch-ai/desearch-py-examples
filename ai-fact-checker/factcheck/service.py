"""The /api/check endpoint, shared by the local server (app.py) and the Vercel function (api/check.py).

Safety: the Desearch key is read on the server only and never put in a response or a log line. Requests are
validated before any paid call; a per-IP limit, a daily spend cap, a cache and a kill switch (DEMO_LIVE=0) sit
in front of the API. Limits and the cap live in Upstash Redis when it is configured, so they hold across
instances; otherwise they fall back to memory (one warning). A store error fails closed with the same 503
as the kill switch. The in-memory result cache is per warm instance; the CDN cache (Cache-Control s-maxage)
serves repeat claims without calling the function at all. Logs never include the Redis token, the claim or the IP.
"""
import json, os, sys, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from . import core, limits
from .client import Client, api_key

CACHE_HEADER = "public, max-age=0, s-maxage=21600"
NO_STORE = "no-store"
PAUSED = {"error": "The live demo is paused. See the saved sample run.", "sample": "/sample.json"}


def _env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


class Checker:
    def __init__(self, client=None, limiter=None, cap=None, cache=None, live=None):
        self._client = client
        if limiter is None and cap is None:
            per_ip = int(_env_float("DEMO_PER_IP_10MIN", 5))
            per_ip_day = int(_env_float("DEMO_PER_IP_DAY", 15))
            global_window = int(_env_float("DEMO_GLOBAL_10MIN", 30))
            cap_usd = _env_float("DEMO_DAILY_CAP_USD", 1.0)
            limiter, cap = limits.load(per_ip, per_ip_day, global_window, cap_usd)
            if limiter is None:
                limiter = core.RateLimiter(per_ip=per_ip, per_ip_day=per_ip_day, global_window=global_window)
                cap = core.DailyCap(cap_usd)
        self.limiter = limiter or core.RateLimiter(per_ip=int(_env_float("DEMO_PER_IP_10MIN", 5)),
                                                   per_ip_day=int(_env_float("DEMO_PER_IP_DAY", 15)),
                                                   global_window=int(_env_float("DEMO_GLOBAL_10MIN", 30)))
        self.cap = cap or core.DailyCap(_env_float("DEMO_DAILY_CAP_USD", 1.0))
        self.cache = cache or core.TTLCache()
        self.fallback_cost = _env_float("DEMO_FALLBACK_COST_USD", 0.005)
        self.live = (os.environ.get("DEMO_LIVE", "1") != "0") if live is None else live

    def cap_cost(self, status, rec):
        """What a call counts against the daily cap. If the API sent no cost (no X-Desearch-Cost-USD header and no
        body cost_usd), a 2xx/4xx call counts DEMO_FALLBACK_COST_USD so missing headers cannot switch the cap off."""
        if rec.get("cost_known", True):
            return rec["cost"]
        return self.fallback_cost if status < 500 and status not in (401, 402, 403, 429) else 0.0

    def client(self):
        if self._client is None:
            self._client = Client(api_key(), log_dir=os.environ.get("FACTCHECK_LOG_DIR"))
        return self._client

    def run(self, claim, wiki=False):
        """Paid part: 2 calls (ai-search web + X search), 3 with the Wikipedia option."""
        c = self.client()
        jobs = [("ai", c.ai_search, core.ai_body(claim, "web")), ("x", c.x_search, core.x_params(claim))]
        if wiki:
            jobs.append(("wiki", c.ai_search, core.ai_body(claim, "wikipedia")))
        calls = {}
        with ThreadPoolExecutor(max_workers=len(jobs)) as ex:   # calls run in parallel
            futs = {name: ex.submit(fn, arg, f"check-{name}") for name, fn, arg in jobs}
            for name, f in futs.items():
                st, body, rec = f.result()
                self.cap.add(self.cap_cost(st, rec))
                calls[name] = {"status": st, "body": body, "cost": rec["cost"], "latency_s": rec["latency_s"]}
        if calls["ai"]["status"] != 200 or not isinstance(calls["ai"]["body"], dict):
            return calls["ai"]["status"], None, calls
        return 200, core.build_result(claim, calls["ai"], calls["x"], calls.get("wiki")), calls

    def handle(self, query, ip):
        """query: dict of GET params. Returns (http_status, headers, json_text)."""
        def out(code, obj, cache=NO_STORE):
            return code, {"Content-Type": "application/json; charset=utf-8", "Cache-Control": cache,
                          "X-Content-Type-Options": "nosniff"}, json.dumps(obj, ensure_ascii=False)
        try:
            claim = core.clean_claim(query.get("claim"))
        except core.FormError as e:
            return out(400, {"error": str(e)})
        wiki = str(query.get("wiki", "")).lower() in ("1", "true", "yes", "on")
        key = core.cache_key(claim, wiki)
        hit = self.cache.get(key)
        if hit:
            return out(200, {**hit, "cached": True, "cost_usd_this_request": 0}, CACHE_HEADER)
        if not self.live:
            return out(503, PAUSED)
        try:
            if not self.cap.ok():
                return out(503, {"error": "Today's demo budget is used up. See the saved sample run, or run it yourself.", "sample": "/sample.json"})
            if not self.limiter.allow(ip or "unknown"):
                return out(429, {"error": "Too many checks from your network. Try again in a few minutes."})
            st, res, _ = self.run(claim, wiki)
        except limits.StoreError:
            print("[check] shared limit store error", file=sys.stderr)
            return out(503, PAUSED)
        except RuntimeError as e:   # missing key on the server: say so without details
            print(f"[check] server error: {type(e).__name__}", file=sys.stderr)
            return out(500, {"error": "The demo is not configured."})
        if st != 200:
            return out(502, {"error": f"Search API returned {st}. Try again later."})
        self.cache.put(key, res)
        print(f"[check] ok calls={res['calls']} cost={res['cost_usd']} spent_today={round(self.cap.spent, 4)}", file=sys.stderr)
        return out(200, {**res, "cached": False, "cost_usd_this_request": res["cost_usd"]}, CACHE_HEADER)


def client_ip(headers, fallback=""):
    fwd = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For") or ""
    return fwd.split(",")[0].strip() or headers.get("x-real-ip") or fallback


def parse_query(path):
    return {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(path).query).items()}
