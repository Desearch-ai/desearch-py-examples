"""The /api/search and /api/answer endpoints, shared by the local server (app.py) and the Vercel functions (api/).

Safety: the Desearch key is read on the server only and never put in a response or a log line. Requests are validated
before any paid call; a per-IP limit, a daily spend cap, a cache and a kill switch (DEMO_LIVE=0) sit in front of the
API. On Vercel the limit, cap and in-memory cache are per warm instance (best effort); the CDN cache
(Cache-Control s-maxage) serves repeat requests without running the function at all.
"""
import json, os, sys, urllib.parse
from . import core
from .client import Client, api_key

CACHE_HEADER = "public, max-age=0, s-maxage=21600"
NO_STORE = "no-store"


def _env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


class Engine:
    def __init__(self, client=None, limiter=None, cap=None, cache=None, live=None):
        self._client = client
        self.limiter = limiter or core.RateLimiter(per_ip=int(_env_float("DEMO_PER_IP_10MIN", 10)),
                                                   per_ip_day=int(_env_float("DEMO_PER_IP_DAY", 40)),
                                                   global_window=int(_env_float("DEMO_GLOBAL_10MIN", 60)))
        self.cap = cap or core.DailyCap(_env_float("DEMO_DAILY_CAP_USD", 1.0))
        self.cache = cache or core.TTLCache()
        self.live = (os.environ.get("DEMO_LIVE", "1") != "0") if live is None else live

    def client(self):
        if self._client is None:
            self._client = Client(api_key(), log_dir=os.environ.get("SEARCHAPP_LOG_DIR"), quiet=True)
        return self._client

    # paid parts -------------------------------------------------------------------------------------------------
    def search(self, q, mode="fast", count=10, start=None, end=None):
        st, body, rec = self.client().search(core.search_body(q, mode, count, start, end), "search")
        self.cap.add(rec["cost"])
        if st != 200 or not isinstance(body, dict):
            return st, None, rec
        results, stats = core.clean_results(body, start, end)
        return 200, {"query": q, "mode": mode, "count": count, "start_date": start, "end_date": end,
                     "results": results, "stats": stats, "cost_usd": rec["cost"], "latency_s": rec["latency_s"]}, rec

    def answer(self, q, search_urls=None):
        st, body, rec = self.client().ai_search(core.answer_body(q), "answer")
        self.cap.add(rec["cost"])
        if st != 200 or not isinstance(body, dict):
            return st, None, rec
        return 200, {**core.build_answer(q, body, search_urls), "cost_usd": rec["cost"], "latency_s": rec["latency_s"]}, rec

    # HTTP layer -------------------------------------------------------------------------------------------------
    @staticmethod
    def _out(code, obj, cache=NO_STORE):
        return code, {"Content-Type": "application/json; charset=utf-8", "Cache-Control": cache,
                      "X-Content-Type-Options": "nosniff"}, json.dumps(obj, ensure_ascii=False)

    def _gate(self, ip):
        if not self.live:
            return self._out(503, {"error": "The live demo is paused. See the saved sample run.", "sample": "/sample.json"})
        if not self.cap.ok():
            return self._out(503, {"error": "Today's demo budget is used up. See the saved sample run, or run it yourself.", "sample": "/sample.json"})
        if not self.limiter.allow(ip or "unknown"):
            return self._out(429, {"error": "Too many searches from your network. Try again in a few minutes."})
        return None

    def _run(self, fn, *args):
        try:
            return fn(*args)
        except RuntimeError as e:   # missing key on the server: say so without details
            print(f"[searchapp] server error: {type(e).__name__}", file=sys.stderr)
            return None

    def handle_search(self, query, ip):
        """query: dict of GET params (q, mode, count, range, from, to). Returns (status, headers, json_text)."""
        try:
            q = core.clean_query(query.get("q"))
            mode, count = core.parse_mode(query.get("mode")), core.parse_count(query.get("count"))
            start, end = core.date_window(query.get("range"), query.get("from"), query.get("to"))
        except core.FormError as e:
            return self._out(400, {"error": str(e)})
        key = core.cache_key("search", q=q, mode=mode, count=count, start=start, end=end)
        hit = self.cache.get(key)
        if hit:
            return self._out(200, {**hit, "cached": True, "cost_usd_this_request": 0}, CACHE_HEADER)
        blocked = self._gate(ip)
        if blocked:
            return blocked
        r = self._run(self.search, q, mode, count, start, end)
        if r is None:
            return self._out(500, {"error": "The demo is not configured."})
        st, res, _ = r
        if st != 200:
            return self._out(502, {"error": f"Search API returned {st}. Try again later."})
        self.cache.put(key, res)
        print(f"[searchapp] search ok cost={res['cost_usd']} spent_today={round(self.cap.spent, 4)}", file=sys.stderr)
        return self._out(200, {**res, "cached": False, "cost_usd_this_request": res["cost_usd"]}, CACHE_HEADER)

    def handle_answer(self, query, ip):
        try:
            q = core.clean_query(query.get("q"))
        except core.FormError as e:
            return self._out(400, {"error": str(e)})
        key = core.cache_key("answer", q=q)
        hit = self.cache.get(key)
        if hit:
            return self._out(200, {**hit, "cached": True, "cost_usd_this_request": 0}, CACHE_HEADER)
        blocked = self._gate(ip)
        if blocked:
            return blocked
        r = self._run(self.answer, q)
        if r is None:
            return self._out(500, {"error": "The demo is not configured."})
        st, res, _ = r
        if st != 200:
            return self._out(502, {"error": f"Answer API returned {st}. Try again later."})
        self.cache.put(key, res)
        print(f"[searchapp] answer ok cost={res['cost_usd']} spent_today={round(self.cap.spent, 4)}", file=sys.stderr)
        return self._out(200, {**res, "cached": False, "cost_usd_this_request": res["cost_usd"]}, CACHE_HEADER)


def client_ip(headers, fallback=""):
    fwd = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For") or ""
    return fwd.split(",")[0].strip() or headers.get("x-real-ip") or fallback


def parse_query(path):
    return {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(path).query).items()}
