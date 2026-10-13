"""Pure helpers for repobuzz.py (no network): queries, matching, ranking, cost, output files."""
import csv, datetime as dt, io, re

# Public rate for X Search (desearch.ai/pricing, checked 2026-10-12): $0.15 per 1,000 posts,
# 10-post minimum per request. Used only as a labelled fallback when a response has no cost header.
X_RATE, X_MIN = 0.00015, 10


def parse_repo(s):
    """'https://github.com/a/b' or 'a/b' -> ('a', 'b')."""
    m = re.search(r"(?:github\.com/)?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$", (s or "").strip())
    if not m:
        raise ValueError(f"not an owner/repo: {s!r}")
    return m.group(1), m.group(2)


def url_query(owner, repo):
    return f'("github.com/{owner}/{repo}" OR "{owner}/{repo}")'


def name_query(repo):
    words = re.sub(r"[-_.]+", " ", repo).strip()
    alts = [repo] + ([words] if words.lower() != repo.lower() else [])
    return "(" + " OR ".join(f'"{a}"' for a in alts) + ")"


def post_urls(p):
    """Every URL attached to a post: expanded entity URLs plus raw t.co / text URLs."""
    out = []
    for u in ((p.get("entities") or {}).get("urls") or []):
        if isinstance(u, dict):
            out += [u.get("expanded_url") or "", u.get("url") or "", u.get("display_url") or ""]
    out += re.findall(r"https?://\S+", p.get("text") or "")
    return [u for u in out if u]


CONTEXT = re.compile(r"github|open[- ]source|\brepo\b|\bstars?\b|npm|\bpip\b|\bcli\b", re.I)


def classify(p, owner, repo):
    """How a post points at the repo. 'url' and 'owner/repo' are sure; 'name+context' is likely;
    'name-only' is ambiguous; 'no-match' means the post does not contain the term at all."""
    text = (p.get("text") or "")
    low = text.lower()
    full = f"github.com/{owner}/{repo}".lower()
    if any(full in u.lower() for u in post_urls(p)):
        return "url"
    if f"{owner}/{repo}".lower() in low:
        return "owner/repo"
    name_re = re.compile(re.escape(repo).replace(r"\-", r"[-_ ]?"), re.I)
    if name_re.search(text):
        return "name+context" if (CONTEXT.search(text) or owner.lower().split("-")[0] in low) else "name-only"
    if any("x.com/i/article/" in u for u in post_urls(p)):
        return "x-article"  # long-form X Article: body not in the result, term cannot be checked
    return "no-match"


# 'name-only' is kept for distinctive repo names (default); --strict keeps only the first three.
KEEP = {"url", "owner/repo", "name+context", "name-only"}
STRICT = {"url", "owner/repo", "name+context"}


def in_window(p, start):
    """start_date is a UTC day; drop anything created before 00:00 UTC that day."""
    c = created(p)
    return bool(c) and c.date().isoformat() >= start


def created(p):
    s = p.get("created_at") or ""
    for f in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return dt.datetime.strptime(s.replace("Z", "+0000"), f)
        except ValueError:
            pass
    return None


def loudness(p):
    return int(p.get("like_count") or 0) + 2 * int(p.get("retweet_count") or 0) + int(p.get("reply_count") or 0)


def status_url(pid):
    return f"https://x.com/i/status/{pid}"


def author_label(p, owner, repo=""):
    """Org accounts are named; individual accounts are not (public copy rule)."""
    u = ((p.get("user") or {}).get("username") or "")
    stem = owner.lower().split("-")[0]
    rs = re.sub(r"[-_.]", "", repo.lower())
    ul = re.sub(r"[-_.]", "", u.lower())
    return u if u and (stem in ul or (rs and rs in ul)) else "a developer"


# Names masked in quoted post text. Ship a placeholder so this file does not list vendor products.
# Set your own names before a run, for example: VENDOR_NAMES = ["example-tool"]
VENDOR_NAMES = ["[tool]"]


def vendor_pattern(names=None):
    parts = []
    for name in VENDOR_NAMES if names is None else names:
        if not name or name == "[tool]":
            continue
        parts.append(re.escape(name))
    if not parts:
        return None
    return re.compile(r"\b(?:" + "|".join(parts) + r")\b(?:\s*\d+(?:\.\d+)*)?", re.I)


def mask(text):
    text = (text or "").replace("\u2014", ", ").replace("\u2013", "-")
    pat = vendor_pattern()
    return pat.sub("[tool]", text) if pat else text


def scrub(text):
    return re.sub(r"@\w{1,15}", "@user", re.sub(r"\s+", " ", text or "")).strip()


