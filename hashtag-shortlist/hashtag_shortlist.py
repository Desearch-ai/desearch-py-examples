#!/usr/bin/env python3
"""Hashtag Shortlist: niche + candidate hashtags -> top public TikTok and Instagram posts per tag ->
ranked table per platform, a "use these 5" line per platform, CSV and a scatter chart. Built on the Desearch API.

Made by Desearch (https://desearch.ai)

Usage:
    export DESEARCH_API_KEY=...       # your key from console.desearch.ai
    python hashtag_shortlist.py "home gym" homegym garagegym homeworkout ...   # count 15 per tag per platform
    python hashtag_shortlist.py "home gym" homegym garagegym --count 20 --platforms tiktok
    python hashtag_shortlist.py --from-raw output/raw-2026-10-07-home-gym.json  # offline re-analysis, no API calls

Scoring is client side from stats, createTime and author. Account-level post counts are not used.
"""
import argparse, datetime as dt, json, os, re, statistics, sys, time

import requests
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE = "https://api.desearch.ai"
TBILISI = dt.timezone(dt.timedelta(hours=4))
PLATFORMS = ("tiktok", "instagram")


def call(session, costs, platform, tag, count):
    t0 = time.time()
    r = session.get(f"{BASE}/desearch/{platform}/hashtag/{tag}", params={"count": count}, timeout=120)
    lat = round(time.time() - t0, 2)
    try:
        data = r.json()
    except ValueError:
        data = {"non_json": r.text[:300]}
    items = len(data) if isinstance(data, list) else 0
    cost = r.headers.get("X-Desearch-Cost-Usd")
    uc = r.headers.get("X-Desearch-Usage-Count")
    costs.append({"ts": dt.datetime.now(TBILISI).isoformat(timespec="seconds"), "platform": platform, "tag": tag,
                  "count": count, "status": r.status_code, "latency_s": lat, "items": items,
                  "unique_items": len({p.get("id") for p in data}) if isinstance(data, list) else 0,
                  "usage_count": int(uc) if uc else None, "cost_usd": round(float(cost), 6) if cost else None})
    print(f"  {platform:<9} #{tag:<22} {r.status_code} {lat:>5.2f}s items={items} billed={uc} cost={costs[-1]['cost_usd']}", flush=True)
    return data if r.ok and isinstance(data, list) else []


def to_dt(v):
    if isinstance(v, (int, float)):
        return dt.datetime.fromtimestamp(v, dt.timezone.utc)
    if isinstance(v, str):
        return dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
    return None


def engagement(platform, p):
    s = p.get("stats") or {}
    if platform == "tiktok":
        return s.get("playCount"), s.get("digCount")
    return s.get("playCount") or s.get("viewCount"), s.get("likeCount")


def score(raw):
    now = to_dt(raw["fetched_at"])
    rows, posts = [], []
    for platform in raw["platforms"]:
        for tag in raw["tags"]:
            items = raw["results"].get(platform, {}).get(tag) or []
            ages, plays, likes, creators = [], [], [], set()
            for p in items:
                t = to_dt(p.get("createTime"))
                age = (now - t).days if t else None
                pl, lk = engagement(platform, p)
                user = (p.get("author") or {}).get("username")
                posts.append({"platform": platform, "tag": tag, "id": p.get("id"), "url": p.get("url"), "author": user,
                              "created": t.date().isoformat() if t else None, "age_days": age, "plays": pl, "likes": lk,
                              "comments": (p.get("stats") or {}).get("commentCount")})
                if age is not None: ages.append(age)
                if pl is not None: plays.append(pl)
                if lk is not None: likes.append(lk)
                if user: creators.add(user)
            n = len(items)
            rows.append({"platform": platform, "tag": tag, "posts": n,
                         "median_likes": statistics.median(likes) if likes else None,
                         "median_plays": statistics.median(plays) if plays else None,
                         "share_last_30d": round(sum(a <= 30 for a in ages) / len(ages), 2) if ages else None,
                         "newest_days": min(ages) if ages else None, "median_age_days": statistics.median(ages) if ages else None,
                         "oldest_days": max(ages) if ages else None, "creators": len(creators),
                         "creator_share": round(len(creators) / n, 2) if n else None})
    df = pd.DataFrame(rows)
    out = []
    for platform, g in df.groupby("platform", sort=False):
        g = g.copy()
        g = g[g.posts > 0]
        # rank score: median likes percentile 50%, freshness 30%, creator spread 20%
        g["score"] = (0.5 * g.median_likes.rank(pct=True) + 0.3 * g.share_last_30d.fillna(0).rank(pct=True)
                      + 0.2 * g.creator_share.fillna(0).rank(pct=True)).round(3)
        out.append(g.sort_values("score", ascending=False))
    ranked = pd.concat(out) if out else df
    return ranked, pd.DataFrame(posts)


