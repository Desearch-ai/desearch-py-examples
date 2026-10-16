"""Network-free logic for the Hacker News Search App: input checks, request body, HN item filter, dedupe, exports, HTML."""
import csv, html, io, json, re, urllib.parse

MAX_QUERY = 300
COUNTS = (10, 20, 30)   # results asked per call (the API minimum is 10)
DATE_FILTERS = ("", "PAST_WEEK", "PAST_MONTH", "PAST_YEAR")
ITEM_RE = re.compile(r"^https?://news\.ycombinator\.com/item\?(?:.*&)?id=(\d+)(?:&|$)")
FIELDS = ["rank", "item_id", "title", "url", "snippet", "highlights"]


class FormError(ValueError):
    pass


def clean_query(s):
    """Collapses whitespace and checks length. Raises FormError before any paid call."""
    q = " ".join(str(s or "").split())
    if not q:
        raise FormError("Enter a search topic.")
    if len(q) > MAX_QUERY:
        raise FormError(f"A topic is at most {MAX_QUERY} characters.")
    if q.count("(") != q.count(")"):
        raise FormError("Parentheses are not balanced.")
    return q


def or_query(terms):
    """Joins alternative terms as one group in parentheses: (a OR b OR c)."""
    ts = [" ".join(str(t).split()) for t in terms]
    ts = [t for t in ts if t]
    if not ts:
        raise FormError("Give at least one term.")
    return ts[0] if len(ts) == 1 else "(" + " OR ".join(ts) + ")"


def count_value(s):
    s = (str(s) if s is not None else "").strip() or "10"
    if not s.isdigit() or int(s) not in COUNTS:
        raise FormError("Count must be 10, 20 or 30.")
    return int(s)


def date_value(s):
    s = (str(s) if s is not None else "").strip().upper()
    if s not in DATE_FILTERS:
        raise FormError("Date filter must be empty, PAST_WEEK, PAST_MONTH or PAST_YEAR.")
    return s


def body(query, count=10, date_filter=""):
    """Request body for POST /desearch/ai/search with only the hackernews tool, links only, no streaming."""
    b = {"prompt": query, "tools": ["hackernews"], "streaming": False, "result_type": "ONLY_LINKS", "count": count}
    if date_filter:
        b["date_filter"] = date_filter
    return b


def item_id(url):
    m = ITEM_RE.match((url or "").strip())
    return m.group(1) if m else None


def raw_items(resp):
    """Every dict with a link in any list field of the response (the HN results came back under `search`)."""
    out = []
    if isinstance(resp, dict):
        for k, v in resp.items():
            if isinstance(v, list):
                out += [x for x in v if isinstance(x, dict) and (x.get("link") or x.get("url"))]
    return out


def _txt(s):
    return " ".join(str(s or "").split())


def strip_suffix(title):
    """Drops the trailing ' | Hacker News' site tag, also when the API cut it short (' | Hack')."""
    head, sep, tail = title.rpartition("|")
    tail = tail.strip()
    if sep and tail and "Hacker News".startswith(tail) and len(tail) >= 2:
        return head.rstrip()
    return title


def normalize(it):
    url = _txt(it.get("link") or it.get("url"))
    hl = it.get("highlights") if isinstance(it.get("highlights"), list) else []
    return {"item_id": item_id(url), "title": strip_suffix(_txt(it.get("title"))),
            "url": url, "snippet": _txt(it.get("snippet")), "highlights": [_txt(h) for h in hl if _txt(h)]}


def filter_items(items):
    """Keeps only HN item links, deduped by item id. Returns (results, stats)."""
    seen, out, other, dup = set(), [], 0, 0
    for it in items:
        r = normalize(it)
        if not r["item_id"]:
            other += 1
            continue
        if r["item_id"] in seen:
            dup += 1
            continue
        seen.add(r["item_id"])
        r["url"] = f"https://news.ycombinator.com/item?id={r['item_id']}"
        r["rank"] = len(out) + 1
        out.append(r)
    return out, {"returned": len(items), "kept": len(out), "non_item_links": other, "duplicates": dup}


def to_json(payload):
    return json.dumps(payload, indent=1, ensure_ascii=False)


def to_csv(results, max_highlights=3):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(FIELDS)
    for r in results:
        w.writerow([r["rank"], r["item_id"], r["title"], r["url"], r["snippet"], " | ".join(r["highlights"][:max_highlights])])
    return buf.getvalue()


def render_page(form, results=None, info=None, error=None):
    e = lambda s: html.escape(str(s), quote=True)
    opts = "".join(f"<option{' selected' if form.get('date', '') == d else ''} value='{d}'>{d or 'any time'}</option>" for d in DATE_FILTERS)
    p = ["<!doctype html><meta charset=utf-8><title>Hacker News Search</title>",
         "<style>body{font:15px system-ui;max-width:860px;margin:2em auto}.err{color:#b00}.s{color:#444}li{margin:.8em 0}blockquote{margin:.3em 0 0 1em;color:#555}</style>",
         "<h1>Hacker News Search</h1><form method=get action=/>",
         f"<p><input name=q size=46 placeholder='topic, e.g. (sqlite OR duckdb)' value='{e(form.get('q', ''))}'> "
         f"<label>Count <input name=count size=2 value='{e(form.get('count') or 10)}'></label> "
         f"<select name=date>{opts}</select> <button>Search</button></p></form>"]
    if error:
        p.append(f"<p class=err>{e(error)}</p>")
    if info:
        q = urllib.parse.urlencode({k: info[k] for k in ("q", "count", "date") if info.get(k)})
        p.append(f"<p class=s>{info['kept']} HN items of {info['returned']} links, {'from cache' if info['cached'] else 'cost $' + str(info['cost_usd'])}. "
                 f"Export: <a href='/search?{e(q)}'>JSON</a> <a href='/search.csv?{e(q)}'>CSV</a></p>")
    if results is not None:
        if not results:
            p.append("<p>No Hacker News items returned.</p>")
        p.append("<ol>")
        for r in results:
            hl = "".join(f"<blockquote>{e(h[:300])}</blockquote>" for h in r["highlights"][:2])
            p.append(f"<li><a href='{e(r['url'])}'>{e(r['title'] or r['url'])}</a><br><span class=s>{e(r['snippet'][:400])}</span>{hl}</li>")
        p.append("</ol>")
    return "".join(p)
