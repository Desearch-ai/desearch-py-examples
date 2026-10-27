"""Network-free logic for the AI Search Engine web app: input checks, request bodies, result cleanup, the
answer citation check, and the demo limits (per-IP limiter, daily spend cap, cache)."""
import collections, datetime as dt, json, re, threading, time, urllib.parse

MIN_Q, MAX_Q = 2, 300          # the API accepts 1-2000 chars; the demo keeps queries short
MODES = ("fast", "balanced")
COUNTS = (10, 15, 20)
RANGES = {"any": None, "day": 1, "week": 7, "month": 31, "year": 365}
PASSAGE_CHARS = 420
STRONG_SHARE = 0.6             # an answer link "matches" when its title/snippet holds 60% of the query's key terms
MIN_STRONG = 2
STOP = set("""a an the is are was were be been being of to in on at by for with from as and or but not no nor this that
these those it its into than then so such can could will would should may might must do does did has have had about
over under more most less very just also only there their they them he she his her we you your i me my our what which
who whom whose when where why how all any each both few other some own same too up down out off again here per via vs
if best new latest""".split())
CITE = re.compile(r"\[(\d+)\]\((https?://[^)\s]+)\)")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Fixed reply the answer service gives when it declines to summarize (seen 2 of 2 times on 2026-10-19)
DECLINED = re.compile(r"closest on-topic source reviewed", re.I)


class FormError(ValueError):
    pass


def _txt(s):
    return " ".join(str(s or "").split())


def clean_query(s):
    """Collapses whitespace and checks the query before any paid call. A whitespace-only query got a 503 from the
    API and a made-up one is billed like a real search, so junk is stopped here."""
    q = _txt(s)
    if not q:
        raise FormError("Type something to search for.")
    if len(q) < MIN_Q:
        raise FormError(f"A search is at least {MIN_Q} characters.")
    if len(q) > MAX_Q:
        raise FormError(f"A search is at most {MAX_Q} characters.")
    if not re.search(r"\w", q):
        raise FormError("A search needs at least one letter or number.")
    return q


def parse_mode(v):
    v = (str(v or "fast")).strip().lower()
    if v not in MODES:
        raise FormError("mode is fast or balanced.")
    return v


def parse_count(v):
    try:
        n = int(v or 10)
    except (TypeError, ValueError):
        raise FormError("count is 10, 15 or 20.")
    if n not in COUNTS:
        raise FormError("count is 10, 15 or 20.")
    return n


def _date(v, name):
    v = str(v or "").strip()
    if not v:
        return None
    if not DATE.match(v):
        raise FormError(f"{name} is a date like 2026-10-01.")
    try:
        dt.date.fromisoformat(v)
    except ValueError:
        raise FormError(f"{name} is not a real date.")
    return v


def date_window(range_=None, start=None, end=None, today=None):
    """Returns (start_date, end_date) as YYYY-MM-DD or None. `range` (day/week/month/year, counted back from today in
    UTC) or explicit from/to. The API filters on the page's published date."""
    today = today or dt.datetime.now(dt.timezone.utc).date()
    s, e = _date(start, "from"), _date(end, "to")
    r = str(range_ or "").strip().lower()
    if r and r != "custom":
        if r not in RANGES:
            raise FormError("range is any, day, week, month, year or custom.")
        if s or e:
            raise FormError("Use either a range or from/to dates, not both.")
        days = RANGES[r]
        return ((today - dt.timedelta(days=days)).isoformat(), None) if days else (None, None)
    if s and e and s > e:
        raise FormError("from must be on or before to.")
    return s, e


def search_body(q, mode="fast", count=10, start=None, end=None):
    """POST /search body (live OpenAPI 2026-10-19). highlights=true returns the best-matching passage."""
    b = {"query": q, "mode": mode, "count": count, "highlights": True}
    if start:
        b["start_date"] = start
    if end:
        b["end_date"] = end
    return b


def answer_body(q):
    """POST /desearch/ai/search body for the Answer button: web only, one JSON response with links + completion."""
    return {"prompt": q, "tools": ["web"], "streaming": False, "result_type": "LINKS_WITH_FINAL_SUMMARY", "count": 10}


def cache_key(kind, **parts):
    norm = {k: (" ".join(re.sub(r"[^\w\s'.-]", " ", str(v).lower()).split()) if k == "q" else v) for k, v in parts.items() if v not in (None, "")}
    return kind + "|" + json.dumps(norm, sort_keys=True)


def norm_url(u):
    return urllib.parse.unquote(str(u or "")).rstrip("/")


def passage(highlights, limit=PASSAGE_CHARS):
    """First highlight with whitespace collapsed and cut at a word boundary. Text is otherwise shown as returned."""
    hs = [_txt(h) for h in (highlights or []) if _txt(h)] if isinstance(highlights, list) else []
    if not hs:
        return ""
    h = hs[0]
    if len(h) <= limit:
        return h
    cut = h[:limit].rsplit(" ", 1)[0]
    return cut + " ..."


