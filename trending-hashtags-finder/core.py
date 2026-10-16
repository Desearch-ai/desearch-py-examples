"""Network-free logic for the Trending Hashtags Finder. Everything here is pure and unit-tested."""
import datetime as dt
import re
import statistics
from collections import Counter

X_TIME = "%a %b %d %H:%M:%S %z %Y"
SPAM_HINTS = re.compile(r"(giveaway|airdrop|follow ?back|f4f|nsfw)", re.I)


def is_hashtag(name):
    return isinstance(name, str) and name.startswith("#") and len(name) > 1


def trends_of(body):
    if isinstance(body, dict) and isinstance(body.get("trends"), list):
        return body["trends"]
    return []


def hashtags_by_country(trend_bodies):
    """trend_bodies: {country_label: body}. Returns ({label: [(rank, tag)]}, {label: (n_hashtags, n_trends)})."""
    out, counts = {}, {}
    for label, body in trend_bodies.items():
        tr = trends_of(body)
        tags = [(t.get("rank"), t.get("name")) for t in tr if is_hashtag(t.get("name"))]
        out[label] = tags
        counts[label] = (len(tags), len(tr))
    return out, counts


def merge_countries(by_country):
    """One row per hashtag (case-insensitive), with the countries it trends in and its best rank."""
    rows = {}
    for label, tags in by_country.items():
        for rank, tag in tags:
            r = rows.setdefault(tag.lower(), {"hashtag": tag, "countries": {}, "best_rank": rank or 999})
            r["countries"][label] = rank
            r["best_rank"] = min(r["best_rank"], rank or 999)
    return sorted(rows.values(), key=lambda r: (-len(r["countries"]), r["best_rank"], r["hashtag"].lower()))


def build_query(tags):
    """X search query. Several tags are always wrapped as (a OR b)."""
    tags = [t for t in tags if t]
    if not tags:
        raise ValueError("no tags")
    return tags[0] if len(tags) == 1 else "(" + " OR ".join(tags) + ")"


def parse_time(s):
    try:
        return dt.datetime.strptime(s, X_TIME)
    except (TypeError, ValueError):
        return None


def keep_after(posts, start):
    """Drop posts created before `start` (aware datetime). The API can return edge posts from before start_date."""
    kept, dropped = [], 0
    for p in posts:
        t = parse_time(p.get("created_at"))
        if t is None or t < start:
            dropped += 1
        else:
            kept.append(p)
    return kept, dropped


def post_stats(tag, posts, now):
    """Summary of a sample of posts for one hashtag. `now` is an aware datetime."""
    times = [t for t in (parse_time(p.get("created_at")) for p in posts) if t]
    ages = [(now - t).total_seconds() / 60 for t in times]
    likes = [p.get("like_count") or 0 for p in posts]
    authors = {((p.get("user") or {}).get("id")) for p in posts} - {None}
    langs = Counter(p.get("lang") or "und" for p in posts)
    co = Counter()
    for p in posts:
        for h in ((p.get("entities") or {}).get("hashtags") or []):
            t = "#" + (h.get("text") or "") if isinstance(h, dict) else str(h)
            if t.lower() != tag.lower() and len(t) > 1:
                co[t] += 1
    span_h = (max(times) - min(times)).total_seconds() / 3600 if len(times) > 1 else None
    rate = round(len(times) / span_h, 1) if span_h else None
    retweets = sum(1 for p in posts if p.get("is_retweet"))
    spam = sum(1 for p in posts if SPAM_HINTS.search(p.get("text") or ""))
    return {
        "hashtag": tag,
        "sample": len(posts),
        "authors": len(authors),
        "newest_min": round(min(ages)) if ages else None,
        "oldest_min": round(max(ages)) if ages else None,
        "posts_per_hour": rate,
        "median_likes": statistics.median(likes) if likes else None,
        "top_lang": langs.most_common(1)[0][0] if langs else None,
        "lang_share": round(langs.most_common(1)[0][1] / len(posts), 2) if posts else None,
        "co_hashtags": [t for t, _ in co.most_common(3)],
        "spam_hits": spam,
        "retweets": retweets,
        "examples": [f"https://x.com/i/status/{p['id']}" for p in posts[:2] if p.get("id")],
    }


def verdict(row, stats):
    if not stats or stats["sample"] == 0:
        return "no recent posts found"
    if stats["spam_hits"] * 2 >= stats["sample"]:
        return "skip (looks spammy)"
    if stats["authors"] and stats["authors"] * 2 < stats["sample"]:
        return "skip (few accounts posting)"
    if stats["newest_min"] is not None and stats["newest_min"] > 180:
        return "cooling (newest post over 3 h old)"
    if len(row["countries"]) > 1:
        return "use: trending in several countries"
    return "use: local"


def render_md(rows, stats_by_tag, counts, generated):
    lines = [f"# Trending hashtags on X, {generated}", "", "## Hashtags among trends", "",
             "| Country | Hashtags | Trends |", "|---|---|---|"]
    for label, (h, n) in counts.items():
        lines.append(f"| {label} | {h} | {n} |")
    lines += ["", "## Shortlist", "",
              "| Hashtag | Countries (rank) | Sample | Accounts | Newest (min) | Posts/h | Median likes | Lang | Also used with | Verdict |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        s = stats_by_tag.get(r["hashtag"].lower())
        c = ", ".join(f"{k} ({v})" for k, v in r["countries"].items())
        if s:
            lines.append(f"| {r['hashtag']} | {c} | {s['sample']} | {s['authors']} | {s['newest_min']} | {s['posts_per_hour']} | "
                         f"{s['median_likes']} | {s['top_lang']} | {' '.join(s['co_hashtags']) or '-'} | {verdict(r, s)} |")
        else:
            lines.append(f"| {r['hashtag']} | {c} | - | - | - | - | - | - | - | not sampled |")
    return "\n".join(lines) + "\n"
