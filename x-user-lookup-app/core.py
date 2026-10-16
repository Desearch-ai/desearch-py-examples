"""Network-free logic for the X User Lookup App: username check, paging rules, profile card, post rows, stats, CSV, HTML."""
import csv, datetime as dt, html, io, re, statistics

X_TIME = "%a %b %d %H:%M:%S %z %Y"
USER_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
HANDLE_RE = re.compile(r"@\w{1,15}")
MAX_PAGES = 3  # first page plus up to 2 more via next_cursor


class FormError(ValueError):
    pass


def clean_username(s):
    """Accepts 'name', '@name' or an x.com / twitter.com profile URL. Raises FormError before any paid call."""
    s = (s or "").strip()
    m = re.match(r"^(?:https?://)?(?:www\.)?(?:x|twitter)\.com/([^/?#]+)/?(?:[?#].*)?$", s, re.I)
    if m:
        s = m.group(1)
    s = s.lstrip("@")
    if not s:
        raise FormError("Enter a username.")
    if not USER_RE.match(s):
        raise FormError("A username is 1 to 15 letters, digits or underscores.")
    return s


def pages_value(s):
    s = (str(s) if s is not None else "").strip() or str(MAX_PAGES)
    if not s.isdigit() or not 1 <= int(s) <= MAX_PAGES:
        raise FormError(f"Pages must be 1 to {MAX_PAGES}.")
    return int(s)


def params(username, cursor=None):
    p = {"username": username}
    if cursor:
        p["cursor"] = cursor
    return p


def parse_time(s):
    try:
        return dt.datetime.strptime(s, X_TIME)
    except (TypeError, ValueError):
        return None


def tweets_of(body):
    if isinstance(body, dict) and isinstance(body.get("tweets"), list):
        return [t for t in body["tweets"] if isinstance(t, dict)]
    return []


def next_cursor(body):
    return body.get("next_cursor") or None if isinstance(body, dict) else None


def should_follow(body, seen_cursors, pages_done, max_pages):
    """Return the cursor to request next, or None. Stops on no cursor, a repeated cursor, or the page limit."""
    c = next_cursor(body)
    if not c or c in seen_cursors or pages_done >= max_pages:
        return None
    return c


def profile(body, username):
    u = (body.get("user") if isinstance(body, dict) else None) or {}
    t = parse_time(u.get("created_at"))
    return {"username": u.get("username") or username, "name": u.get("name") or "",
            "bio": " ".join(str(u.get("description") or "").split()),
            "followers": u.get("followers_count"), "following": u.get("followings_count"),
            "posts_total": u.get("statuses_count"), "created": t.strftime("%Y-%m-%d") if t else "",
            "blue": bool(u.get("is_blue_verified")), "found": bool(u)}


def row(t, page):
    c = parse_time(t.get("created_at"))
    kind = "repost" if t.get("is_retweet") else "reply" if t.get("in_reply_to_status_id") else "quote" if t.get("is_quote_tweet") else "post"
    return {"id": str(t.get("id", "")), "page": page, "created_utc": c.strftime("%Y-%m-%d %H:%M") if c else "",
            "kind": kind, "text": HANDLE_RE.sub("@user", " ".join(str(t.get("text") or "").split())),
            "likes": t.get("like_count") or 0, "replies": t.get("reply_count") or 0,
            "reposts": t.get("retweet_count") or 0, "views": t.get("view_count") or 0,
            "link": f"https://x.com/i/status/{t.get('id')}"}


def merge(pages):
    """pages: list of tweet-lists (one per page). Dedupes by id, keeps first seen. Returns rows and repeat count."""
    seen, rows, repeats = set(), [], 0
    for i, ts in enumerate(pages, 1):
        for t in ts:
            r = row(t, i)
            if r["id"] in seen:
                repeats += 1
                continue
            seen.add(r["id"])
            rows.append(r)
    return rows, repeats


def out_of_order(rows):
    """Count of adjacent pairs where a later row is newer than the one before it (API order kept as-is)."""
    ts = [r["created_utc"] for r in rows if r["created_utc"]]
    return sum(1 for a, b in zip(ts, ts[1:]) if b > a)


def stats(rows):
    times = sorted(r["created_utc"] for r in rows if r["created_utc"])
    if not rows or not times:
        return {"posts": len(rows), "per_day": 0.0, "median_likes": 0, "first": "", "last": ""}
    a, b = (dt.datetime.strptime(x, "%Y-%m-%d %H:%M") for x in (times[0], times[-1]))
    days = max((b - a).total_seconds() / 86400, 1.0)
    return {"posts": len(rows), "per_day": round(len(times) / days, 2),
            "median_likes": statistics.median(r["likes"] for r in rows), "first": times[0], "last": times[-1]}


CSV_FIELDS = ["created_utc", "kind", "text", "likes", "replies", "reposts", "views", "page", "link"]


def to_csv(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def render_page(form, prof=None, rows=None, st=None, error=None, note=None, csv_href=None):
    e = lambda s: html.escape(str(s), quote=True)
    parts = ["<!doctype html><meta charset=utf-8><title>X User Lookup</title>",
             "<style>body{font:15px system-ui;max-width:960px;margin:2em auto}td{vertical-align:top;padding:4px;border-top:1px solid #ddd}"
             ".err{color:#b00}.note{color:#555}.card{border:1px solid #ddd;padding:10px}</style>",
             "<h1>X User Lookup</h1><form method=get action=/lookup>",
             f"<p><input name=username size=30 placeholder='username' value='{e(form.get('username', ''))}'> "
             f"<label>Pages <input name=pages size=2 value='{e(form.get('pages') or MAX_PAGES)}'></label> <button>Look up</button></p></form>"]
    if error:
        parts.append(f"<p class=err>{e(error)}</p>")
    if note:
        parts.append(f"<p class=note>{e(note)}</p>")
    if prof:
        parts.append(f"<div class=card><b>{e(prof['name'])}</b> @{e(prof['username'])}<br>{e(prof['bio'])}<br>"
                     f"{e(prof['followers'])} followers, {e(prof['following'])} following, {e(prof['posts_total'])} posts, joined {e(prof['created'])}</div>")
    if st:
        parts.append(f"<p>{st['posts']} posts from {e(st['first'])} to {e(st['last'])} UTC, {st['per_day']} per day, median likes {st['median_likes']}</p>")
    if rows is not None:
        if csv_href:
            parts.append(f"<p><a href='{e(csv_href)}'>Download CSV</a></p>")
        if not rows:
            parts.append("<p>No posts returned.</p>")
        parts.append("<table>")
        for r in rows:
            parts.append(f"<tr><td>{e(r['created_utc'])}<br>{e(r['kind'])}</td><td>{e(r['text'])}</td>"
                         f"<td>{r['likes']} likes<br>{r['replies']} replies</td><td><a href='{e(r['link'])}'>open</a></td></tr>")
        parts.append("</table>")
    return "".join(parts)
