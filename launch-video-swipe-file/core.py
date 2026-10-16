"""Pure helpers for swipe.py (no network): query, filters, opening rules, cost, output files."""
import csv, datetime as dt, io, re

# Public rate for X Search (desearch.ai/pricing, checked 2026-10-12): $0.15 per 1,000 posts,
# 10-post minimum per request. Used only as a labelled fallback when a response has no cost header.
X_RATE, X_MIN = 0.00015, 10

LAUNCH_WORDS = ["launch", "launching", "introducing", "demo"]


def build_query(terms, words=LAUNCH_WORDS):
    """Both OR groups in parentheses: (launch OR ...) (term1 OR term2)."""
    def grp(xs):
        xs = [x if (" " not in x or x.startswith('"')) else f'"{x}"' for x in xs]
        return "(" + " OR ".join(xs) + ")"
    return f"{grp(words)} {grp(terms)}"


def created(p):
    s = p.get("created_at") or ""
    for f in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return dt.datetime.strptime(s.replace("Z", "+0000"), f)
        except ValueError:
            pass
    return None


def in_window(p, start):
    """start_date is a UTC day; drop anything created before 00:00 UTC that day."""
    c = created(p)
    return bool(c) and c.astimezone(dt.timezone.utc).date().isoformat() >= start


def likes(p):
    return int(p.get("like_count") or 0)


def media_types(p):
    out = []
    for m in (p.get("media") or []) + ((p.get("extended_entities") or {}).get("media") or []):
        if isinstance(m, dict) and m.get("type"):
            out.append(m["type"])
    return out


def has_video(p):
    return any(t in ("video", "animated_gif") for t in media_types(p))


def status_url(pid):
    return f"https://x.com/i/status/{pid}"


def author_label(p, brands=()):
    """Org/brand accounts listed in `brands` are named; individuals show as 'a creator'."""
    u = ((p.get("user") or {}).get("username") or "")
    return u if u and u.lower() in {b.lower() for b in brands} else "a creator"


VENDORS = re.compile(r"\b(claude|anthropic|opus|haiku|sonnet|codex|openai|chatgpt|gpt-?\d[\w.]*|gemini|google|qwen|"
                     r"elevenlabs|higgsfield|runway|sora|veo|kling|posthog|remotion|canva|adobe|firefly|grok|llama|"
                     r"deepseek|mistral|perplexity|cursor|notion|todoist|tiktok|capcut|loom|screen ?studio|"
                     r"product ?hunt|lovable|replit|bolt|v0|figma|framer)\b(?:\s*\d+(?:\.\d+)*)?", re.I)


def mask(text):
    t = re.sub(r"\s*\u2014\s*", ", ", text or "").replace("\u2013", "-")
    return VENDORS.sub("[tool]", t)


def scrub(text):
    t = re.sub(r"https?://t\.co/\w+", "", text or "")
    return re.sub(r"@\w{1,15}", "@user", re.sub(r"\s+", " ", t)).strip()


def hook(p, n=140):
    """First line of the post text (the hook)."""
    first = next((l for l in (p.get("text") or "").splitlines() if l.strip()), "")
    return scrub(first)[:n]


# Opening rules, checked in order on the first ~200 chars. First match wins.
OPENINGS = [
    ("before/after", re.compile(r"\bbefore\b.*\bafter\b|\bbefore\s*(?:vs|/|->|→)|\bold way\b|\bthen vs now\b", re.I)),
    ("problem-first", re.compile(r"^\W*(?:tired of|sick of|ever |why (?:is|do|does)|struggl|hate |the problem|stop |"
                                 r"most people|you (?:don't|never)|no more|what if|how (?:do|many))|^[^.!\n]{0,80}\?", re.I)),
    ("founder talking", re.compile(r"\b(?:i|we)(?:'ve| have)? (?:built|made|spent|quit|launched|shipped|started|"
                                   r"created|finally)\b|\bmy (?:first|new|own|app|startup|side project)\b|"
                                   r"\bafter \d+ (?:months|weeks|years)\b|\bsolo (?:dev|founder)\b", re.I)),
    ("demo-first", re.compile(r"\bdemo\b|\bwatch\b|\bin action\b|\bhere'?s how\b|\blook at\b|\bwalkthrough\b|"
                              r"\bsee (?:it|how)\b|👇|🎥|📹", re.I)),
    ("announcement", re.compile(r"\bintroducing\b|\blaunch(?:ing|ed)?\b|\bmeet\b|\bis (?:now )?live\b|"
                                r"\bjust shipped\b|\bout now\b|\bavailable (?:now|today)\b|\bnew:", re.I)),
]