def write(raw, ranked, posts, costs, outdir):
    os.makedirs(outdir, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", raw["niche"].lower()).strip("-")
    day = to_dt(raw["fetched_at"]).astimezone(TBILISI).date().isoformat()
    base = f"{outdir}/{day}-{slug}"
    ranked.to_csv(f"{base}-ranked.csv", index=False)
    posts.to_csv(f"{base}-posts.csv", index=False)
    if costs:
        pd.DataFrame(costs).to_csv(f"{base}-costs.csv", index=False)
    lines = [f"# Hashtag Shortlist: {raw['niche']} ({day})", "",
             f"Made by [Desearch](https://desearch.ai). Data fetched {to_dt(raw['fetched_at']).astimezone(TBILISI):%Y-%m-%d %H:%M} Asia/Tbilisi, "
             f"count={raw['count']} posts per tag per platform.", "",
             "Score = 0.5 x median-likes rank + 0.3 x share-of-posts-from-last-30-days rank + 0.2 x distinct-creator-share rank (within platform).", ""]
    fig, ax = plt.subplots(figsize=(8, 5))
    for platform, g in ranked.groupby("platform", sort=False):
        lines += [f"## {platform}", "", f"**Use these 5:** " + " ".join("#" + t for t in g.tag.head(5)), "",
                  g.drop(columns="platform").to_markdown(index=False), ""]
        ax.scatter(g.share_last_30d, g.median_likes, label=platform)
        for _, r in g.iterrows():
            ax.annotate("#" + r.tag, (r.share_last_30d, r.median_likes), fontsize=7)
    ax.set_yscale("symlog"); ax.set_xlabel("share of posts from last 30 days"); ax.set_ylabel("median likes per post")
    ax.set_title(f"Hashtags for {raw['niche']}: engagement vs freshness"); ax.legend()
    fig.tight_layout(); fig.savefig(f"{base}-scatter.png", dpi=120)
    if costs:
        c = pd.DataFrame(costs)
        lines += ["## Cost", "", f"{len(c)} calls, {int(c['items'].sum())} posts returned, {int(c.usage_count.fillna(0).sum())} billed units, "
                  f"${c.cost_usd.fillna(0).sum():.4f} (sum of X-Desearch-Cost-Usd headers).", ""]
    open(f"{base}-shortlist.md", "w").write("\n".join(lines))
    print(f"wrote {base}-shortlist.md / -ranked.csv / -posts.csv / -scatter.png")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("niche", nargs="?")
    ap.add_argument("tags", nargs="*")
    ap.add_argument("--count", type=int, default=15, help="posts per tag per platform (1-20 here)")
    ap.add_argument("--platforms", default="tiktok,instagram")
    ap.add_argument("--out", default="output")
    ap.add_argument("--from-raw")
    a = ap.parse_args()
    costs = []
    if a.from_raw:
        raw = json.load(open(a.from_raw))
    else:
        if not a.niche or not a.tags:
            ap.error("give a niche and at least one hashtag")
        if not 1 <= a.count <= 20:
            ap.error("--count must be 1..20")
        key = os.environ.get("DESEARCH_API_KEY") or sys.exit("Set DESEARCH_API_KEY (create a key at console.desearch.ai).")
        s = requests.Session(); s.headers["Authorization"] = key
        tags = [t.lstrip("#").lower() for t in a.tags]
        plats = [p for p in a.platforms.split(",") if p in PLATFORMS]
        raw = {"fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "niche": a.niche,
               "tags": tags, "platforms": plats, "count": a.count, "results": {p: {} for p in plats}}
        for p in plats:
            for t in tags:
                raw["results"][p][t] = call(s, costs, p, t, a.count)
        raw["costs"] = costs
        os.makedirs(a.out, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", a.niche.lower()).strip("-")
        path = f"{a.out}/raw-{dt.datetime.now(TBILISI).date()}-{slug}.json"
        json.dump(raw, open(path, "w")); print("raw saved:", path)
    ranked, posts = score(raw)
    write(raw, ranked, posts, costs or raw.get("costs", []), a.out)


if __name__ == "__main__":
    main()
