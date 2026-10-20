"""Shared per-IP, global and daily-USD counters in Upstash Redis (REST, stdlib urllib only).

Fixed windows: 10 minute keys are named by the window start, daily keys by the UTC day.
Each key is one transaction: INCR (or INCRBYFLOAT for the USD cap) and EXPIRE together,
with a TTL equal to that window. The token is sent only in the Authorization header.

If the store is not configured on a local run, `load` returns (None, None) and the
caller keeps the in-memory limiter and cap. On Vercel (`VERCEL` set, or `VERCEL_ENV`
of production or preview) a missing store fails closed. A configured store that errors
raises StoreError. This module never logs the token, the claim text or the IP.
"""
import hashlib, json, os, sys, threading, time, urllib.error, urllib.request

WINDOW = 600
DAY = 86400
FALLBACK_IP_SALT = "desearch-ai-fact-checker"
_warned = False
_closed_warned = False


class StoreError(Exception):
    """The shared store is configured, but a call failed."""


def _env(name):
    return (os.environ.get(name) or "").strip()


def credentials():
    """Server-side only. KV_* (Vercel Marketplace / KV) wins, then UPSTASH_REDIS_REST_*."""
    url = _env("KV_REST_API_URL") or _env("UPSTASH_REDIS_REST_URL")
    token = _env("KV_REST_API_TOKEN") or _env("UPSTASH_REDIS_REST_TOKEN")
    return (url, token) if url and token else None


def ip_hash(ip):
    """sha256 of the salt and the IP. The raw address is never used in a key name."""
    salt = _env("DEMO_IP_SALT") or FALLBACK_IP_SALT
    return hashlib.sha256(f"{salt}\n{ip or ''}".encode()).hexdigest()


def on_vercel():
    """True when this process is a Vercel function (production, preview, or `VERCEL` set)."""
    if _env("VERCEL"):
        return True
    return _env("VERCEL_ENV").lower() in ("production", "preview")


def hosted_without_store():
    """Vercel with neither KV_REST_API_* nor UPSTASH_REDIS_REST_* configured."""
    return on_vercel() and credentials() is None


def warn_fallback_once():
    """One line on a local run with no shared store. No token, claim or IP."""
    global _warned
    if _warned:
        return
    _warned = True
    print("[check] warning: shared limit store is not configured; using in-memory counters", file=sys.stderr)


def warn_closed_once():
    """One line when a hosted run has no shared store. No token, claim or IP."""
    global _closed_warned
    if _closed_warned:
        return
    _closed_warned = True
    print("[check] warning: shared limit store is not configured; refusing live checks", file=sys.stderr)


class ClosedStore:
    """Hosted process with no shared store. Every counter operation fails closed."""

    spent = 0.0

    def ok(self):
        raise StoreError("unconfigured")

    def allow(self, ip):
        raise StoreError("unconfigured")

    def add(self, usd):
        raise StoreError("unconfigured")


def load(per_ip, per_ip_day, global_window, cap_usd):
    """Return (limiter, cap). Redis when configured, closed on Vercel if not, else memory."""
    creds = credentials()
    if creds:
        url, token = creds
        shared = SharedLimits(url, token, per_ip, per_ip_day, global_window, cap_usd)
        return shared, shared
    if on_vercel():
        warn_closed_once()
        closed = ClosedStore()
        return closed, closed
    warn_fallback_once()
    return None, None


def _day(now):
    return time.strftime("%Y-%m-%d", time.gmtime(now))


class SharedLimits:
    """Rate limits and the daily USD cap. `allow` / `ok` run before a paid call; `add` records cost after it."""

    def __init__(self, url, token, per_ip, per_ip_day, global_window, cap_usd, clock=time.time, timeout=4):
        self.url, self.token = url.rstrip("/"), token
        self.per_ip, self.per_ip_day, self.global_window = per_ip, per_ip_day, global_window
        self.cap, self.clock, self.timeout = cap_usd, clock, timeout
        self.spent, self.lock = 0.0, threading.Lock()

    def allow(self, ip):
        now = self.clock()
        start = int(now) // WINDOW * WINDOW
        day, h = _day(now), ip_hash(ip)
        if self._incr(f"factcheck:ip10:{h}:{start}", WINDOW) > self.per_ip:
            return False
        if self._incr(f"factcheck:ipday:{h}:{day}", DAY) > self.per_ip_day:
            return False
        if self._incr(f"factcheck:g10:{start}", WINDOW) > self.global_window:
            return False
        return True

    def ok(self):
        raw = self._exec([["GET", self._usd_key()]])[0]
        spent = 0.0 if raw is None else round(float(raw), 6)
        with self.lock:
            self.spent = spent
        return spent < round(float(self.cap), 6)

    def add(self, usd):
        key = self._usd_key()
        amount = f"{round(float(usd or 0), 6):.6f}"
        raw = self._exec([["INCRBYFLOAT", key, amount], ["EXPIRE", key, DAY, "NX"]])[0]
        with self.lock:
            self.spent = round(float(raw), 6)

    def _usd_key(self):
        return f"factcheck:usd:{_day(self.clock())}"

    def _incr(self, key, ttl):
        return int(self._exec([["INCR", key], ["EXPIRE", key, int(ttl), "NX"]])[0])

    def _exec(self, commands):
        """One transaction. The token is not placed in the URL and is not logged."""
        req = urllib.request.Request(
            self.url + "/multi-exec", data=json.dumps(commands).encode(), method="POST",
            headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            try:
                e.read()
            except Exception:
                pass
            raise StoreError("http") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise StoreError("network") from None
        try:
            body = json.loads(raw.decode())
        except (ValueError, UnicodeError):
            raise StoreError("bad-response") from None
        if isinstance(body, dict) or not isinstance(body, list) or len(body) != len(commands):
            raise StoreError("redis") from None
        out = []
        for item in body:
            if not isinstance(item, dict) or item.get("error") or "result" not in item:
                raise StoreError("redis") from None
            out.append(item["result"])
        return out
