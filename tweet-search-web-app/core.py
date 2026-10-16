"""Network-free logic for the Tweet Search Web App: form validation, query params, result rows, CSV, HTML."""
import csv, datetime as dt, html, io, re

X_TIME = "%a %b %d %H:%M:%S %z %Y"
HANDLE_RE = re.compile(r"@\w{1,15}")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LANG_RE = re.compile(r"^[a-z]{2,3}$")
BOOL_FILTERS = ("verified", "blue_verified", "is_video", "is_image", "is_quote")
MIN_FILTERS = ("min_likes", "min_replies", "min_retweets")


class FormError(ValueError):
    pass


def build_query(terms):
    """Several terms always become (a OR b). A single term is passed as-is."""
    terms = [t.strip() for t in terms if t and t.strip()]
    if not terms:
        raise FormError("Enter a search term.")
    return terms[0] if len(terms) == 1 else "(" + " OR ".join(terms) + ")"


def _date(s, name):
    if not s:
        return None
    if not DATE_RE.match(s):
        raise FormError(f"{name} must be YYYY-MM-DD.")
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        raise FormError(f"{name} is not a real date.")


def validate(form, today=None):
    """form: dict of str -> str (one value each). Returns params for GET /twitter or raises FormError.
    Everything is checked before any paid call is made."""
    g = lambda k: (form.get(k) or "").strip()
    q = g("q")
    if not q:
        raise FormError("Enter a search term.")
    any_terms = [t for t in g("any").split(",") if t.strip()]
    query = q if not any_terms else q + " " + build_query(any_terms)
    p = {"query": query}
    sort = g("sort") or "Latest"
    if sort not in ("Latest", "Top"):
        raise FormError("Sort must be Latest or Top.")
    p["sort"] = sort
    count = g("count") or "20"
    if not count.isdigit() or not 1 <= int(count) <= 100:
        raise FormError("Count must be 1 to 100.")
    p["count"] = int(count)
    lang = g("lang").lower()
    if lang:
        if not LANG_RE.match(lang):
            raise FormError("Language must be a 2 or 3 letter code like en.")
        p["lang"] = lang
    for k in MIN_FILTERS:
        v = g(k)
        if v:
            if not v.isdigit():
                raise FormError(f"{k} must be a whole number, 0 or more.")
            if int(v) > 0:
                p[k] = int(v)
    for k in BOOL_FILTERS:
        if g(k).lower() in ("1", "on", "true", "yes"):
            p[k] = "true"
    s, e = _date(g("start_date"), "Start date"), _date(g("end_date"), "End date")
    today = today or dt.datetime.now(dt.timezone.utc).date()
    if s and s > today:
        raise FormError("Start date is in the future.")
    if s and e and e < s:
        raise FormError("End date is before start date.")
    if s:
        p["start_date"] = s.isoformat()
    if e:
        p["end_date"] = e.isoformat()
    return p


def parse_time(s):
    try:
        return dt.datetime.strptime(s, X_TIME)
    except (TypeError, ValueError):
        return None


def posts_of(body):
    if isinstance(body, list):
        return [p for p in body if isinstance(p, dict)]
    if isinstance(body, dict):
        for k in ("data", "tweets", "results"):
            if isinstance(body.get(k), list):
                return body[k]
    return []


def has_media(p, kind):
    """kind: 'video' or 'photo'. Looks at media and extended_entities."""
    media = list(p.get("media") or []) + list(((p.get("extended_entities") or {}).get("media")) or [])
    for m in media:
        t = (m.get("type") if isinstance(m, dict) else str(m)) or ""
        if (kind == "video" and t in ("video", "animated_gif")) or (kind == "photo" and t == "photo"):
            return True
    return False


