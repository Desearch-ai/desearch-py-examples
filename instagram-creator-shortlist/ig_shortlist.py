#!/usr/bin/env python3
"""Instagram Creator Shortlist: keyword -> public Instagram profiles -> recent posts -> ranked shortlist
by follower tier and engagement, built on the Desearch API.

Made by Desearch (https://desearch.ai)

Usage:
    export DESEARCH_API_KEY=...                  # your key from console.desearch.ai
    python ig_shortlist.py "home gym"            # search 20, profile all, posts for up to 10 creators
    python ig_shortlist.py "vegan baking" --search-count 15 --max-creators 8 --posts 12
    python ig_shortlist.py --from-raw output/raw-2026-10-06-home-gym.json   # offline re-analysis

The official Python SDK (desearch-py 1.2.1) has no Instagram methods, so this script calls the REST API directly.
"""
import argparse, collections, datetime as dt, json, os, re, statistics, sys, time

import requests
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE = "https://api.desearch.ai"
TIERS = [("nano", 1_000, 10_000), ("micro", 10_000, 100_000), ("mid", 100_000, 500_000), ("macro", 500_000, 10**12)]


def tier(f):
    for name, lo, hi in TIERS:
        if lo <= f < hi:
            return name
    return "under 1k"


def call(session, costs, label, method, path, params=None, body=None):
    """One request; records status, latency, items and billing headers. Never logs request headers (API key)."""
    t0 = time.time()
    try:
        r = session.request(method, BASE + path, params=params, json=body, timeout=120)
    except requests.RequestException as e:  # log the type only, never the exception object
        print(f"  {label:<44} request failed: {type(e).__name__}", flush=True)
        costs.append({"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "call": label, "method": method, "path": path,
                      "status": 0, "latency_s": round(time.time() - t0, 2), "items": 0, "usage_count": None,
                      "cost_usd": None, "service": None, "error": type(e).__name__})
        return None
    lat = round(time.time() - t0, 2)
    try:
        data = r.json()
    except ValueError:
        data = {"non_json": r.text[:500]}
    cost = r.headers.get("X-Desearch-Cost-Usd")
    items = len(data) if isinstance(data, list) else (1 if r.ok and isinstance(data, dict) else 0)
    costs.append({"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "call": label, "method": method, "path": path,
                  "status": r.status_code, "latency_s": lat, "items": items,
                  "usage_count": int(r.headers["X-Desearch-Usage-Count"]) if r.headers.get("X-Desearch-Usage-Count") else None,
                  "cost_usd": round(float(cost), 6) if cost else None, "service": r.headers.get("X-Desearch-Service"),
                  "error": None if r.ok else json.dumps(data)[:200]})
    print(f"  {label:<44} {r.status_code} {lat:>5.2f}s items={items} cost={costs[-1]['cost_usd']}", flush=True)
    return data if r.ok else None


def collect(query, search_count, max_creators, posts, min_followers):
    key = os.environ.get("DESEARCH_API_KEY")
    if not key:
        sys.exit("Set DESEARCH_API_KEY (create a key at console.desearch.ai).")
    s = requests.Session()
    s.headers.update({"Authorization": key, "Content-Type": "application/json"})
    costs = []
    raw = {"fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "query": query,
           "params": {"search_count": search_count, "max_creators": max_creators, "posts": posts, "min_followers": min_followers},
           "search": [], "profiles": {}, "posts": {}}
    print(f"1) search Instagram profiles for {query!r}")
    raw["search"] = call(s, costs, f"search {query!r} count={search_count}", "POST", "/desearch/instagram/search",
                         body={"query": query, "count": search_count}) or []
    seen = []
    for r in raw["search"]:
        if r.get("type", "profile") == "profile" and r.get("username") and r["username"] not in seen:
            seen.append(r["username"])
    print(f"2) profile lookup for {len(seen)} usernames")
    for u in seen:
        raw["profiles"][u] = call(s, costs, f"profile {u}", "GET", f"/desearch/instagram/profile/{u}")
    picks = [u for u, p in raw["profiles"].items()
             if p and not p.get("private") and (p.get("followers") or 0) >= min_followers]
    picks = sorted(picks, key=lambda u: -raw["profiles"][u]["followers"])[:max_creators]
    print(f"3) recent posts for {len(picks)} public creators with >= {min_followers:,} followers")
    for u in picks:
        raw["posts"][u] = call(s, costs, f"posts {u} count={posts}", "GET", f"/desearch/instagram/profile/{u}/posts",
                               params={"count": posts}) or []
    raw["costs"] = costs
    return raw


