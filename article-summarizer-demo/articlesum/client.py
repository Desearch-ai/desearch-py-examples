"""One Extract GET, no retries, redirects, URL logs or disk writes."""
import http.client
import json
import math
import urllib.error
import urllib.parse
import urllib.request


def connection_status(error):
    """Reserve 599 for actual timeouts, including urllib's wrapped reason."""
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    return 599 if isinstance(reason, TimeoutError) else 598


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, key, opener=None):
        if not key:
            raise RuntimeError('Missing server configuration')
        self.key = key
        self.opener = opener or urllib.request.build_opener(NoRedirect()).open

    def extract(self, url):
        query = urllib.parse.urlencode({'url': url, 'format': 'text', 'js': 'false'})
        req = urllib.request.Request('https://api.desearch.ai/web/extract?' + query,
                                     headers={'Authorization': self.key, 'User-Agent': 'desearch-py-examples/article-summarizer-demo'})
        try:
            with self.opener(req, timeout=50) as r:
                status, headers, raw = r.status, dict(r.headers), r.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            status, headers, raw = e.code, dict(e.headers or {}), e.read().decode('utf-8', 'replace')
        except (OSError, urllib.error.URLError, http.client.HTTPException) as e:
            return connection_status(e), '', None
        try:
            body = json.loads(raw)
        except ValueError:
            body = raw
        hd = {k.lower(): v for k, v in headers.items()}
        rec = {'cost': 0, 'cost_known': False}
        for value in (hd.get('x-desearch-cost-usd'), body.get('cost_usd') if isinstance(body, dict) else None):
            try:
                cost = float(value)
                if math.isfinite(cost) and cost >= 0:
                    rec.update(cost=cost, cost_known=True)
                    break
            except (ValueError, TypeError):
                pass
        return status, raw, rec['cost'] if rec['cost_known'] else None
