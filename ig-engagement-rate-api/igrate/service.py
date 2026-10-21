"""Fail closed shared state, spend accounting and sanitized results."""
import copy
import datetime as dt
import json
import math
import os
from pathlib import Path
import threading
import time
from urllib.parse import parse_qs, urlsplit
from . import state
from .client import Client
from .guards import DailyCap, RateLimiter, TTLCache
from .handles import validate_handle

ESTIMATE = .027


def env_float(name, default):
    try:
        value = float(os.environ.get(name, default))
        return value if math.isfinite(value) and value >= 0 else default
    except ValueError:
        return default


def timestamp(value):
    try:
        if isinstance(value, (int, float)) or isinstance(value, str) and value.replace('.', '', 1).isdigit():
            return dt.datetime.fromtimestamp(float(value), dt.timezone.utc).timestamp()
        parsed = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.replace(tzinfo=parsed.tzinfo or dt.timezone.utc).timestamp()
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def calculate(followers, posts, now=None):
    now = time.time() if now is None else now
    times = [timestamp(p['taken_at']) for p in posts]
    pinned = 0
    for k in (3, 2, 1):
        if len(times) > k and times[k] is not None and all(t is not None and t < times[k] for t in times[:k]):
            pinned = k
            break
    eligible = [p for i, p in enumerate(posts) if i >= pinned and times[i] is not None and now-times[i] >= 86400 and p['likes'] is not None and followers]
    def rate(rows):
        return round(sum(p['likes'] + (p['comments'] or 0) for p in rows) / len(rows) / followers * 100, 4) if rows else None
    clean = [{**p, 'taken_at': dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat() if t is not None else ''} for p, t in zip(posts, times)]
    return {'followers': followers or 0, 'posts_used': len(eligible), 'eligible_posts': len(eligible), 'engagement_rate_pct': rate(eligible), 'by_format': {kind: rate([p for p in eligible if p['type'] == kind]) for kind in ('image', 'carousel', 'video')}, 'posts': clean}


class Engagement:
    def __init__(self, client=None, limiter=None, cap=None, cache=None, live=None, clock=time.monotonic):
        self._client, self.clock = client, clock
        injected = any(v is not None for v in (limiter, cap, cache))
        memory_requested = os.getenv('DEMO_STATE') == 'memory'
        self.refused = memory_requested and not injected and bool(os.getenv('VERCEL') or os.getenv('VERCEL_ENV'))
        memory = injected or (memory_requested and not self.refused)
        redis = state.RedisREST() if not memory else None
        self.limiter = limiter if limiter is not None else (RateLimiter if memory else lambda **kw: state.Limiter(redis, **kw))(
            per_ip=int(env_float('DEMO_PER_IP_10MIN', 2)),
            per_ip_day=int(env_float('DEMO_PER_IP_DAY', 5)),
            global_window=int(env_float('DEMO_GLOBAL_10MIN', 10)))
        self.cap = cap if cap is not None else (DailyCap(env_float('DEMO_DAILY_CAP_USD', 1)) if memory else state.DailyCap(redis, env_float('DEMO_DAILY_CAP_USD', 1)))
        self.cache = cache if cache is not None else (TTLCache() if memory else state.Cache(redis))
        self.live = live
        self.lock = threading.Lock()
        self.sample = json.loads((Path(__file__).resolve().parents[1] / 'public/sample.json').read_text())

    def handle(self, query, ip):
        with self.lock:
            try:
                return self._handle(query, ip)
            except state.StateUnavailable:
                return self.paused()

    def out(self, code, body):
        headers = {'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'public, max-age=0, s-maxage=86400' if code == 200 else 'no-store', 'X-Content-Type-Options': 'nosniff'}
        return code, headers, json.dumps(body, allow_nan=False)

    def paused(self):
        return self.out(503, {**self.sample, 'status': 'paused', 'error': 'The live demo is paused. See the EXAMPLE data below.'})

    def _handle(self, query, ip):
        try:
            handle = validate_handle(query.get('handle'))
        except ValueError as error:
            return self.out(400, {'error': str(error)})
        for account in self.sample['accounts']:
            if account['handle'] == handle:
                return self.out(200, {'sample': True, 'label': 'EXAMPLE data', 'accounts': [account]})
        if self.refused:
            return self.paused()
        hit = self.cache.get(handle)
        if hit is not None:
            return self.out(200, {**hit, 'cached': True})
        live = self.live if self.live is not None else os.getenv('DEMO_LIVE', '1').lower() in ('1', 'true')
        if not live:
            return self.paused()
        try:
            client = self._client or Client(os.getenv('DESEARCH_API_KEY', '').strip())
        except RuntimeError:
            return self.paused()
        # Reuse the reference cap check with enough headroom for this lookup.
        # This view shares Redis (or the local lock); it does not reserve spend.
        preflight = copy.copy(self.cap)
        preflight.cap = math.nextafter(self.cap.cap - ESTIMATE, math.inf)
        if not preflight.ok():
            return self.paused()
        if not self.limiter.allow(ip):
            return self.out(429, {'error': 'Too many lookups. Try again later.'})
        total, timed_out = 0, False
        deadline = self.clock() + 45
        try:
            for posts in (False, True):
                remaining = deadline - self.clock()
                if remaining <= 0:
                    status, body, cost = 599, None, None
                else:
                    try:
                        status, body, cost = client.fetch(handle, posts=posts, timeout=remaining)
                    except (OSError, TimeoutError):
                        status, body, cost = 599, None, None
                if posts and status != 200:
                    total += cost if cost is not None else env_float('DEMO_FALLBACK_COST_USD', ESTIMATE / 2)
                    timed_out = status == 599
                    return self.out(404, {'error': 'account not found or private'})
                if status == 599 or self.clock() > deadline:
                    timed_out = True
                    return self.paused()
                total += cost if cost is not None else env_float('DEMO_FALLBACK_COST_USD', ESTIMATE / 2)
                if status in (401, 402, 403) or status >= 500:
                    return self.paused()
                if status != 200 or (not posts and (not body or body.get('is_private'))) or (posts and not body):
                    return self.out(404, {'error': 'account not found or private'})
                if not posts:
                    followers = body.get('followers')
                else:
                    result = {'sample': False, 'accounts': [{'handle': handle, **calculate(followers, body)}]}
            self.cache.put(handle, result)
            return self.out(200, {**result, 'cached': False})
        finally:
            self.cap.add(max(ESTIMATE, total) if timed_out else total)


def client_ip(headers, fallback=''):
    headers = {k.lower(): v for k, v in headers.items()}
    return (headers.get('x-vercel-forwarded-for') or headers.get('x-forwarded-for') or headers.get('x-real-ip') or fallback).split(',')[0].strip()


def parse_query(path):
    return {k: v[0] for k, v in parse_qs(urlsplit(path).query, keep_blank_values=True).items()}
