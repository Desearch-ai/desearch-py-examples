"""Two fixed REST routes, no retries, redirects, logging or raw-body retention."""
import json
import math
import re
import urllib.error
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def count(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None


def sanitize(body, posts):
    if not posts:
        body = body.get('data', body) if isinstance(body, dict) else {}
        return {'followers': count(body.get('followers')), 'is_private': body.get('is_private', body.get('private', False))} if isinstance(body, dict) else {}
    if isinstance(body, dict):
        body = next((body[k] for k in ('posts', 'data', 'items', 'results') if isinstance(body.get(k), list)), [])
    cleaned = []
    for post in (body if isinstance(body, list) else [])[:12]:
        if not isinstance(post, dict):
            continue
        stats = post.get('stats') if isinstance(post.get('stats'), dict) else {}
        raw_type = str(post.get('mediaType', post.get('type', ''))).lower()
        kind = {'photo':'image', 'graphimage':'image', '1':'image', 'carousel_album':'carousel', 'sidecar':'carousel', 'graphsidecar':'carousel', '8':'carousel', 'reel':'video', 'reels':'video', 'clips':'video', 'graphvideo':'video', '2':'video'}.get(raw_type, raw_type)
        if kind not in ('image', 'carousel', 'video'):
            kind = 'carousel' if post.get('children') else 'image'
        code = post.get('shortcode', '')
        url = 'https://www.instagram.com/p/' + code + '/' if isinstance(code, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,100}', code) else ''
        cleaned.append({'url': url, 'type': kind, 'likes': count(stats.get('likeCount', post.get('likes'))), 'comments': count(stats.get('commentCount', post.get('comments'))), 'taken_at': post.get('createTime', post.get('taken_at'))})
    return cleaned


class Client:
    def __init__(self, key, opener=None):
        if not key:
            raise RuntimeError('Missing server configuration')
        self.key = key
        self.opener = opener or urllib.request.build_opener(NoRedirect()).open

    def fetch(self, handle, posts=False, timeout=45):
        path = '/desearch/instagram/profile/' + handle + ('/posts?count=12' if posts else '')
        request = urllib.request.Request('https://api.desearch.ai' + path, headers={'Authorization': self.key}, method='GET')
        try:
            with self.opener(request, timeout=timeout) as response:
                status, headers, raw = response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            status, headers, raw = error.code, dict(error.headers or {}), error.read()
        except (OSError, TimeoutError, urllib.error.URLError):
            return 599, None, None
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeError):
            body = {}
        headers = {k.lower(): v for k, v in headers.items()}
        cost = None
        for value in (headers.get('x-desearch-cost-usd'), body.get('cost_usd') if isinstance(body, dict) else None):
            try:
                value = float(value)
                if math.isfinite(value) and value >= 0:
                    cost = value
                    break
            except (ValueError, TypeError):
                pass
        return status, sanitize(body, posts), cost
