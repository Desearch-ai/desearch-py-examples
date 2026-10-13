#!/usr/bin/env python3
"""Posting Time Check: your account + peer accounts on TikTok, Instagram and Facebook ->
each post scored against its own account's median engagement -> weekday x time-block heatmap per platform
and a best-3 / worst-3 slot table. Built on the Desearch API.

Made by Desearch (https://desearch.ai)

Usage:
    export DESEARCH_API_KEY=...                              # your key from console.desearch.ai
    python posting_time_check.py handles.json                # live run, count 30 per account per platform
    python posting_time_check.py handles.json --tz UTC --platforms tiktok,instagram
    python posting_time_check.py --from-raw output/raw-2026-10-09.json   # offline re-analysis, no API calls

Engagement per post (public counts only):
    TikTok    likes (digCount) + comments + shares
    Instagram likes + comments
    Facebook  reactions + comments + shares (when present)
Score = engagement / median engagement of that account's returned posts (1.0 = a normal post for that account).
"""
import argparse, datetime as dt, json, os, re, statistics, sys, time
from zoneinfo import ZoneInfo

import requests
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE = "https://api.desearch.ai"
PLATFORMS = ("tiktok", "instagram", "facebook")
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
BLOCKS = ["00-04", "04-08", "08-12", "12-16", "16-20", "20-24"]
MIN_SLOT = 3  # a slot needs at least this many posts to be ranked


def fetch(session, costs, platform, handle, count, cursor=None, page=1):
    t0 = time.time()
    params = {"count": count}
    if cursor:
        params["cursor"] = cursor
    r = session.get(f"{BASE}/desearch/{platform}/profile/{handle}/posts", params=params, timeout=180)
    lat = round(time.time() - t0, 2)
    try:
        data = r.json()
    except ValueError:
        data = {"non_json": r.text[:300]}
    items = data if isinstance(data, list) else []
    cost, uc = r.headers.get("X-Desearch-Cost-Usd"), r.headers.get("X-Desearch-Usage-Count")
    costs.append({"ts": dt.datetime.now(ZoneInfo("Asia/Tbilisi")).isoformat(timespec="seconds"), "platform": platform,
                  "handle": handle, "count": count, "page": page, "cursor": cursor, "status": r.status_code, "latency_s": lat, "items": len(items),
                  "unique_items": len({p.get("id") for p in items}), "usage_count": int(uc) if uc else None,
                  "cost_usd": round(float(cost), 6) if cost else None})
    print(f"  {platform:<9} {handle:<20} p{page} {r.status_code} {lat:>5.2f}s items={len(items)} billed={uc} cost={costs[-1]['cost_usd']}", flush=True)
    return items


def next_cursor(platform, items):
    """No next-page token comes back (the body is a plain list), so the cursor is built from the last post.
    Measured 2026-10-09: TikTok takes the last post's createTime in milliseconds, Instagram takes the last post's id.
    No working cursor value was found for Facebook, so Facebook is one page per account."""
    if not items:
        return None
    last = items[-1]
    if platform == "tiktok" and isinstance(last.get("createTime"), int):
        return str(last["createTime"] * 1000)
    if platform == "instagram" and last.get("id"):
        return str(last["id"])
    return None


def fetch_account(session, costs, platform, handle, count, pages, max_age_days, first_page=None):
    """Page 1 (or a saved page 1), then more pages while the last post is younger than max_age_days."""
    items = list(first_page) if first_page is not None else fetch(session, costs, platform, handle, count)
    seen = {p.get("id") for p in items}
    page = 1
    while page < pages:
        cur = next_cursor(platform, items)
        last_t = to_utc(items[-1].get("createTime")) if items else None
        if not cur or last_t is None or (dt.datetime.now(dt.timezone.utc) - last_t).days > max_age_days:
            break
        page += 1
        new = [p for p in fetch(session, costs, platform, handle, count, cur, page) if p.get("id") not in seen]
        if not new:
            break
        seen.update(p.get("id") for p in new)
        items += new
    return items


