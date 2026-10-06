#!/usr/bin/env python3
"""TikTok Trend Board: which hashtags and sounds show up in today's TikTok trending feed, per region,
built on the Desearch API.

Made by Desearch (https://desearch.ai)

Usage:
    export DESEARCH_API_KEY=...            # your key from console.desearch.ai
    python tiktok_board.py                 # US + GB, 30 trending posts each, top 3 hashtags, comments on the top post
    python tiktok_board.py --regions US GB --count 30 --tag-count 20 --no-comments
    python tiktok_board.py --from-raw output/raw-2026-10-05.json   # re-run the analysis offline, no API calls

The official Python SDK (desearch-py 1.2.1) has no TikTok methods, so this script calls the REST API directly.
"""
import argparse, collections, datetime as dt, json, os, re, sys, time

import requests
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE = "https://api.desearch.ai"
# Tags that say "please show this" rather than what the post is about. Kept in the counts, skipped when
# choosing which hashtags to drill into.
GENERIC = {"fyp", "foryou", "foryoupage", "viral", "fypシ", "fypシ゚viral", "fy", "fypage", "trending", "tiktok",
           "viralvideo", "xyzbca", "xyzabc", "goviral", "blowthisup", "parati", "capcut", "foryourpage", "fypviral",
           "trend", "explore", "explorepage", "1000views1000likes", "creatorsearchinsights", "tiktokgrowthchallenge"}
TAG_RE = re.compile(r"#([^\s#@]+)")
GENERIC_RE = re.compile(r"^(fy|fp|for ?you|viral)", re.I)


def generic(tag):
    return tag in GENERIC or bool(GENERIC_RE.match(tag))


def get(session, costs, label, path, params):
    """GET one endpoint, record latency and the billing headers. Never logs request headers (API key)."""
    t0 = time.time()
    try:
        r = session.get(BASE + path, params=params, timeout=120)
    except requests.RequestException as e:  # log the type only, never the exception object
        print(f"  {label:<38} request failed: {type(e).__name__}", flush=True)
        costs.append({"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "call": label, "path": path,
                      "params": json.dumps(params), "status": 0, "latency_s": round(time.time() - t0, 2), "items": None,
                      "usage_count": None, "cost_usd": None, "service": None, "error": type(e).__name__})
        return None
    lat = round(time.time() - t0, 2)
    try:
        body = r.json()
    except ValueError:
        body = {"non_json": r.text[:500]}
    cost = r.headers.get("X-Desearch-Cost-Usd")
    n = len(body) if isinstance(body, list) else None
    costs.append({"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "call": label, "path": path,
                  "params": json.dumps(params), "status": r.status_code, "latency_s": lat, "items": n,
                  "usage_count": r.headers.get("X-Desearch-Usage-Count"),
                  "cost_usd": round(float(cost), 6) if cost else None,
                  "service": r.headers.get("X-Desearch-Service"),
                  "error": None if r.ok else json.dumps(body)[:200]})
    print(f"  {label:<38} {r.status_code} {lat:>5.2f}s items={n} cost={costs[-1]['cost_usd']}", flush=True)
    return body if r.ok else None


def tags_of(post):
    """Hashtags from the hashtags[] field if filled, else parsed from the caption."""
    if post.get("hashtags"):
        return [h.lower().lstrip("#") for h in post["hashtags"]], "field"
    return [t.lower().rstrip(".,!?:;)") for t in TAG_RE.findall(post.get("text") or "")], "caption"


def collect(regions, count, tag_count, top_tags, comments, pulls=1):
    key = os.environ.get("DESEARCH_API_KEY")
    if not key:
        sys.exit("Set DESEARCH_API_KEY (create a key at console.desearch.ai).")
    s = requests.Session()
    s.headers.update({"Authorization": key})
    costs = []
    raw = {"fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "params": {"regions": regions, "count": count, "tag_count": tag_count, "top_tags": top_tags, "pulls": pulls},
           "trending": {}, "hashtags": {}, "comments": {}}
    print("1) trending feed per region")
    for reg in regions:
        raw["trending"][reg] = []
        for i in range(pulls):  # each pull is a different sample of the feed, so more pulls = bigger sample
            raw["trending"][reg] += get(s, costs, f"trending {reg} count={count} pull={i + 1}", "/desearch/tiktok/trending",
                                        {"region": reg, "count": count}) or []
    picked = pick_tags(raw, top_tags)
    print(f"2) hashtag posts for {picked}")
    for tag in picked:
        raw["hashtags"][tag] = get(s, costs, f"hashtag #{tag} count={tag_count}", f"/desearch/tiktok/hashtag/{tag}",
                                   {"count": tag_count}) or []
    if comments:
        top = top_post(raw)
        if top:
            print(f"3) comments on the top trending post {top['id']}")
            raw["comments"] = {"video_id": top["id"], "items": get(s, costs, f"comments {top['id']}",
                                                                   f"/desearch/tiktok/comments/{top['id']}", {"count": 20}) or []}
    raw["costs"] = costs
    return raw


