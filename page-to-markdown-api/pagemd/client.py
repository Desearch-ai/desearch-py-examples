"""One Extract GET, no retries, redirects, URL logs or disk writes."""
import json
import math
import urllib.error
import urllib.parse
import urllib.request


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
        query = urllib.parse.urlencode({'url': url, 'format': 'html', 'js': 'false'})
        req = urllib.request.Request('https://api.desearch.ai/web/extract?' + query,
                                     headers={'Authorization': self.key, 'User-Agent': 'page-to-markdown/0.1 (+https://desearch.ai)'})
        try:
            with self.opener(req, timeout=45) as r:
                status, headers, raw = r.status, dict(r.headers), r.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            status, headers, raw = e.code, dict(e.headers or {}), e.read().decode('utf-8', 'replace')
        except (OSError, TimeoutError, urllib.error.URLError):
            return 599, '', {'cost': 0, 'cost_known': False}
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
        if hd.get('location'):
            rec['final_url'] = urllib.parse.urljoin(url, hd['location'])
        return status, body, rec