def ts(v):
    try:
        return dt.datetime.fromtimestamp(int(v), dt.timezone.utc)          # live API: Unix seconds
    except (TypeError, ValueError):
        return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))   # documented: ISO string


def analyze(raw, outdir, stem):
    os.makedirs(outdir, exist_ok=True)
    now = dt.datetime.fromisoformat(raw["fetched_at"])
    search_by_user = {r.get("username"): r for r in raw["search"]}
    prow, crow = [], []
    for u, posts in raw["posts"].items():
        prof = raw["profiles"][u]
        f = prof.get("followers") or 0
        # Instagram returns pinned posts first (up to 3). Treat a leading post as pinned when a later post is newer.
        pinned = {posts[i].get("id") for i in range(min(3, len(posts)))
                  if any(ts(q["createTime"]) > ts(posts[i]["createTime"]) for q in posts[i + 1:])}
        uniq_all = list({p.get("id"): p for p in posts}.values())
        uniq = [p for p in uniq_all if p.get("id") not in pinned] or uniq_all
        dated = sorted(uniq, key=lambda p: ts(p["createTime"]), reverse=True)
        for i, p in enumerate(posts):
            st = p.get("stats") or {}
            c = ts(p["createTime"])
            prow.append({"username": u, "position": i + 1, "id": p.get("id"), "shortcode": p.get("shortcode"), "url": p.get("url"),
                         "created_utc": c.isoformat(), "age_days": round((now - c).total_seconds() / 86400, 1),
                         "media_type": p.get("mediaType"), "likes": st.get("likeCount"), "comments": st.get("commentCount"),
                         "plays": st.get("playCount"), "views": st.get("viewCount"),
                         "out_of_order": i > 0 and ts(posts[i - 1]["createTime"]) < c, "pinned_guess": p.get("id") in pinned,
                         "hashtags_field": len(p.get("hashtags") or []),
                         "caption_hashtags": len(re.findall(r"#\w+", p.get("caption") or "")),
                         "caption": re.sub(r"\s+", " ", p.get("caption") or "")[:160]})
        if not uniq:
            crow.append({"username": u, "followers": f, "tier": tier(f), "posts_returned": 0}); continue
        likes = [p["stats"].get("likeCount") or 0 for p in uniq]
        comms = [p["stats"].get("commentCount") or 0 for p in uniq]
        ers = [(l + c) / f for l, c in zip(likes, comms)] if f else [0]
        gaps = [(ts(a["createTime"]) - ts(b["createTime"])).total_seconds() / 86400 for a, b in zip(dated, dated[1:])]
        crow.append({"username": u, "full_name": prof.get("fullName"), "verified": prof.get("verified"),
                     "followers": f, "tier": tier(f), "search_followers": (search_by_user.get(u) or {}).get("followers"),
                     "posts_count_field": prof.get("postsCount"), "posts_returned": len(posts), "unique_posts": len(uniq),
                     "median_likes": statistics.median(likes), "median_comments": statistics.median(comms),
                     "median_er_pct": round(statistics.median(ers) * 100, 2), "mean_er_pct": round(statistics.mean(ers) * 100, 2),
                     "pinned_excluded": len(uniq_all) - len(uniq),
                     "posts_last_30d": sum((now - ts(p["createTime"])).days < 30 for p in uniq),
                     "median_gap_days": round(statistics.median(gaps), 1) if gaps else None,
                     "days_since_last_post": round((now - ts(dated[0]["createTime"])).total_seconds() / 86400, 1),
                     "oldest_post_days": round((now - ts(dated[-1]["createTime"])).total_seconds() / 86400, 1),
                     "video_share": round(sum(p.get("mediaType") == "video" for p in uniq) / len(uniq), 2),
                     "zero_comment_posts": sum(c == 0 for c in comms),
                     "url": f"https://www.instagram.com/{u}/"})
    pdf, cdf = pd.DataFrame(prow), pd.DataFrame(crow)
    pdf.to_csv(f"{outdir}/posts-{stem}.csv", index=False)
    # every searched profile, so search-vs-profile checks cover all of them
    def vc(series):
        """value counts as 'value (n)', with missing values shown as 'missing' instead of nan."""
        return ", ".join(f"{'missing' if pd.isna(k) else int(k)} ({v})" for k, v in series.value_counts(dropna=False).items())

    allp = []
    for u, p in raw["profiles"].items():
        sr = search_by_user.get(u) or {}
        allp.append({"username": u, "search_followers": sr.get("followers"), "search_mediaCount": sr.get("mediaCount"),
                     "profile_followers": (p or {}).get("followers"), "profile_postsCount": (p or {}).get("postsCount"),
                     "private": (p or {}).get("private"), "verified": (p or {}).get("verified"),
                     "profile_ok": p is not None, "in_shortlist_pull": u in raw["posts"]})
    adf = pd.DataFrame(allp)
    if len(cdf):
        cdf["stale"] = cdf.days_since_last_post > 30
        cdf = cdf.sort_values(["tier", "stale", "median_er_pct"], ascending=[True, True, False])
        cdf.to_csv(f"{outdir}/shortlist-{stem}.csv", index=False)
    adf.to_csv(f"{outdir}/profiles-{stem}.csv", index=False)
    costs = pd.DataFrame(raw.get("costs", []))
    if len(costs):
        costs.to_csv(f"{outdir}/costs-{stem}.csv", index=False)
    # chart: followers vs median engagement rate
    if len(cdf):
        fig, ax = plt.subplots(figsize=(10, 6.5))
        colors = {"nano": "#2a9d8f", "micro": "#e9c46a", "mid": "#f4a261", "macro": "#e76f51", "under 1k": "#999999"}
        for t, g in cdf.groupby("tier"):
            ax.scatter(g.followers, g.median_er_pct, s=60 + 140 * g.video_share.fillna(0), c=colors.get(t, "#555"), label=t, alpha=.85, linewidths=0)
            st = g[g.stale]
            if len(st):
                ax.scatter(st.followers, st.median_er_pct, s=60 + 140 * st.video_share.fillna(0), facecolors="none", edgecolors="black", linewidths=1.5)
            for _, r in g.iterrows():
                ax.annotate("@" + r.username, (r.followers, r.median_er_pct), fontsize=8, xytext=(4, 4), textcoords="offset points")
        ax.set_xscale("log"); ax.set_xlabel("followers (profile call, log scale)"); ax.set_ylabel("median engagement rate per post, % ((likes+comments)/followers)")
        ax.set_title(f"Instagram creators for {raw['query']!r}: reach vs engagement\n(bubble size = share of video posts, black edge = no post in 30+ days)")
        ax.legend(title="tier"); ax.grid(alpha=.3)
        fig.tight_layout(); fig.savefig(f"{outdir}/engagement-{stem}.png", dpi=120); plt.close(fig)
    # markdown
    L = [f"# Instagram creator shortlist: {raw['query']!r}, {now:%Y-%m-%d}", "",
         f"Made by Desearch (https://desearch.ai). Fetched {now:%Y-%m-%d %H:%M} UTC: `POST /desearch/instagram/search` "
         f"(count={raw['params']['search_count']}), `GET /desearch/instagram/profile/{{username}}` for every result, and "
         f"`GET /desearch/instagram/profile/{{username}}/posts` (count={raw['params']['posts']}) for up to {raw['params']['max_creators']} "
         f"public creators with at least {raw['params']['min_followers']:,} followers.", "",
         "Engagement rate = (likes + comments) / followers per post, median over the posts returned (pinned posts excluded). Cadence = posts in the last 30 days and median days between posts.", "",
         f"![Followers vs median engagement rate](engagement-{stem}.png)", ""]
    for t, _, _ in TIERS:
        g = cdf[cdf.tier == t] if len(cdf) else cdf
        if not len(g):
            continue
        L += [f"## {t.capitalize()} creators", "", "| Rank | Creator | Followers | Median ER | Median likes | Median comments | Posts in 30 d | Median gap | Last post | Video share |", "|---|---|---|---|---|---|---|---|---|---|"]
        for i, (_, r) in enumerate(g.iterrows(), 1):
            flag = " (stale)" if r.stale else ""
            L.append(f"| {i} | [@{r.username}]({r.url}){' ✓' if r.verified else ''} | {r.followers:,} | {r.median_er_pct:.2f}% | {r.median_likes:,.0f} | {r.median_comments:,.0f} | {r.posts_last_30d} | {r.median_gap_days} d | {r.days_since_last_post:.0f} d ago{flag} | {r.video_share:.0%} |")
        L.append("")
    skipped = adf[~adf.in_shortlist_pull]
    L += ["## Searched but not pulled", "",
          f"{len(skipped)} of {len(adf)} search results were not pulled: " + ", ".join(
              f"@{r.username} ({'private' if r.private else ('profile lookup failed' if not r.profile_ok else f'{int(r.profile_followers or 0):,} followers')})"
              for _, r in skipped.iterrows()), ""]
    # data quality
    both = adf.dropna(subset=["search_followers", "profile_followers"])
    match = (both.search_followers == both.profile_followers).sum()
    L += ["## Data quality checks", "",
          f"- Search results: {len(raw['search'])}, types: " + ", ".join(f"{k} {v}" for k, v in collections.Counter(r.get('type') for r in raw['search']).items())
          + f"; repeated usernames: {len(raw['search']) - len({r.get('username') for r in raw['search']})}.",
          f"- Followers, search vs profile call: {match} of {len(both)} identical" + (
              "; differences: " + ", ".join(f"@{r.username} {int(r.search_followers):,} vs {int(r.profile_followers):,}" for _, r in both[both.search_followers != both.profile_followers].iterrows())
              if match < len(both) else "") + ".",
          f"- `postsCount` on profiles: {vc(adf.profile_postsCount)}; search `mediaCount`: {vc(adf.search_mediaCount)}."]
    if len(pdf):
        L += [f"- Posts returned per creator: " + ", ".join(f"{k} ({v})" for k, v in cdf.posts_returned.value_counts().items()) + f" (requested {raw['params']['posts']}).",
              f"- Duplicate post ids: {len(pdf) - pdf.drop_duplicates(['username', 'id']).shape[0]}.",
              f"- Posts out of date order (newer than the post before it): {int(pdf.out_of_order.sum())} across {pdf[pdf.out_of_order].username.nunique()} creators; leading posts treated as pinned and excluded from ER/cadence: {int(pdf.pinned_guess.sum())} (no pinned flag in the response).",
              f"- Post age: median {pdf.age_days.median():.0f} d, newest {pdf.age_days.min():.1f} d, oldest {pdf.age_days.max():.0f} d.",
              f"- Posts with `commentCount` 0: {int((pdf.comments == 0).sum())} of {len(pdf)}; `viewCount` present on {int(pdf.views.notna().sum())}, `playCount` on {int(pdf.plays.notna().sum())}.",
              f"- `hashtags[]` filled on {int((pdf.hashtags_field > 0).sum())} posts; captions containing #tags: {int((pdf.caption_hashtags > 0).sum())}."]
    if len(costs):
        L += [f"- Calls: {len(costs)}, errors: {int((costs.status >= 400).sum())}, total cost ${costs.cost_usd.fillna(0).sum():.4f} (sum of `X-Desearch-Cost-Usd`); "
              f"billed units {int(costs.usage_count.fillna(0).sum())} vs items returned {int(costs['items'].sum())}.",
              f"- Latency: median {costs.latency_s.median():.2f}s, max {costs.latency_s.max():.2f}s."]
    L += ["", f"Files: shortlist-{stem}.csv, profiles-{stem}.csv, posts-{stem}.csv, engagement-{stem}.png, costs-{stem}.csv, raw-{stem}.json"]
    open(f"{outdir}/shortlist-{stem}.md", "w").write("\n".join(L) + "\n")
    print(f"wrote {outdir}/shortlist-{stem}.md")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query", nargs="?", default="home gym", help="niche keyword")
    ap.add_argument("--search-count", type=int, default=20, help="profiles to search (1-20 recommended)")
    ap.add_argument("--max-creators", type=int, default=10, help="creators to pull posts for (largest first)")
    ap.add_argument("--posts", type=int, default=12, help="posts per creator")
    ap.add_argument("--min-followers", type=int, default=1000)
    ap.add_argument("--out", default="output")
    ap.add_argument("--from-raw", help="re-run analysis from a saved raw JSON (no API calls)")
    a = ap.parse_args()
    if a.from_raw:
        raw = json.load(open(a.from_raw))
    else:
        t0 = time.time()
        raw = collect(a.query, a.search_count, a.max_creators, a.posts, a.min_followers)
        print(f"collected in {time.time() - t0:.1f}s")
    stem = f"{raw['fetched_at'][:10]}-{re.sub(r'[^a-z0-9]+', '-', raw['query'].lower()).strip('-')}"
    if not a.from_raw:
        os.makedirs(a.out, exist_ok=True)
        json.dump(raw, open(f"{a.out}/raw-{stem}.json", "w"), ensure_ascii=False, indent=1)
    analyze(raw, a.out, stem)


if __name__ == "__main__":
    main()
