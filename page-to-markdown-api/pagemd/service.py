"""Shared demo endpoint. State is shared through Redis unless memory is explicitly selected."""
import json
import math
import os
from pathlib import Path
import socket
import threading
from urllib.parse import parse_qs, urlsplit
import core
from .client import Client
from .guards import DailyCap, RateLimiter, TTLCache
from . import state
from .urlguard import validate_url, URLValidationError

NO_STORE = 'no-store'
MAX_MARKDOWN = 200 * 1024


def _env_float(name, default):
    try:
        value = float(os.environ.get(name, default))
        return value if math.isfinite(value) and value >= 0 else default
    except ValueError:
        return default


class Converter:
    def __init__(self, client=None, limiter=None, cap=None, cache=None, live=None, resolver=None):
        self._client = client
        memory = os.environ.get('DEMO_STATE') == 'memory' or any(
            item is not None for item in (limiter, cap, cache))
        redis = state.RedisREST() if not memory else None
        self.limiter = limiter if limiter is not None else (
            RateLimiter if memory else lambda **kw: state.Limiter(redis, **kw))(
                per_ip=int(_env_float('DEMO_PER_IP_10MIN', 5)),
                per_ip_day=int(_env_float('DEMO_PER_IP_DAY', 15)),
                global_window=int(_env_float('DEMO_GLOBAL_10MIN', 30)))
        self.cap = cap if cap is not None else (DailyCap(_env_float('DEMO_DAILY_CAP_USD', 1))
            if memory else state.DailyCap(redis, _env_float('DEMO_DAILY_CAP_USD', 1)))
        self.cache = cache if cache is not None else (TTLCache() if memory else state.Cache(redis))
        self.live = os.environ.get('DEMO_LIVE', '1').lower() in ('1', 'true') if live is None else live
        self.fallback_cost = _env_float('DEMO_FALLBACK_COST_USD', .0005)
        self.resolver = resolver or socket.getaddrinfo
        self.lock = threading.Lock()
        self.sample = json.loads((Path(__file__).resolve().parents[1] / 'public/sample.json').read_text())

    def handle(self, query, ip):
        with self.lock:
            try:
                return self._handle(query, ip)
            except state.StateUnavailable:
                return 503, {'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': NO_STORE,
                             'X-Content-Type-Options': 'nosniff'}, json.dumps({**self.sample,
                    'status': 'paused', 'error': 'The live demo is paused. See the saved sample below.',
                    'message': 'The live demo is paused. See the saved sample below.',
                    'sample': '/sample.json', 'cached': False, 'cost_usd_this_request': 0}, ensure_ascii=False)

    def _handle(self, query, ip):
        def out(code, obj):
            return code, {'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': NO_STORE,
                          'X-Content-Type-Options': 'nosniff'}, json.dumps(obj, ensure_ascii=False)
        def sample(code, status, message):
            return out(code, {**self.sample, 'status': status, 'error': message, 'message': message,
                              'sample': '/sample.json', 'cached': False, 'cost_usd_this_request': 0})
        if not self.limiter.allow(ip or 'unknown'):
            return sample(429, 'limited', 'Too many conversions. Try again later; each network has a daily limit too.')
        try:
            url = validate_url(query.get('url'), self.resolver)
        except URLValidationError as e:
            return sample(400, 'invalid', str(e))
        if not self.live:
            return sample(503, 'paused', 'The live demo is paused. See the saved sample below.')
        hit = self.cache.get(url)
        if hit:
            return out(200, {**hit, 'cached': True, 'cost_usd_this_request': 0})
        if not self.cap.ok():
            return sample(503, 'paused', "Today's demo budget is used up. See the saved sample below.")
        try:
            if self._client is None:
                self._client = Client(os.environ.get('DESEARCH_API_KEY', '').strip())
            st, body, rec = self._client.extract(url)
        except RuntimeError:
            return sample(503, 'paused', 'The live demo is paused. See the saved sample below.')
        except (OSError, TimeoutError):
            st, body, rec = 599, '', {'cost_known': False}
        cost = 0 if st in (401, 402, 403, 404) else (rec['cost'] if rec.get('cost_known') else self.fallback_cost)
        self.cap.add(cost)
        try:
            candidates = [rec.get('final_url')]
            if isinstance(body, dict):
                candidates += [body.get(k) for k in ('final_url', 'redirect_url', 'url')]
                for key in ('data', 'result'):
                    if isinstance(body.get(key), dict):
                        candidates += [body[key].get(k) for k in ('final_url', 'redirect_url', 'url')]
            for candidate in candidates:
                if candidate:
                    validate_url(candidate, self.resolver)
        except URLValidationError:
            return sample(400, 'invalid', 'The page redirected to an unsafe address. Try another link.')
        if st in (401, 402, 403):
            return sample(503, 'paused', 'The live demo is paused. See the saved sample below.')
        if st == 404:
            return sample(502, 'error', "Couldn't fetch this page, the site may block bots")
        if st != 200:
            return sample(502, 'error', "We couldn't fetch this page right now. Try another link. Here is a saved sample.")
        content = body
        if isinstance(content, dict):
            content = content.get('data', content.get('result', content))
            if isinstance(content, dict):
                content = content.get('html', content.get('text', content.get('content', '')))
        if not isinstance(content, str):
            content = ''
        title, md, _ = core.html_to_markdown(content, url)
        words = core.word_count(md)
        note = '\n\n[Output truncated at 200 KB.]'
        truncated = len(md.encode()) > MAX_MARKDOWN
        if truncated:
            md = md.encode()[:MAX_MARKDOWN - len(note.encode())].decode('utf-8', 'ignore') + note
        result = dict(title=title, markdown=md, status='empty' if words < 20 else 'ok', words=words,
                      message='This page looks empty (JavaScript-heavy). Try another link.' if words < 20 else '',
                      truncated=truncated, calls=1, cost_usd=cost)
        self.cache.put(url, result)
        return out(200, {**result, 'cached': False, 'cost_usd_this_request': cost})


def client_ip(headers, fallback=''):
    return (headers.get('x-forwarded-for') or headers.get('X-Forwarded-For') or '').split(',')[0].strip() or headers.get('x-real-ip') or fallback


def parse_query(path):
    return {k: v[0] for k, v in parse_qs(urlsplit(path).query, keep_blank_values=True).items()}
