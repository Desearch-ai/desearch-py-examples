"""Network-free logic for the Web Search API Quickstart: query check, paging, result normalizing, dedupe, cache, HTML."""
import html, time, urllib.parse

MAX_QUERY = 300
PAGE_STEP = 20   # a GET /web page held up to 20 results in our runs, so page 2 is start=20
MAX_PAGES = 3    # start 0, 20, 40 (the API caps start at 100)
CACHE_TTL = 600  # seconds


class FormError(ValueError):
    pass


def clean_query(s):
    """Collapses whitespace. Raises FormError before any paid call (a blank query is billed by the API)."""
    q = " ".join(str(s or "").split())
    if not q:
        raise FormError("Enter a search query.")
    if len(q) > MAX_QUERY:
        raise FormError(f"A query is at most {MAX_QUERY} characters.")
    return q


def pages_value(s):
    s = (str(s) if s is not None else "").strip() or "1"
    if not s.isdigit() or not 1 <= int(s) <= MAX_PAGES:
        raise FormError(f"Pages must be 1 to {MAX_PAGES}.")
    return int(s)


def starts(pages):
    return [i * PAGE_STEP for i in range(pages)]


def params(query, start=0):
    return {"query": query, "start": start}


def domain_of(url):
    host = (urllib.parse.urlsplit(url or "").hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def norm_url(url):
    """Key for dedupe: lowercase host without www, no fragment, no trailing slash."""
    p = urllib.parse.urlsplit((url or "").strip())
    path = p.path.rstrip("/") or "/"
    return f"{domain_of(url)}{path}" + (f"?{p.query}" if p.query else "")


def items_of(body):
    if isinstance(body, dict) and isinstance(body.get("data"), list):
        return [x for x in body["data"] if isinstance(x, dict)]
    return []


def normalize(item):
    url = str(item.get("link") or item.get("url") or "").strip()
    return {"title": " ".join(str(item.get("title") or "").split()), "url": url,
            "snippet": " ".join(str(item.get("snippet") or "").split()), "domain": domain_of(url)}


def merge(pages):
    """pages: list of raw item lists. Returns (results, per_page_new, repeats). Keeps first seen, drops items with no URL."""
    seen, out, per_page, repeats = set(), [], [], 0
    for items in pages:
        new = 0
        for it in items:
            r = normalize(it)
            if not r["url"]:
                continue
            k = norm_url(r["url"])
            if k in seen:
                repeats += 1
                continue
            seen.add(k)
            r["rank"] = len(out) + 1
            out.append(r)
            new += 1
        per_page.append(new)
    return out, per_page, repeats


class TTLCache:
    """Small in-memory cache. `clock` is injectable for tests."""

    def __init__(self, ttl=CACHE_TTL, clock=time.monotonic, max_items=256):
        self.ttl, self.clock, self.max, self.d = ttl, clock, max_items, {}

    def get(self, key):
        v = self.d.get(key)
        if not v:
            return None
        if self.clock() - v[0] >= self.ttl:
            del self.d[key]
            return None
        return v[1]

    def put(self, key, value):
        if len(self.d) >= self.max:
            del self.d[min(self.d, key=lambda k: self.d[k][0])]
        self.d[key] = (self.clock(), value)


def cache_key(query, pages):
    return (query.lower(), pages)


def render_page(form, results=None, info=None, error=None):
    e = lambda s: html.escape(str(s), quote=True)
    parts = ["<!doctype html><meta charset=utf-8><title>Web Search API Quickstart</title>",
             "<style>body{font:15px system-ui;max-width:860px;margin:2em auto}.err{color:#b00}.d{color:#070}.s{color:#444}li{margin:.7em 0}</style>",
             "<h1>Web Search API Quickstart</h1><form method=get action=/>",
             f"<p><input name=q size=50 placeholder='search the web' value='{e(form.get('q', ''))}'> "
             f"<label>Pages <input name=pages size=2 value='{e(form.get('pages') or 1)}'></label> <button>Search</button></p></form>"]
    if error:
        parts.append(f"<p class=err>{e(error)}</p>")
    if info:
        parts.append(f"<p class=s>{info['count']} results, {'from cache' if info['cached'] else str(info['calls']) + ' API call(s)'}. "
                     f"JSON: <a href='{e(info['json_href'])}'>{e(info['json_href'])}</a></p>")
    if results is not None:
        if not results:
            parts.append("<p>No results returned.</p>")
        parts.append("<ol>")
        for r in results:
            parts.append(f"<li><a href='{e(r['url'])}'>{e(r['title'] or r['url'])}</a> <span class=d>{e(r['domain'])}</span>"
                         f"<br><span class=s>{e(r['snippet'])}</span></li>")
        parts.append("</ol>")
    return "".join(parts)
