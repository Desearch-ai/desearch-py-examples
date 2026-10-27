"""One fixed Desearch POST, without retries, redirects or logging."""
import http.client
import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def amount(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value >= 0 else None
    except (ValueError, TypeError):
        return None


def shape(rows):
    results = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        link = row.get('link')
        if not isinstance(link, str):
            continue
        try:
            url = urllib.parse.urlsplit(link)
            if url.scheme not in ('http', 'https') or not url.hostname or any(ord(c) <= 32 for c in link):
                continue
            domain = url.hostname.lower().removeprefix('www.')
        except ValueError:
            continue
        title = row.get('title')
        title = title.strip()[:300] if isinstance(title, str) else ''
        snippet = row.get('snippet')
        date = row.get('published_date')
        results.append({'title': title or domain, 'link': link, 'domain': domain,
            'snippet': snippet.strip()[:500] if isinstance(snippet, str) else '',
            'date': date if isinstance(date, str) and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', date) else None})
        if len(results) == 10:
            break
    return results


class Client:
    def __init__(self, key, opener=None):
        if not key:
            raise RuntimeError('Missing server configuration')
        self.key = key
        self.opener = opener or urllib.request.build_opener(NoRedirect()).open

    def search(self, prompt):
        request = urllib.request.Request(
            'https://api.desearch.ai/desearch/ai/search/links/web',
            data=json.dumps({'prompt': prompt, 'tools': ['web'], 'count': 10}).encode(),
            headers={'Authorization': self.key, 'Content-Type': 'application/json',
                'User-Agent': 'desearch-py-examples/web-links-search-demo'}, method='POST')
        try:
            with self.opener(request, timeout=50) as response:
                status, headers, raw = response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            status, headers, raw = error.code, dict(error.headers or {}), error.read()
        except (OSError, urllib.error.URLError, http.client.HTTPException):
            return 599, None, None
        cost = amount({k.lower(): v for k, v in headers.items()}.get('x-desearch-cost-usd'))
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeError):
            return 502, None, cost
        if cost is None and isinstance(body, dict):
            cost = amount(body.get('cost_usd'))
        if status != 200:
            return status, None, cost
        if not isinstance(body, dict) or not isinstance(body.get('search_results'), list):
            return 502, None, cost
        return 200, shape(body['search_results']), cost