def cost_of(headers, posts_returned=None):
    """(usd, source). Header wins; otherwise a labelled calculation from the public X rate."""
    h = {k.lower(): v for k, v in (headers or {}).items()}
    if "x-desearch-cost-usd" in h:
        return float(h["x-desearch-cost-usd"]), "header"
    if posts_returned is not None:
        return round(max(posts_returned, X_MIN) * X_RATE, 6), "calculated"
    return 0.0, "none"


CSV_COLS = ["date", "source", "match", "author", "url", "likes", "reposts", "replies", "snippet", "found_by"]


def rows(posts, web, owner):
    out = []
    for p in posts:
        c = created(p)
        out.append({"date": c.strftime("%Y-%m-%d %H:%M UTC") if c else "", "source": "x", "match": p["_match"],
                    "author": ((p.get("user") or {}).get("username") or ""), "url": status_url(p["id"]),
                    "likes": p.get("like_count") or 0, "reposts": p.get("retweet_count") or 0,
                    "replies": p.get("reply_count") or 0, "snippet": scrub(p.get("text"))[:200],
                    "found_by": "+".join(sorted(p["_found_by"]))})
    out.sort(key=lambda r: r["date"], reverse=True)
    for w in web:
        out.append({"date": "", "source": "web", "match": w["_match"], "author": re.sub(r"^www\.", "", re.sub(r"^https?://([^/]+).*", r"\1", w.get("link") or "")),
                    "url": w.get("link") or "", "likes": "", "reposts": "", "replies": "",
                    "snippet": scrub(w.get("title"))[:200], "found_by": "links/web"})
    return out


def to_csv(rs):
    b = io.StringIO()
    w = csv.DictWriter(b, fieldnames=CSV_COLS)
    w.writeheader()
    w.writerows(rs)
    return b.getvalue()


def web_match(w, owner, repo):
    blob = " ".join([w.get("link") or "", w.get("title") or "", w.get("snippet") or ""]).lower()
    if re.search(r"github\.com/" + re.escape(f"{owner}/{repo}".lower()) + r"(?![a-z0-9_.-])", blob):
        return "repo-page"
    if re.search(re.escape(repo.lower()) + r"(?![a-z0-9_-])", blob) or repo.lower().replace("-", " ") in blob:
        return "mentions-name"
    return "no-match"


def buzz_md(owner, repo, start, posts, top3, replies, web, generated):
    by_day = {}
    for p in posts:
        c = created(p)
        by_day.setdefault(c.strftime("%Y-%m-%d") if c else "unknown", []).append(p)
    L = [f"# Repo buzz: {owner}/{repo}", "",
         f"Public posts and pages Desearch returned for `{owner}/{repo}` since {start} (generated {generated}).",
         "Counts are what the search returned, not a full count of all posts. Tip: check post dates.", "",
         f"- X posts kept: **{len(posts)}** (a link to the repo, the `owner/repo` text, or the repo name; X Article posts whose text is not in the result are left out)",
         f"- Web pages returned: **{len(web)}**", "", "## Day by day", "",
         "| Day (UTC) | Posts | Likes | Reposts | Loudest post |", "|---|---|---|---|---|"]
    for d in sorted(by_day, reverse=True):
        ps = by_day[d]
        top = max(ps, key=loudness)
        L.append(f"| {d} | {len(ps)} | {sum(int(p.get('like_count') or 0) for p in ps)} | "
                 f"{sum(int(p.get('retweet_count') or 0) for p in ps)} | {status_url(top['id'])} |")
    L += ["", "## Loudest 3 posts and replies Desearch returned", ""]
    for p in top3:
        rs = replies.get(p["id"], [])
        L += [f"### {status_url(p['id'])}", "",
              f"{created(p):%Y-%m-%d} · {author_label(p, owner, repo)} · {p.get('like_count') or 0} likes, "
              f"{p.get('retweet_count') or 0} reposts, {p.get('reply_count') or 0} replies (as shown on the post)", "",
              f"> {mask(scrub(p.get('text')))[:280]}", "",
              f"Replies returned: {len(rs)}", ""]
        for r in rs[:5]:
            L.append(f"- {mask(scrub(r.get('text')))[:160]} ({status_url(r['id'])})")
        L.append("")
    L += ["## Web pages Desearch returned", ""]
    for w in web:
        L.append(f"- [{mask(scrub(w.get('title'))) or w.get('link')}]({w.get('link')}) ({w['_match']})")
    L += ["", "Made by Desearch · https://desearch.ai", ""]
    return "\n".join(L)