def opening(p):
    t = (p.get("text") or "")[:200]
    for name, rx in OPENINGS:
        if rx.search(t):
            return name
    return "other"


def is_launch(p):
    """Rough text check: launch / demo wording present."""
    return bool(re.search(r"\b(?:launch\w*|introduc\w*|demo\w*|shipped|is live|out now|built)\b", p.get("text") or "", re.I))


def cost_of(headers, posts_returned=None):
    """(usd, source). Header wins; otherwise a labelled calculation from the public X rate."""
    h = {k.lower(): v for k, v in (headers or {}).items()}
    if "x-desearch-cost-usd" in h:
        return float(h["x-desearch-cost-usd"]), "header"
    if posts_returned is not None:
        return round(max(posts_returned, X_MIN) * X_RATE, 6), "calculated"
    return 0.0, "none"


def select(posts, start, min_likes, n=15):
    """Keep in-window video posts at or above min_likes, one per author, most-liked first."""
    ok = [p for p in posts if in_window(p, start) and has_video(p) and likes(p) >= min_likes]
    ok.sort(key=likes, reverse=True)
    out, seen = [], set()
    for p in ok:
        u = ((p.get("user") or {}).get("username") or "").lower()
        if u in seen:
            continue
        seen.add(u)
        out.append(p)
        if len(out) == n:
            break
    return out


CSV_COLS = ["rank", "opening", "date", "author", "url", "likes", "reposts", "replies", "has_video", "launch_words", "hook", "found_by"]


def rows(posts, brands=()):
    out = []
    for i, p in enumerate(posts, 1):
        c = created(p)
        out.append({"rank": i, "opening": opening(p), "date": c.strftime("%Y-%m-%d") if c else "",
                    "author": author_label(p, brands), "url": status_url(p["id"]), "likes": likes(p),
                    "reposts": p.get("retweet_count") or 0, "replies": p.get("reply_count") or 0,
                    "has_video": has_video(p), "launch_words": is_launch(p), "hook": mask(hook(p)),
                    "found_by": "+".join(sorted(p.get("_found_by") or []))})
    return out


def to_csv(rs, cols=CSV_COLS):
    b = io.StringIO()
    w = csv.DictWriter(b, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    w.writerows(rs)
    return b.getvalue()


ORDER = ["demo-first", "problem-first", "founder talking", "before/after", "announcement", "other"]


def swipe_md(category, query, start, min_likes, posts, generated, brands=()):
    L = [f"# Launch video swipe file: {category}", "",
         f"Public X video posts Desearch returned for this search on {generated[:10]}: `{query}`, "
         f"video posts only, at least {min_likes} likes, since {start} (UTC). Likes, reposts and replies were refreshed by URL "
         f"at {generated}.", "", "Tip: check post dates and open each post before you use it as a reference.", ""]
    by = {}
    for p in posts:
        by.setdefault(opening(p), []).append(p)
    for k in ORDER:
        if k not in by:
            continue
        L += [f"## {k} ({len(by[k])})", ""]
        for p in by[k]:
            c = created(p)
            L += [f"- **{mask(hook(p))}**", f"  {c:%Y-%m-%d} · {author_label(p, brands)} · {likes(p)} likes, "
                  f"{p.get('retweet_count') or 0} reposts, {p.get('reply_count') or 0} replies · {status_url(p['id'])}", ""]
    L += ["## How posts are grouped", "",
          "By the first 200 characters of the post text, first rule that matches: before/after (before ... after, then vs now), "
          "problem-first (opens with a question or a pain such as \"tired of\"), founder talking (\"I built\", \"we made\", "
          "\"my first app\"), demo-first (demo, watch, here's how), announcement (introducing, launching, meet, is live), else other. "
          "The text decides, not the video itself, so watch before you copy.", "", "Made by Desearch · https://desearch.ai", ""]
    return "\n".join(L)