def unique(posts):
    seen, out = set(), []
    for p in posts:
        if p["id"] not in seen:
            seen.add(p["id"]); out.append(p)
    return out


def pick_tags(raw, k):
    c, plays = collections.Counter(), collections.Counter()
    for posts in raw["trending"].values():
        for p in unique(posts):
            for t in dict.fromkeys(t for t in tags_of(p)[0] if not generic(t)):
                c[t] += 1
                plays[t] += (p.get("stats") or {}).get("playCount") or 0
    # most posts first, then most plays (ties are common in a 20-30 post sample)
    return sorted(c, key=lambda t: (-c[t], -plays[t]))[:k]


def top_post(raw):
    allp = [p for posts in raw["trending"].values() for p in posts]
    return max(allp, key=lambda p: (p.get("stats") or {}).get("playCount") or 0) if allp else None


def ts(v):
    try:
        return dt.datetime.fromtimestamp(int(v), dt.timezone.utc)          # live API: Unix seconds
    except (TypeError, ValueError):
        return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))   # documented: ISO string


def rows(posts, source, now):
    out = []
    for i, p in enumerate(posts):
        st = p.get("stats") or {}
        created = ts(p.get("createTime"))
        tags, tag_src = tags_of(p)
        out.append({"source": source, "position": i + 1, "id": p.get("id"), "url": p.get("url"),
                    "author": (p.get("author") or {}).get("username"), "created_utc": created.isoformat(),
                    "age_days": round((now - created).total_seconds() / 86400, 1),
                    "plays": st.get("playCount"), "likes": st.get("digCount"), "comments": st.get("commentCount"),
                    "shares": st.get("shareCount"), "saves": st.get("collectCount"),
                    "like_rate": round(st["digCount"] / st["playCount"], 4) if st.get("playCount") else None,
                    "music_title": (p.get("music") or {}).get("title"), "hashtags": " ".join(tags), "hashtag_source": tag_src,
                    "hashtags_field_len": len(p.get("hashtags") or []), "has_text": "text" in p,
                    "text": re.sub(r"\s+", " ", p.get("text") or "")[:200]})
    return out


