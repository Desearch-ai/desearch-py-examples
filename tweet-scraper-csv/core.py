"""Pure helpers for tweets_csv.py (no network): query, date filter, rows, CSV, masking, cost."""
import csv, datetime as dt, io, re

COLUMNS = ["id", "date", "text", "likes", "reposts", "replies", "link", "author"]


def build_query(terms, extra=""):
    """OR terms always go inside parentheses: ("a b" OR c) extra."""
    xs = [t if (" " not in t or t.startswith('"')) else f'"{t}"' for t in terms if t.strip()]
    if not xs:
        raise ValueError("at least one search term is required")
    q = "(" + " OR ".join(xs) + ")"
    return f"{q} {extra}".strip()


def created(p):
    s = (p.get("created_at") or "").replace("Z", "+0000")
    for f in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return dt.datetime.strptime(s, f)
        except ValueError:
            pass
    return None


def in_window(p, start=None, end=None):
    """start/end are UTC days (YYYY-MM-DD). Drops posts from before start (e.g. a day-before edge post)
    and, if end is given, posts after end."""
    c = created(p)
    if not c:
        return False
    d = c.astimezone(dt.timezone.utc).date().isoformat()
    return (not start or d >= start) and (not end or d <= end)


def status_url(pid):
    return f"https://x.com/i/status/{pid}"


def author_label(p, orgs=()):
    """Org accounts listed in `orgs` are named; everyone else is 'a user'."""
    u = (p.get("user") or {}).get("username") or ""
    return u if u and u.lower() in {o.lower().lstrip("@") for o in orgs} else "a user"


VENDORS = re.compile(r"\b(claude|anthropic|codex|openai|chatgpt|gpt-?\d[\w.]*|gemini|google|grok|xai|llama|deepseek|"
                     r"mistral|perplexity|cursor|apify|bright ?data|brightdata|scrapingbee|scraperapi|zenrows|oxylabs|"
                     r"phantombuster|octoparse|firecrawl|exa|tavily|serpapi|serper|jina|twint|snscrape|tweepy|"
                     r"nitter|rapidapi|socialdata|twitterapi(?:\.io)?|scrapfly|diffbot|smartproxy|decodo)\b", re.I)


def mask(text):
    t = re.sub(r"\s*\u2014\s*", ", ", text or "").replace("\u2013", "-")
    return VENDORS.sub("[tool]", t)


def scrub(text, public=True):
    t = re.sub(r"https?://t\.co/\w+", "", text or "")
    t = re.sub(r"\s+", " ", t).strip()
    if public:
        t = re.sub(r"@\w{1,15}", "@user", mask(t))
    return t


def row(p, orgs=(), public=True):
    c = created(p)
    return {"id": str(p.get("id")),
            "date": c.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if c else "",
            "text": scrub(p.get("text"), public),
            "likes": int(p.get("like_count") or 0),
            "reposts": int(p.get("retweet_count") or 0),
            "replies": int(p.get("reply_count") or 0),
            "link": status_url(p.get("id")),
            "author": author_label(p, orgs) if public else ((p.get("user") or {}).get("username") or "")}


def clean(posts, start=None, end=None):
    """Dedupe by id, keep the date window, newest first. Returns (kept, dropped_ids)."""
    seen, kept, dropped = set(), [], []
    for p in posts or []:
        pid = str(p.get("id"))
        if pid in seen:
            continue
        seen.add(pid)
        if in_window(p, start, end):
            kept.append(p)
        else:
            dropped.append(pid)
    kept.sort(key=lambda p: created(p) or dt.datetime.min.replace(tzinfo=dt.timezone.utc), reverse=True)
    return kept, dropped


def to_csv(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS)
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def cost_of(headers):
    h = {k.lower(): v for k, v in (headers or {}).items()}
    return (float(h["x-desearch-cost-usd"]), "header") if "x-desearch-cost-usd" in h else (0.0, "none")
