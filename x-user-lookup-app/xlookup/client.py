"""One fixed Desearch GET, without retries, redirects or logging."""
import http.client
import json
import math
import urllib.error
import urllib.parse
import urllib.request
import core


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def amount(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value >= 0 else None
    except (ValueError, TypeError):
        return None


class Client:
    def __init__(self, key, opener=None):
        if not key:
            raise RuntimeError('Missing server configuration')
        self.key = key
        self.opener = opener or urllib.request.build_opener(NoRedirect()).open

    def lookup(self, username):
        request = urllib.request.Request(
            'https://api.desearch.ai/twitter/user/posts?' + urllib.parse.urlencode({'username': username}),
            headers={'Authorization': self.key, 'User-Agent': 'desearch-py-examples/x-user-lookup-app'}, method='GET')
        try:
            with self.opener(request, timeout=45) as response:
                status, headers, raw = response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            status, headers, raw = error.code, dict(error.headers or {}), error.read()
        except (OSError, urllib.error.URLError, http.client.HTTPException):
            return 599, None, None
        cost = amount({k.lower(): v for k, v in headers.items()}.get('x-desearch-cost-usd'))
        # A missing account uses only the cost header, never error-body metadata.
        if status == 404:
            return 404, None, cost if cost is not None else 0
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeError):
            return 502, None, cost
        if cost is None and isinstance(body, dict):
            cost = amount(body.get('cost_usd'))
        if status != 200:
            return status, None, cost
        if not isinstance(body, dict) or not isinstance(body.get('tweets'), list):
            return 502, None, cost
        if body.get('user') is not None and not isinstance(body['user'], dict):
            return 502, None, cost
        posts, _ = core.merge([core.tweets_of(body)])
        return status, {'profile': core.profile(body, username), 'posts': posts}, cost
