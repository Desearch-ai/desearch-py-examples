"""One fixed Desearch GET, without retries, redirects or logging."""
import json
import math
import urllib.error
import urllib.parse
import urllib.request


PER_PAGE = 20


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Client:
    def __init__(self, key, opener=None):
        if not key:
            raise RuntimeError('Missing server configuration')
        self.key = key
        self.opener = opener or urllib.request.build_opener(NoRedirect()).open

    def search(self, query, page):
        params = urllib.parse.urlencode({'query': query, 'start': (page - 1) * PER_PAGE})
        request = urllib.request.Request('https://api.desearch.ai/web?' + params,
            headers={'Authorization': self.key, 'User-Agent': 'desearch-py-examples/web-search-demo'}, method='GET')
        try:
            with self.opener(request, timeout=45) as response:
                status, headers, raw = response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            status, headers, raw = error.code, dict(error.headers or {}), error.read()
        except (OSError, urllib.error.URLError):
            return 599, None, None
        cost = None
        try:
            value = float({k.lower(): v for k, v in headers.items()}.get('x-desearch-cost-usd'))
            if math.isfinite(value) and value >= 0:
                cost = value
        except (ValueError, TypeError):
            pass
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeError):
            return 502, None, cost
        rows = body.get('data') if isinstance(body, dict) else body
        if not isinstance(rows, list):
            return 502, None, cost
        # Project onto public fields; never return upstream error bodies or metadata.
        results = [{k: row.get(k, '') if isinstance(row.get(k, ''), str) else ''
                    for k in ('title', 'link', 'snippet')}
                   for row in rows[:PER_PAGE] if isinstance(row, dict)]
        return status, results, cost
