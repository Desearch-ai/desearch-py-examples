"""Standard library client. Credentials are read only at runtime from the environment."""
import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.desearch.ai"
UA = "ai-news-today-board/0.1 (+made-by-desearch)"


def api_key():
    key = os.environ.get("DESEARCH_API_KEY", "").strip()
    if not key:
        raise RuntimeError("not configured")
    return key


class Client:
    def __init__(self, key, timeout=45):
        self.key, self.timeout = key, timeout

    def _call(self, method, path, params=None, payload=None):
        url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
        data = json.dumps(payload).encode() if payload is not None else None
        hdr = {"Authorization": self.key, "User-Agent": UA, "Content-Type": "application/json"}
        req = urllib.request.Request(url, data=data, method=method,
                                     headers=hdr)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                status, headers, raw = response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            status, headers, raw = error.code, dict(error.headers), error.read()
        except (urllib.error.URLError, TimeoutError, OSError):
            return 599, {}, {"cost": 0, "cost_known": False}
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            body = {}
        headers = {k.lower(): v for k, v in headers.items()}
        cost, known = 0.0, False
        for value in (headers.get("x-desearch-cost-usd"), body.get("cost_usd") if isinstance(body, dict) else None):
            try:
                candidate = float(value)
                if math.isfinite(candidate) and candidate >= 0:
                    cost, known = candidate, True
                    break
            except (ValueError, TypeError):
                pass
        return status, body, {"cost": round(cost, 6), "cost_known": known}

    def x_search(self, params, tag="x"):
        return self._call("GET", "/twitter", params=params)

    def ai_search(self, payload, tag="web"):
        return self._call("POST", "/desearch/ai/search", payload=payload)