def clean_results(body, start=None, end=None):
    """Normalize POST /search results: rank as returned, dedupe by URL, flag missing and out-of-window dates."""
    items = body.get("results") if isinstance(body, dict) else None
    out, seen, dup = [], set(), 0
    for it in items or []:
        if not isinstance(it, dict):
            continue
        url = _txt(it.get("url"))
        if not url:
            continue
        k = norm_url(url)
        if k in seen:
            dup += 1
            continue
        seen.add(k)
        d = _txt(it.get("published_date"))[:10] or None
        in_window = None if not d else ((not start or d >= start) and (not end or d <= end))
        out.append({"rank": len(out) + 1, "title": _txt(it.get("title")) or url, "url": url,
                    "domain": (urllib.parse.urlsplit(url).hostname or "").removeprefix("www."),
                    "published_date": d, "passage": passage(it.get("highlights")), "in_window": in_window})
    stats = {"returned": len(items or []), "shown": len(out), "duplicates": dup,
             "no_date": sum(1 for r in out if not r["published_date"]),
             "outside_window": sum(1 for r in out if r["in_window"] is False)}
    return out, stats


def key_terms(text):
    out = []
    for w in re.findall(r"[a-z0-9][a-z0-9'.\-]*", str(text).lower()):
        w = w.strip("'.-")
        if len(w) > 1 and w not in STOP and w not in out:
            out.append(w)
    return out


def check_citations(completion, links):
    """Splits the completion into sentences and keeps those whose [n](url) citations all point at a link the same
    answer call returned. Uncited or mis-cited sentences are hidden and counted."""
    urls = {norm_url(u) for u in links}
    text = _txt(completion)
    if not text:
        return {"lines": [], "hidden": 0, "cited_urls": []}
    keep, hidden, cited = [], 0, []
    for p in re.split(r"(?<=[.!?])\s+(?=[A-Z\[])", text):
        cs = CITE.findall(p)
        ok = bool(cs) and all(norm_url(u) in urls for _, u in cs)
        if ok:
            keep.append({"text": re.sub(r"\s+([.,;:!?])", r"\1", CITE.sub("", p)).strip(), "cites": [u for _, u in cs]})
            cited += [u for _, u in cs if u not in cited]
        elif cs and not CITE.sub("", p).strip(" .") and keep and all(norm_url(u) in urls for _, u in cs):
            keep[-1]["cites"] += [u for _, u in cs]          # trailing citation-only fragment
        elif cs or len(p) > 3:
            hidden += 1
    return {"lines": keep, "hidden": hidden, "cited_urls": cited}


def build_answer(q, body, search_urls=None):
    """Answer panel data. The completion is shown only as sentences tied to the answer's own links. 'no strong
    sources' when fewer than two links hold most of the query's key terms. 'declined' when the service sent its fixed
    "Closest on-topic source reviewed" reply instead of a summary."""
    items = [x for x in (body.get("search") or []) if isinstance(x, dict) and x.get("link")] if isinstance(body, dict) else []
    terms = key_terms(q)
    links, seen = [], set()
    for x in items:
        u = _txt(x.get("link"))
        if norm_url(u) in seen:
            continue
        seen.add(norm_url(u))
        text = " ".join([_txt(x.get("title")), _txt(x.get("snippet"))]).lower()
        share = (sum(1 for w in terms if w in text) / len(terms)) if terms else 0.0
        links.append({"n": len(links) + 1, "title": _txt(x.get("title")) or u, "url": u,
                      "domain": (urllib.parse.urlsplit(u).hostname or "").removeprefix("www."),
                      "published_date": (_txt(x.get("published_date"))[:10] or None), "term_share": round(share, 2)})
    comp = _txt(body.get("completion") if isinstance(body, dict) else "")
    declined = bool(DECLINED.search(comp))
    if declined:   # show what the service said, quoted without its citation, and no summary lines
        summ = {"lines": [], "hidden": 0, "cited_urls": [u for _, u in CITE.findall(comp)]}
    else:
        summ = check_citations(comp, [l["url"] for l in links])
    strong = sum(1 for l in links if l["term_share"] >= STRONG_SHARE)
    su = {norm_url(u) for u in (search_urls or [])}
    return {"query": q, "links": links, "summary": summ, "strong": strong, "declined": declined,
            "declined_text": comp[:DECLINED.search(comp).start()].strip() if declined else "",
            "no_strong_sources": strong < MIN_STRONG,
            "also_in_search_results": sum(1 for l in links if norm_url(l["url"]) in su) if search_urls else None}


class RateLimiter:
    """Sliding-window per-IP and global limits, in memory. On serverless hosts this is per warm instance only."""

    def __init__(self, per_ip=10, window=600, per_ip_day=40, global_window=60, clock=time.time):
        self.per_ip, self.window, self.per_ip_day, self.global_window, self.clock = per_ip, window, per_ip_day, global_window, clock
        self.hits, self.lock = collections.defaultdict(list), threading.Lock()

    def allow(self, ip):
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
    """Stops paid calls once today's cost reaches `cap_usd`. Day boundary is UTC. Per process / instance."""

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
        self.ttl, self.clock, self.max, self.d, self.lock = ttl, clock, max_items, collections.OrderedDict(), threading.Lock()

    def get(self, k):
        with self.lock:
            v = self.d.get(k)
            if v and self.clock() - v[0] < self.ttl:
                return v[1]
            self.d.pop(k, None)
            return None

    def put(self, k, val):
        with self.lock:
            self.d[k] = (self.clock(), val)
            self.d.move_to_end(k)
            while len(self.d) > self.max:
                self.d.popitem(last=False)


def to_json(payload):
    return json.dumps(payload, indent=1, ensure_ascii=False)
