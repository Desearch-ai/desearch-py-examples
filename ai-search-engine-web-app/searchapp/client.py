"""Plain-HTTP Desearch client (standard library). The key is only ever sent in the Authorization header."""
import datetime as dt, json, os, pathlib, sys, threading, time, urllib.error, urllib.parse, urllib.request

BASE = "https://api.desearch.ai"
UA = "ai-search-engine-web-app/0.1 (+made-by-desearch)"


def api_key(key_file=None):
    """Key from --key-file, DESEARCH_API_KEY_FILE, or DESEARCH_API_KEY (production: env var set on the host)."""
    path = key_file or os.environ.get("DESEARCH_API_KEY_FILE")
    k = pathlib.Path(path).read_text().strip() if path else os.environ.get("DESEARCH_API_KEY", "").strip()
    return k or None


class Client:
    """One method per endpoint. If `log_dir` is set, each call is saved (key redacted) to raw/ and calls.jsonl."""

    def __init__(self, key, log_dir=None, timeout=45, quiet=False):
        if not key:
            raise RuntimeError("no Desearch API key: set DESEARCH_API_KEY_FILE or DESEARCH_API_KEY")
        self.key, self.n, self.total, self.timeout, self.quiet = key, 0, 0.0, timeout, quiet
        self.lock = threading.Lock()
        self.log = pathlib.Path(log_dir) if log_dir else None
        if self.log:
            (self.log / "raw").mkdir(parents=True, exist_ok=True)

    def _write(self, path, text, mode="w"):
        if self.key in text:
            raise RuntimeError("refusing to write a file that contains the API key")
        with open(path, mode) as f:
            f.write(text)

    def _call(self, method, path, tag, params=None, payload=None):
        with self.lock:
            self.n += 1
            n = self.n
        url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
        data = json.dumps(payload).encode() if payload is not None else None
        hdr = {"Authorization": self.key, "User-Agent": UA}
        if data is not None:
            hdr["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=hdr)
        import math
        import http.client
        ts = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        t0 = time.perf_counter()
        try:
            r = urllib.request.urlopen(req, timeout=self.timeout)
            st, hd, raw = r.status, dict(r.headers), r.read().decode()
        except urllib.error.HTTPError as e:
            st, hd, raw = e.code, dict(e.headers), e.read().decode()
        except (OSError, urllib.error.URLError, TimeoutError, http.client.HTTPException):
            st, hd, raw = 599, {}, json.dumps({"detail": "network error"})
        lat = round(time.perf_counter() - t0, 2)
        try:
            body = json.loads(raw)
        except ValueError:
            body = raw[:2000]
        bill = {k.lower(): v for k, v in hd.items() if k.lower().startswith("x-desearch")}
        # POST /search sends no X-Desearch-* headers (2026-10-19), only cost_usd in the body. Header first, then the
        # body's cost_usd; if neither is there the cost is unknown (not zero) and the service counts a fallback.
        body_cost = body.get("cost_usd") if isinstance(body, dict) else None
        cost, cost_known, cost_source = 0.0, False, "none"
        for src, v in (("header", bill.get("x-desearch-cost-usd")), ("body", body_cost)):
            try:
                value = float(v)
                if math.isfinite(value) and value >= 0:
                    cost, cost_known, cost_source = value, True, src
                    break
            except (TypeError, ValueError):
                continue
        cost = round(cost, 6)
        self.total += cost
        rec = {"n": n, "tag": tag, "time": ts, "request": {"method": method, "url": url, "body": payload,
               "headers": {"Authorization": "<redacted>", "User-Agent": UA}}, "status": st, "latency_s": lat,
               "billing_headers": bill, "body_cost_usd": body_cost, "cost": cost, "cost_source": cost_source,
               "cost_known": cost_known}
        if self.log:
            self._write(self.log / "raw" / f"{n:03d}-{tag}.json", json.dumps({**rec, "body": body}, indent=1, ensure_ascii=False))
            self._write(self.log / "calls.jsonl", json.dumps(rec) + "\n", "a")
        if not self.quiet:
            print(f"[{ts}] {st} {method} {path} {tag} {lat}s cost={cost}", file=sys.stderr)
        return st, body, rec

    def ai_search(self, payload, tag="ai-search"):
        return self._call("POST", "/desearch/ai/search", tag, payload=payload)

    def search(self, payload, tag="search"):
        """POST /search: ranked pages with published_date and the best-matching passage (highlights)."""
        return self._call("POST", "/search", tag, payload=payload)