def row(p):
    """One public result row. No author name or handle: the link uses x.com/i/status/<id>."""
    t = parse_time(p.get("created_at"))
    u = p.get("user") or {}
    return {"id": str(p.get("id", "")),
            "created_utc": t.strftime("%Y-%m-%d %H:%M") if t else "",
            "text": HANDLE_RE.sub("@user", " ".join(str(p.get("text") or "").split())),
            "lang": p.get("lang") or "",
            "likes": p.get("like_count") or 0, "replies": p.get("reply_count") or 0,
            "reposts": p.get("retweet_count") or 0,
            "verified": bool(u.get("verified")), "blue": bool(u.get("is_blue_verified")),
            "video": has_media(p, "video"), "image": has_media(p, "photo"),
            "link": f"https://x.com/i/status/{p.get('id')}"}


def check_filters(params, rows):
    """For each filter sent, how many returned rows break it. Used by the UI note and by the filter probes."""
    out = {}
    for k in MIN_FILTERS:
        if k in params:
            f = {"min_likes": "likes", "min_replies": "replies", "min_retweets": "reposts"}[k]
            out[k] = sum(1 for r in rows if r[f] < params[k])
    for k, f in (("is_video", "video"), ("is_image", "image"), ("verified", "verified"), ("blue_verified", "blue")):
        if k in params:
            out[k] = sum(1 for r in rows if not r[f])
    if "lang" in params:
        out["lang"] = sum(1 for r in rows if r["lang"] != params["lang"])
    if "start_date" in params or "end_date" in params:
        s, e = params.get("start_date", "0000"), params.get("end_date", "9999")
        out["date"] = sum(1 for r in rows if r["created_utc"] and not (s <= r["created_utc"][:10] <= e))
    return out


CSV_FIELDS = ["created_utc", "text", "lang", "likes", "replies", "reposts", "verified", "blue", "video", "image", "link"]


def to_csv(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def render_page(form, rows=None, error=None, note=None, csv_href=None):
    e = lambda s: html.escape(str(s), quote=True)
    v = lambda k: e(form.get(k, ""))
    chk = lambda k: " checked" if form.get(k) else ""
    sel = lambda val: " selected" if (form.get("sort") or "Latest") == val else ""
    parts = ["<!doctype html><meta charset=utf-8><title>Tweet Search</title>",
             "<style>body{font:15px system-ui;max-width:960px;margin:2em auto}td{vertical-align:top;padding:4px;border-top:1px solid #ddd}"
             "label{margin-right:10px}.err{color:#b00}.note{color:#555}</style>",
             "<h1>Tweet Search</h1><form method=get action=/search>",
             f"<p><input name=q size=40 placeholder='search terms' value='{v('q')}'> "
             f"any of (comma separated): <input name=any size=24 value='{v('any')}'></p>",
             f"<p><label>Sort <select name=sort><option{sel('Latest')}>Latest</option><option{sel('Top')}>Top</option></select></label>"
             f"<label>Count <input name=count size=3 value='{v('count') or 20}'></label>"
             f"<label>Lang <input name=lang size=3 value='{v('lang')}'></label>"
             f"<label>Min likes <input name=min_likes size=4 value='{v('min_likes')}'></label>"
             f"<label>Min replies <input name=min_replies size=4 value='{v('min_replies')}'></label>"
             f"<label>Min reposts <input name=min_retweets size=4 value='{v('min_retweets')}'></label></p>",
             "<p>" + "".join(f"<label><input type=checkbox name={k}{chk(k)}> {k}</label>" for k in BOOL_FILTERS) + "</p>",
             f"<p><label>From <input type=date name=start_date value='{v('start_date')}'></label>"
             f"<label>To <input type=date name=end_date value='{v('end_date')}'></label>"
             "<button>Search</button></p></form>"]
    if error:
        parts.append(f"<p class=err>{e(error)}</p>")
    if note:
        parts.append(f"<p class=note>{e(note)}</p>")
    if rows is not None:
        if csv_href:
            parts.append(f"<p><a href='{e(csv_href)}'>Download CSV</a></p>")
        if not rows:
            parts.append("<p>No posts returned.</p>")
        parts.append("<table>")
        for r in rows:
            parts.append(f"<tr><td>{e(r['created_utc'])}</td><td>{e(r['text'])}</td>"
                         f"<td>{r['likes']} likes<br>{r['replies']} replies</td><td><a href='{e(r['link'])}'>open</a></td></tr>")
        parts.append("</table>")
    return "".join(parts)