def to_utc(v):
    """TikTok and Instagram send Unix seconds (int), Facebook sends an ISO 8601 string; all UTC."""
    if isinstance(v, (int, float)):
        return dt.datetime.fromtimestamp(v, dt.timezone.utc)
    if isinstance(v, str) and v:
        return dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
    return None


def engagement(platform, s):
    s = s or {}
    if platform == "tiktok":
        parts = [s.get("digCount"), s.get("commentCount"), s.get("shareCount")]
    elif platform == "instagram":
        parts = [s.get("likeCount"), s.get("commentCount")]
    else:
        parts = [s.get("reactionCount"), s.get("commentCount"), s.get("shareCount")]
    if not isinstance(parts[0], (int, float)):
        return None  # main count hidden or missing (for example hidden likes): leave the post out
    return sum(p for p in parts if isinstance(p, (int, float)))


def build_posts(raw, tz, max_age_days=90):
    fetched = to_utc(raw["fetched_at"])
    rows = []
    for platform, accounts in raw["results"].items():
        for handle, items in accounts.items():
            seen = set()
            for p in items:
                if p.get("id") in seen:
                    continue
                seen.add(p.get("id"))
                t = to_utc(p.get("createTime"))
                if t is None:
                    continue
                local = t.astimezone(tz)
                rows.append({"platform": platform, "handle": handle, "role": raw["roles"].get(f"{platform}:{handle}", "peer"),
                             "id": p.get("id"), "url": p.get("url"), "created_utc": t.isoformat(),
                             "created_local": local.isoformat(), "weekday": DAYS[local.weekday()], "hour": local.hour,
                             "block": BLOCKS[local.hour // 4], "age_days": round((fetched - t).total_seconds() / 86400, 1),
                             "engagement": engagement(platform, p.get("stats")),
                             "plays": (p.get("stats") or {}).get("playCount")})
    df = pd.DataFrame(rows)
    if df.empty:
        return df, df
    df["recent"] = df.age_days <= max_age_days
    df["scored"] = df.engagement.notna() & df.recent
    all_posts = df.copy()
    df = df[df.scored].copy()
    med = df.groupby(["platform", "handle"]).engagement.transform("median")
    df["account_median"] = med
    df["score"] = (df.engagement / med.replace(0, np.nan)).round(3)
    df = df[df.score.notna()]
    return df, all_posts


def slots(df):
    g = df.groupby(["platform", "weekday", "block"]).agg(posts=("score", "count"), median_score=("score", "median"),
                                                        accounts=("handle", "nunique")).reset_index()
    g["median_score"] = g.median_score.round(2)
    return g


def heatmap(df, platform, path, tzname, n_accounts):
    d = df[df.platform == platform]
    med = d.pivot_table(index="weekday", columns="block", values="score", aggfunc="median").reindex(index=DAYS, columns=BLOCKS)
    cnt = d.pivot_table(index="weekday", columns="block", values="score", aggfunc="count").reindex(index=DAYS, columns=BLOCKS).fillna(0)
    fig, ax = plt.subplots(figsize=(8, 5))
    im = ax.imshow(med.values.astype(float), cmap="RdYlGn", vmin=0, vmax=2, aspect="auto")
    for i in range(len(DAYS)):
        for j in range(len(BLOCKS)):
            n = int(cnt.values[i, j])
            v = med.values[i, j]
            ax.text(j, i, "" if n == 0 else f"{v:.2f}\nn={n}", ha="center", va="center", fontsize=7,
                    color="black" if n >= MIN_SLOT else "grey")
    ax.set_xticks(range(len(BLOCKS)), BLOCKS); ax.set_yticks(range(len(DAYS)), DAYS)
    ax.set_xlabel(f"time of day ({tzname})")
    ax.set_title(f"{platform}: median post score by slot ({len(d)} posts, {n_accounts} accounts)\n"
                 "1.0 = a normal post for that account; grey = fewer than 3 posts")
    fig.colorbar(im, ax=ax, label="median score")
    fig.tight_layout(); fig.savefig(path, dpi=120); plt.close(fig)


def write(raw, df, all_posts, costs, outdir, tzname, max_age_days):
    os.makedirs(outdir, exist_ok=True)
    day = to_utc(raw["fetched_at"]).astimezone(ZoneInfo("Asia/Tbilisi")).date().isoformat()
    base = f"{outdir}/{day}"
    all_posts.merge(df[["id", "platform", "handle", "account_median", "score"]], how="left",
                    on=["id", "platform", "handle"]).to_csv(f"{base}-posts.csv", index=False)
    sl = slots(df)
    sl.to_csv(f"{base}-slots.csv", index=False)
    if costs:
        pd.DataFrame(costs).to_csv(f"{base}-costs.csv", index=False)
    acc = all_posts.groupby(["platform", "handle", "role"]).agg(posts_returned=("id", "count"), scored=("scored", "sum"),
                                                          newest_days=("age_days", "min"), oldest_days=("age_days", "max"),
                                                          over_90_days=("age_days", lambda a: int((a > 90).sum()))).reset_index()
    acc = acc.merge(df.groupby(["platform", "handle"]).engagement.median().rename("median_engagement").reset_index(),
                    how="left", on=["platform", "handle"])
    acc.to_csv(f"{base}-accounts.csv", index=False)
    fetched = to_utc(raw["fetched_at"]).astimezone(ZoneInfo("Asia/Tbilisi"))
    lines = [f"# Posting Time Check ({day})", "",
             f"Made by [Desearch](https://desearch.ai). Data fetched {fetched:%Y-%m-%d %H:%M} Asia/Tbilisi; "
             f"slots shown in {tzname}; count={raw['count']} per request, up to {raw.get('pages', 1)} page(s) per account "
             f"(TikTok and Instagram); scored = posts from the last {max_age_days} days with a public like/reaction count.", "",
             "Score = post engagement / median engagement of that account's returned posts (1.0 = a normal post for that account). "
             f"Slots = weekday x 4-hour block. Only slots with at least {MIN_SLOT} posts are ranked. "
             "This describes public engagement on the recent posts in this sample only. It says nothing about reach, "
             "and it is not a rule for other accounts or niches.", ""]
    best_rows = []
    for platform in [p for p in PLATFORMS if p in df.platform.unique()]:
        d = df[df.platform == platform]
        n_acc = d.handle.nunique()
        heatmap(df, platform, f"{base}-heatmap-{platform}.png", tzname, n_acc)
        s = sl[(sl.platform == platform) & (sl.posts >= MIN_SLOT)].sort_values("median_score", ascending=False)
        span = f"{d.created_utc.min()[:10]} to {d.created_utc.max()[:10]}"
        lines += [f"## {platform}", "", f"Sample: {len(d)} posts from {n_acc} accounts, posted {span} (UTC dates); "
                  f"{len(s)} of 42 slots have {MIN_SLOT}+ posts.", ""]
        if len(s) >= 2:
            k = min(3, len(s) // 2)  # best and worst never share a slot
            top, bottom = s.head(k), s.tail(k).iloc[::-1]
            for kind, part in (("best", top), ("worst", bottom)):
                for _, r in part.iterrows():
                    best_rows.append({"platform": platform, "kind": kind, "slot": f"{r.weekday} {r.block}",
                                      "median_score": r.median_score, "posts": int(r.posts),
                                      "accounts": int(r.accounts)})
            spread = top.median_score.iloc[0] - bottom.median_score.iloc[0]
            small = s.posts.median() < 6
            note = []
            if small:
                note.append(f"median slot has {s.posts.median():.0f} posts, so single posts move the result")
            if spread < 0.5:
                note.append(f"best and worst slot differ by only {spread:.2f}")
            lines += ["| | slot | median score | posts | accounts |", "|---|---|---|---|---|"]
            lines += [f"| best | {r.weekday} {r.block} | {r.median_score:.2f} | {int(r.posts)} | {int(r.accounts)} |" for _, r in top.iterrows()]
            lines += [f"| worst | {r.weekday} {r.block} | {r.median_score:.2f} | {int(r.posts)} | {int(r.accounts)} |" for _, r in bottom.iterrows()]
            lines += ["", "Read with care: " + "; ".join(note) + "." if note else "", ""]
        else:
            lines += ["Too few posts per slot to rank slots on this platform.", ""]
        lines += [f"![{platform} heatmap]({os.path.basename(base)}-heatmap-{platform}.png)", ""]
    pd.DataFrame(best_rows).to_csv(f"{base}-best-worst.csv", index=False)
    lines += ["## Accounts", "", acc.to_markdown(index=False), ""]
    if costs:
        c = pd.DataFrame(costs)
        lines += ["## Cost", "", f"{len(c)} calls, {int(c['items'].sum())} posts returned, {int(c.usage_count.fillna(0).sum())} billed units, "
                  f"${c.cost_usd.fillna(0).sum():.4f} (sum of X-Desearch-Cost-Usd headers).", ""]
    open(f"{base}-report.md", "w").write("\n".join(lines))
    print(f"wrote {base}-report.md, -posts.csv, -slots.csv, -best-worst.csv, -accounts.csv, heatmap PNGs")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("handles", nargs="?", help="JSON file with main and peers (see handles.json)")
    ap.add_argument("--count", type=int, default=30, help="posts requested per account per platform (1-100)")
    ap.add_argument("--platforms", default="tiktok,instagram,facebook")
    ap.add_argument("--tz", default="Asia/Tbilisi", help="time zone for the slots, e.g. UTC or America/New_York")
    ap.add_argument("--pages", type=int, default=1, help="pages per account on TikTok and Instagram (Facebook: 1)")
    ap.add_argument("--max-age-days", type=int, default=90, help="score only posts from the last N days; stop paging past it")
    ap.add_argument("--reuse-raw", help="earlier raw JSON: reuse its page-1 results instead of calling again")
    ap.add_argument("--out", default="output")
    ap.add_argument("--from-raw")
    a = ap.parse_args()
    tz = ZoneInfo(a.tz)
    costs = []
    if a.from_raw:
        raw = json.load(open(a.from_raw))
    else:
        if not a.handles:
            ap.error("give a handles JSON file (see handles.json)")
        if not 1 <= a.count <= 100:
            ap.error("--count must be 1..100")
        key = os.environ.get("DESEARCH_API_KEY") or sys.exit("Set DESEARCH_API_KEY (create a key at console.desearch.ai).")
        cfg = json.load(open(a.handles))
        s = requests.Session(); s.headers["Authorization"] = key
        plats = [p for p in a.platforms.split(",") if p in PLATFORMS]
        prev = json.load(open(a.reuse_raw)) if a.reuse_raw else None
        raw = {"fetched_at": (prev or {}).get("fetched_at") or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
               "count": a.count, "pages": a.pages, "results": {p: {} for p in plats}, "roles": {}}
        if prev:
            raw["reused_from"] = a.reuse_raw
            costs.extend(prev.get("costs", []))
        for p in plats:
            for role, entry in [("main", cfg["main"])] + [("peer", e) for e in cfg["peers"]]:
                h = entry.get(p)
                if not h:
                    continue
                raw["roles"][f"{p}:{h}"] = role
                first = None
                if prev and h in prev["results"].get(p, {}):
                    first = prev["results"][p][h][: a.count]
                n = a.pages if p in ("tiktok", "instagram") else 1
                if first is not None and n == 1:
                    raw["results"][p][h] = first
                else:
                    raw["results"][p][h] = fetch_account(s, costs, p, h, a.count, n, a.max_age_days, first)
        raw["costs"] = costs
        os.makedirs(a.out, exist_ok=True)
        path = f"{a.out}/raw-{dt.datetime.now(ZoneInfo('Asia/Tbilisi')).date()}{'-p' + str(a.pages) if a.pages > 1 else ''}.json"
        json.dump(raw, open(path, "w")); print("raw saved:", path)
    df, all_posts = build_posts(raw, tz, a.max_age_days)
    if df.empty:
        sys.exit("no posts returned")
    write(raw, df, all_posts, costs or raw.get("costs", []), a.out, a.tz, a.max_age_days)


if __name__ == "__main__":
    main()