def analyze(raw, outdir, date):
    os.makedirs(outdir, exist_ok=True)
    now = dt.datetime.fromisoformat(raw["fetched_at"])
    prow = []
    for reg, posts in raw["trending"].items():
        prow += rows(posts, f"trending:{reg}", now)
    for tag, posts in raw["hashtags"].items():
        for r in rows(posts, f"hashtag:{tag}", now):
            r["carries_tag"] = tag in r["hashtags"].split() or f"#{tag}" in r["text"].lower()
            prow.append(r)
    pdf = pd.DataFrame(prow)
    pdf.to_csv(f"{outdir}/posts-{date}.csv", index=False)
    tr = pdf[pdf.source.str.startswith("trending")]
    tr_u = tr.drop_duplicates(["source", "id"])
    # hashtag + sound aggregation on unique posts per region
    hrows = []
    for reg in raw["trending"]:
        sub = tr_u[tr_u.source == f"trending:{reg}"]
        c = collections.Counter(t for h in sub.hashtags for t in dict.fromkeys(h.split()))  # caption order, so ties sort the same every run
        for t, n in c.items():
            m = sub[sub.hashtags.str.split().apply(lambda x: t in x)]
            hrows.append({"region": reg, "hashtag": t, "posts": n, "generic": generic(t),
                          "plays": int(m.plays.sum()), "likes": int(m.likes.sum()), "shares": int(m.shares.sum())})
    hdf = pd.DataFrame(hrows).sort_values(["region", "generic", "posts", "plays"], ascending=[True, True, False, False])
    hdf.to_csv(f"{outdir}/hashtags-{date}.csv", index=False)
    music = tr_u.music_title.dropna()
    # comments
    com = raw.get("comments") or {}
    citems = com.get("items") or []
    if citems:
        pd.DataFrame([{"video_id": c.get("videoId"), "id": c.get("id"), "author": (c.get("author") or {}).get("username"),
                       "created_utc": ts(c.get("createTime")).isoformat(), "likes": c.get("likes"),
                       "text": re.sub(r"\s+", " ", c.get("text") or "")[:200]} for c in citems]).to_csv(f"{outdir}/comments-{date}.csv", index=False)
    cdf = pd.DataFrame(raw.get("costs", []))
    if len(cdf):
        cdf.to_csv(f"{outdir}/costs-{date}.csv", index=False)
    # chart: top hashtags per region (by number of trending posts carrying them)
    regs = list(raw["trending"])
    fig, axes = plt.subplots(1, len(regs), figsize=(6.5 * len(regs), 6), squeeze=False)
    for ax, reg in zip(axes[0], regs):
        top = hdf[hdf.region == reg].head(12).iloc[::-1]
        ax.barh(["#" + t for t in top.hashtag], top.posts, color=["#bbbbbb" if g else "#fe2c55" for g in top.generic])
        ax.set_title(f"{reg}: top hashtags in {tr_u[tr_u.source == f'trending:{reg}'].shape[0]} unique trending posts\n(grey = generic reach tags)")
        ax.set_xlabel("posts carrying the hashtag (parsed from captions)")
    fig.suptitle(f"TikTok Trend Board, trending feed fetched {now:%Y-%m-%d %H:%M} UTC via Desearch API")
    fig.tight_layout(); fig.savefig(f"{outdir}/top-hashtags-{date}.png", dpi=120); plt.close(fig)
    # markdown
    L = [f"# What's moving on TikTok, {date}", "",
         f"Made by Desearch (https://desearch.ai). Trending feed fetched {now:%Y-%m-%d %H:%M} UTC "
         f"with `GET /desearch/tiktok/trending` (count={raw['params']['count']} per region); hashtag posts with "
         f"`GET /desearch/tiktok/hashtag/{{tag}}` (count={raw['params']['tag_count']}).", "",
         f"![Top hashtags per region](top-hashtags-{date}.png)", ""]
    L += ["## Feed at a glance", "", "| Region | Posts returned | Unique posts | Duplicates | Median age (days) | Newest | Oldest | Total plays (unique) | Median like rate |", "|---|---|---|---|---|---|---|---|---|"]
    for reg in regs:
        a = tr[tr.source == f"trending:{reg}"]; u = tr_u[tr_u.source == f"trending:{reg}"]
        if not len(a):
            L.append(f"| {reg} | 0 | 0 | 0 | | | | | |"); continue
        L.append(f"| {reg} | {len(a)} | {len(u)} | {len(a) - len(u)} | {u.age_days.median():.0f} | {u.age_days.min():.1f} d | {u.age_days.max():.0f} d ({u.loc[u.age_days.idxmax(), 'created_utc'][:10]}) | {int(u.plays.sum()):,} | {u.like_rate.median():.1%} |")
    L += ["", "Age buckets of unique trending posts: " + ", ".join(
        f"{lab} {((tr_u.age_days >= lo) & (tr_u.age_days < hi)).sum()}" for lab, lo, hi in
        [("<1 d", 0, 1), ("1-7 d", 1, 7), ("7-30 d", 7, 30), ("30-90 d", 30, 90), (">90 d", 90, 1e9)]), ""]
    for reg in regs:
        h = hdf[hdf.region == reg]
        L += [f"## {reg}: top hashtags", "", "| Hashtag | Posts | Plays | Likes | Shares |", "|---|---|---|---|---|"]
        for _, r in h.head(10).iterrows():
            L.append(f"| #{r.hashtag}{' (generic)' if r.generic else ''} | {r.posts} | {r.plays:,} | {r.likes:,} | {r.shares:,} |")
        u = tr_u[tr_u.source == f"trending:{reg}"].sort_values("plays", ascending=False)
        L += ["", f"Top {reg} posts by plays:", "", "| Post | Plays | Likes | Shares | Posted | Caption |", "|---|---|---|---|---|---|"]
        for _, r in u.head(5).iterrows():
            L.append(f"| [@{r.author}]({r.url}) | {r.plays:,} | {r.likes:,} | {r.shares:,} | {r.created_utc[:10]} | {r.text[:70].replace('|', '/')} |")
        L.append("")
    shared = set(tr_u[tr_u.source == f"trending:{regs[0]}"].id) & set(tr_u[tr_u.source == f"trending:{regs[-1]}"].id) if len(regs) > 1 else set()
    L += ["## Across regions", "",
          f"- Posts in both {' and '.join(regs)}: {len(shared)}.",
          "- Hashtags in the top 10 of every region: " + (", ".join("#" + t for t in sorted(set.intersection(*[set(hdf[hdf.region == r].head(10).hashtag) for r in regs]))) or "none") + ".",
          f"- Sounds: `music.title` present on {len(music)} of {len(tr_u)} unique trending posts" + (": " + ", ".join(f"{k} ({v})" for k, v in music.value_counts().head(5).items()) if len(music) else " (the field is not returned, so sounds cannot be ranked).") , ""]
    hp = pdf[pdf.source.str.startswith("hashtag")]
    if len(hp):
        L += ["## Hashtag drill-down", "", "| Hashtag | Posts returned | Unique | Carry the tag in caption | Median age (days) | Oldest | Top post |", "|---|---|---|---|---|---|---|"]
        for tag in raw["hashtags"]:
            a = hp[hp.source == f"hashtag:{tag}"]
            if not len(a):
                L.append(f"| #{tag} | 0 | | | | | |"); continue
            u = a.drop_duplicates("id"); t = u.sort_values("plays", ascending=False).iloc[0]
            L.append(f"| #{tag} | {len(a)} | {len(u)} | {u.carries_tag.sum()}/{len(u)} | {u.age_days.median():.0f} | {u.age_days.max():.0f} d | [@{t.author}]({t.url}) {t.plays:,} plays |")
        L.append("")
    if citems:
        L += [f"## Comments on the top trending post ({com['video_id']})", "",
              f"- {len(citems)} comments returned; newest {min((now - ts(c['createTime'])).days for c in citems)} d old; top liked: "
              + "; ".join(f"\"{(c.get('text') or '')[:60]}\" ({c.get('likes')} likes)" for c in sorted(citems, key=lambda c: -(c.get('likes') or 0))[:3]), ""]
    L += ["## Data quality", "",
          f"- `hashtags[]` field filled on {(tr_u.hashtags_field_len > 0).sum()} of {len(tr_u)} unique trending posts; hashtags above are parsed from captions.",
          f"- Posts with no `text` field: {(~tr_u.has_text).sum()} of {len(tr_u)}.",
          f"- Duplicate post ids inside one response: {len(tr) - len(tr_u)} (trending) and {len(hp) - len(hp.drop_duplicates(['source', 'id'])) if len(hp) else 0} (hashtag)."]
    if len(cdf):
        L += [f"- Calls: {len(cdf)}, errors: {(cdf.status >= 400).sum()}, total cost ${cdf.cost_usd.fillna(0).sum():.4f} (sum of `X-Desearch-Cost-Usd`); "
              f"billed units {pd.to_numeric(cdf.usage_count).fillna(0).sum():.0f} vs items returned {cdf['items'].fillna(0).sum():.0f}.",
              f"- Latency: median {cdf.latency_s.median():.2f}s, max {cdf.latency_s.max():.2f}s."]
    L += ["", f"Files: posts-{date}.csv, hashtags-{date}.csv, comments-{date}.csv, top-hashtags-{date}.png, costs-{date}.csv, raw-{date}.json"]
    open(f"{outdir}/board-{date}.md", "w").write("\n".join(L) + "\n")
    print(f"wrote {outdir}/board-{date}.md")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--regions", nargs="+", default=["US", "GB"])
    ap.add_argument("--count", type=int, default=30, help="trending posts per region (1-100)")
    ap.add_argument("--tag-count", type=int, default=20, help="posts per drilled hashtag")
    ap.add_argument("--top-tags", type=int, default=3, help="how many hashtags to drill into")
    ap.add_argument("--pulls", type=int, default=1, help="trending calls per region (each returns a different sample)")
    ap.add_argument("--no-comments", action="store_true")
    ap.add_argument("--out", default="output")
    ap.add_argument("--from-raw", help="re-run analysis from a saved raw JSON (no API calls)")
    a = ap.parse_args()
    if a.from_raw:
        raw = json.load(open(a.from_raw))
    else:
        t0 = time.time()
        raw = collect(a.regions, a.count, a.tag_count, a.top_tags, not a.no_comments, a.pulls)
        os.makedirs(a.out, exist_ok=True)
        json.dump(raw, open(f"{a.out}/raw-{raw['fetched_at'][:10]}.json", "w"), ensure_ascii=False, indent=1)
        print(f"collected in {time.time() - t0:.1f}s")
    analyze(raw, a.out, raw["fetched_at"][:10])


if __name__ == "__main__":
    main()
