import json, os, sys, urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from . import core, state
from .client import Client, api_key
import datetime as dt
import threading
from ai_news_board import plan_requests, build_board

CACHE_HEADER = "public, max-age=0, s-maxage=21600"
NO_STORE = "no-store"


def _env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


class Board:
    def __init__(self, client=None, limiter=None, cap=None, cache=None, live=None):
        self._client = client
        self.build_lock = threading.Lock()
        memory = os.environ.get("DEMO_STATE") == "memory" or any(
            item is not None for item in (limiter, cap, cache))
        backend = core if memory else state
        args = () if memory else (state.RedisREST(),)
        self.limiter = limiter if limiter is not None else (
            backend.RateLimiter if memory else backend.Limiter)(
                *args, per_ip=int(_env_float("DEMO_PER_IP_10MIN", 5)),
                per_ip_day=int(_env_float("DEMO_PER_IP_DAY", 15)),
                global_window=int(_env_float("DEMO_GLOBAL_10MIN", 30)))
        self.cap = cap if cap is not None else backend.DailyCap(*args, _env_float("DEMO_DAILY_CAP_USD", 1.0))
        self.cache = cache if cache is not None else (backend.TTLCache if memory else backend.Cache)(*args)
        self.fallback_cost = _env_float("DEMO_FALLBACK_COST_USD", 0.005)
        self.live = (os.environ.get("DEMO_LIVE", "1") != "0") if live is None else live

    def cap_cost(self, status, rec):
        """What a call counts against the daily cap. If the API sent no cost (no X-Desearch-Cost-USD header and no
        body cost_usd), a 2xx/4xx call counts DEMO_FALLBACK_COST_USD so missing headers cannot switch the cap off.
        A 401, 402 or 403 (invalid key or out of balance) counts $0."""
        if status in (401, 402, 403):
            return 0.0
        if rec.get("cost_known", True):
            return rec["cost"]
        return self.fallback_cost if status < 500 and status not in (401, 402, 403, 429) else 0.0

    def client(self):
        if self._client is None:
            self._client = Client(api_key())
        return self._client

    def run(self):
        client = self.client()
        jobs = plan_requests()
        calls = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [(kind, tag, executor.submit(client.x_search if kind == "x" else client.ai_search, params, tag))
                       for kind, tag, params in jobs]
            for kind, tag, future in futures:
                try:
                    status, body, rec = future.result()
                except Exception:
                    status, body, rec = 599, {}, {"cost": 0, "cost_known": False}
                cost = self.cap_cost(status, rec)
                self.cap.add(cost)
                calls.append({"source": kind, "tag": tag, "status": status, "body": body, "cost_usd": cost})
        spent = round(sum(call["cost_usd"] for call in calls), 6)
        statuses = Counter(call["status"] for call in calls)
        status_counts = ",".join(f"{code}:{statuses[code]}" for code in sorted(statuses))
        print(f"[board] calls={len(calls)} cost={spent} spent_today={round(self.cap.spent, 6)} "
              f"statuses={{{status_counts}}}", file=sys.stderr)
        if any(call["status"] in (401, 402, 403) for call in calls):
            return 403, None
        if any(not any(c["status"] == 200 for c in calls if c["source"] == kind) for kind in ("x", "web")):
            return 502, None
        result = build_board([c for c in calls if c["status"] == 200], dt.datetime.now(dt.timezone.utc))
        result.update(calls=len(calls), cost_usd=spent, partial=any(c["status"] != 200 for c in calls))
        return 200, result

    def handle(self, query, ip):
        # Serialize cache misses so simultaneous viewers share a single paid build.
        with self.build_lock:
            try:
                return self._handle(query, ip)
            except state.StateUnavailable:
                return 503, {"Content-Type": "application/json; charset=utf-8",
                             "Cache-Control": NO_STORE, "X-Content-Type-Options": "nosniff"}, json.dumps({
                    "status": "paused", "error": "The live demo is paused. See the saved sample run.",
                    "sample": "/sample.json"})

    def _handle(self, query, ip):
        """query: dict of GET params. Returns (http_status, headers, json_text)."""
        def out(code, obj, cache=NO_STORE):
            return code, {"Content-Type": "application/json; charset=utf-8", "Cache-Control": cache,
                          "X-Content-Type-Options": "nosniff"}, json.dumps(obj, ensure_ascii=False)
        if query:
            return out(400, {"error": "This endpoint accepts no parameters."})
        utc = dt.datetime.now(dt.timezone.utc)
        key = (utc.date().isoformat(), utc.hour // 6)
        hit = self.cache.get(key)
        if hit:
            return out(200, {**hit, "cached": True, "cost_usd_this_request": 0}, CACHE_HEADER)
        if not self.live:
            return out(503, {"status": "paused", "error": "The live demo is paused. See the saved sample run.", "sample": "/sample.json"})
        if not self.cap.ok():
            return out(503, {"status": "paused", "error": "Today's demo budget is used up. See the saved sample run, or run it yourself.", "sample": "/sample.json"})
        if not self.limiter.allow(ip or "unknown"):
            return out(429, {"error": "Too many requests from your network. Try again in a few minutes."})
        try:
            st, res = self.run()
        except RuntimeError as e:   # missing key on the server: say so without details
            print(f"[check] server error: {type(e).__name__}", file=sys.stderr)
            return out(500, {"error": "The demo is not configured."})
        if st in (401, 402, 403):   # bad key or empty balance: same response as the kill switch
            return out(503, {"status": "paused", "error": "The live demo is paused. See the saved sample run.", "sample": "/sample.json"})
        if st != 200:
            return out(502, {"error": f"Search API returned {st}. Try again later."})
        self.cache.put(key, res)
        return out(200, {**res, "cached": False, "cost_usd_this_request": res["cost_usd"]}, CACHE_HEADER)


def client_ip(headers, fallback=""):
    fwd = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For") or ""
    return fwd.split(",")[0].strip() or headers.get("x-real-ip") or fallback


def parse_query(path):
    return {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(path).query, keep_blank_values=True).items()}
