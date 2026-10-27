import collections, threading, time
from .state import ip_bucket

class RateLimiter:
    """Sliding-window per-IP and global limits, in memory. On serverless hosts this is per warm instance only."""

    def __init__(self, per_ip=5, window=600, per_ip_day=15, global_window=30, clock=time.time):
        self.per_ip, self.window, self.per_ip_day, self.global_window, self.clock = per_ip, window, per_ip_day, global_window, clock
        self.hits, self.lock = collections.defaultdict(list), threading.Lock()

    def allow(self, ip):
        ip = ip_bucket(ip)
        now = self.clock()
        with self.lock:
            h = self.hits[ip] = [t for t in self.hits[ip] if now - t < 86400]
            recent = [t for t in h if now - t < self.window]
            total = sum(1 for hs in self.hits.values() for t in hs if now - t < self.window)
            if len(recent) >= self.per_ip or len(h) >= self.per_ip_day or total >= self.global_window:
                return False
            h.append(now)
            return True


class DailyCap:
    """Stops paid calls once today's header cost reaches `cap_usd`. Day boundary is UTC. Per process / instance."""

    def __init__(self, cap_usd=1.0, clock=time.time):
        self.cap, self.clock, self.day, self.spent, self.lock = cap_usd, clock, None, 0.0, threading.Lock()

    def _roll(self):
        d = time.strftime("%Y-%m-%d", time.gmtime(self.clock()))
        if d != self.day:
            self.day, self.spent = d, 0.0

    def ok(self):
        with self.lock:
            self._roll()
            return self.spent < self.cap

    def add(self, usd):
        with self.lock:
            self._roll()
            self.spent += float(usd or 0)


class TTLCache:
    def __init__(self, ttl=900, clock=time.monotonic, max_items=500):
        self.ttl, self.clock, self.max, self.d = ttl, clock, max_items, collections.OrderedDict()

    def get(self, k):
        v = self.d.get(k)
        if v and self.clock() - v[0] < self.ttl:
            return v[1]
        self.d.pop(k, None)
        return None

    def put(self, k, val):
        self.d[k] = (self.clock(), val)
        self.d.move_to_end(k)
        while len(self.d) > self.max:
            self.d.popitem(last=False)
