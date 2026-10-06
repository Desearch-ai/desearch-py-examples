#!/usr/bin/env python3
"""City Trends Pulse: a 'what's moving where' snapshot of X trends per location, built on the Desearch API.

Made by Desearch (https://desearch.ai)

Usage:
    export DESEARCH_API_KEY=...          # your key from console.desearch.ai
    python trends.py                     # default locations, top 4 trends each
    python trends.py --top 3 --posts 20  # fewer trends, posts fetched per trend
    python trends.py --from-raw output/raw-2026-10-04.json   # re-run the analysis offline, no API calls
"""
import argparse, asyncio, collections, datetime as dt, json, os, re, sys, time, unicodedata

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# (label, WOEID). WOEIDs from the list linked in the Desearch API reference for GET /twitter/trends.
# Georgia (23424823) is NOT in that list; it is included on purpose to show how unsupported places behave.
LOCATIONS = [
    ("Worldwide", 1),
    ("United States", 23424977),
    ("United Kingdom", 23424975),
    ("New York", 2459115),
    ("London", 44418),
    ("Istanbul", 2344116),
    ("Georgia", 23424823),
]


def parse_ts(s):
    """GET /twitter returns legacy 'Sat Oct 03 08:00:00 +0000 2026'; be tolerant of ISO too."""
    if not s:
        return None
    for fn in (lambda x: dt.datetime.strptime(x, "%a %b %d %H:%M:%S %z %Y"),
               lambda x: dt.datetime.fromisoformat(x.replace("Z", "+00:00"))):
        try:
            return fn(s)
        except ValueError:
            pass
    return None


def norm(name):
    """Normalize a trend name for cross-location matching: casefold, drop '#', quotes, accents."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode() or name
    return re.sub(r"[#\"']", "", s).strip().casefold()


def dump(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, list):
        return [dump(x) for x in obj]
    return obj


async def timed(costs, label, coro):
    """Await one SDK call, record latency and billing metadata. Never log repr(e): the SDK's
    aiohttp exception repr includes request headers, i.e. the API key."""
    t0 = time.time()
    err, res = None, None
    try:
        res = await coro
    except Exception as e:
        err = f"{type(e).__name__}: status={getattr(e, 'status', '?')} message={str(getattr(e, 'message', ''))[:200]}"
    latency = round(time.time() - t0, 2)
    meta = getattr(res, "metadata", None)
    costs.append({
        "ts": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "call": label, "latency_s": latency, "ok": err is None,
        "cost_usd": round(meta.cost_usd, 6) if meta and meta.cost_usd is not None else None,
        "usage_count": meta.usage_count if meta else None,
        "service": meta.service if meta else None, "error": err,
    })
    print(f"  {label:<55} {latency:>6.2f}s  cost={costs[-1]['cost_usd']}  {err or ''}", flush=True)
    return res.data if res is not None else None


async def collect(top_n, posts_count, replies):
    from desearch_py import Desearch
    key = os.environ.get("DESEARCH_API_KEY")
    if not key:
        sys.exit("Set DESEARCH_API_KEY (create a key at console.desearch.ai).")
    costs, raw = [], {"fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                      "params": {"top_n": top_n, "posts_count": posts_count, "replies": replies},
                      "trends": {}, "searches": {}, "replies": {}}
    start_date = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).strftime("%Y-%m-%d")
    raw["params"]["start_date"] = start_date
    async with Desearch(api_key=key) as d:
        print("1) trends per WOEID")
        for label, woeid in LOCATIONS:
            data = await timed(costs, f"x_trends {label} ({woeid})", d.x_trends(woeid=woeid, count=30, include_metadata=True))
            raw["trends"][label] = {"requested_woeid": woeid, "response": dump(data)}
        # one search per unique trend query among the top N of each supported location
        queries = {}
        for label, t in raw["trends"].items():
            r = t["response"] or {}
            if not supported(t):
                continue
            for tr in r.get("trends", [])[:top_n]:
                queries.setdefault(tr.get("query") or tr["name"], tr["name"])
        print(f"2) X search for {len(queries)} unique trend queries (sort=Top, start_date={start_date})")
        for q, name in queries.items():
            data = await timed(costs, f"x_search {name[:40]}", d.x_search(query=q, sort="Top", start_date=start_date,
                                                                         count=posts_count, include_metadata=True))
            raw["searches"][q] = {"trend": name, "posts": dump(data) if data is not None else None}
        if replies:
            print("3) replies to the #1 post per location")
            for label, t in raw["trends"].items():
                if not supported(t):
                    continue
                top = top_posts_for_location(raw, label, top_n, 1)
                if top:
                    pid = top[0]["id"]
                    data = await timed(costs, f"x_post_replies {label} {pid}", d.x_post_replies(post_id=pid, count=10, include_metadata=True))
                    raw["replies"][label] = {"post_id": pid, "replies": dump(data) if data is not None else None}
    raw["costs"] = costs
    return raw


def supported(t):
    """GET /twitter/trends returns HTTP 200 with woeid=null and Worldwide-like trends for WOEIDs it does
    not know. Treat a missing or mismatched woeid echo as unsupported."""
    r = t.get("response") or {}
    w = r.get("woeid") or {}
    return bool(r.get("trends")) and w.get("id") == t["requested_woeid"]


def engagement(p):
    return (p.get("like_count") or 0) + 2 * (p.get("retweet_count") or 0) + (p.get("reply_count") or 0) + (p.get("quote_count") or 0)


def top_posts_for_location(raw, label, top_n, k):
    r = raw["trends"][label]["response"]
    out = []
    for tr in r.get("trends", [])[:top_n]:
        posts = (raw["searches"].get(tr.get("query") or tr["name"]) or {}).get("posts") or []
        out += sorted(posts, key=engagement, reverse=True)[:k]
    return sorted(out, key=engagement, reverse=True)


def is_relevant(trend_name, query, text, entities):
    """Does the post actually mention the trend? Match the trend name (or any quoted phrase / word of the
    trend query) in the text or hashtags, case- and accent-insensitive."""
    t = norm(text)
    tags = {norm(h.get("text", "")) for h in ((entities or {}).get("hashtags") or [])}
    n = norm(trend_name)
    if n and (n in t or n.replace(" ", "") in t.replace(" ", "") or n in tags):
        return True
    return False


def analyze(raw, outdir, date):
    os.makedirs(outdir, exist_ok=True)
    now = dt.datetime.fromisoformat(raw["fetched_at"])
    top_n = raw["params"]["top_n"]
    # ---- trends table
    trows, unsupported = [], []
    for label, t in raw["trends"].items():
        r = t["response"] or {}
        ok = supported(t)
        if not ok:
            unsupported.append((label, t["requested_woeid"], r.get("woeid"), len(r.get("trends", []))))
        for tr in r.get("trends", []):
            extra = {k: v for k, v in tr.items() if k not in ("name", "query", "rank")}
            trows.append({"location": label, "requested_woeid": t["requested_woeid"],
                          "returned_woeid": (r.get("woeid") or {}).get("id"), "supported": ok,
                          "rank": tr.get("rank"), "name": tr["name"], "query": tr.get("query"),
                          "volume": tr.get("tweet_volume", tr.get("volume")), "extra_fields": json.dumps(extra) if extra else ""})
    tdf = pd.DataFrame(trows)
    tdf.to_csv(f"{outdir}/trends-{date}.csv", index=False)
    sup = tdf[tdf.supported]
    locs = list(dict.fromkeys(sup.location))
    # ---- overlap
    sets = {l: set(sup[sup.location == l].name.map(norm)) for l in locs}
    jac = pd.DataFrame([[len(sets[a] & sets[b]) / max(1, len(sets[a] | sets[b])) for b in locs] for a in locs], index=locs, columns=locs)
    share = sup.assign(n=sup.name.map(norm)).groupby("n").location.nunique()
    display = sup.assign(n=sup.name.map(norm)).groupby("n").name.first()
    multi = share[share >= 3].sort_values(ascending=False)
    local_only = {l: [display[n] for n in sorted(sets[l]) if share[n] == 1] for l in locs}
    vol_share = sup.volume.notna().mean() if len(sup) else 0
    # ---- posts table
    prow = []
    for q, s in raw["searches"].items():
        posts = s.get("posts") or []
        ranked = sorted(posts, key=engagement, reverse=True)
        for i, p in enumerate(ranked):
            ts = parse_ts(p.get("created_at"))
            prow.append({"trend": s["trend"], "query": q, "rank_in_trend": i + 1, "kept_top3": i < 3,
                         "id": p.get("id"), "url": p.get("url"), "author": (p.get("user") or {}).get("username"),
                         "created_at_utc": ts.isoformat() if ts else p.get("created_at"),
                         "age_h": round((now - ts).total_seconds() / 3600, 1) if ts else None,
                         "lang": p.get("lang"), "likes": p.get("like_count"), "retweets": p.get("retweet_count"),
                         "replies": p.get("reply_count"), "quotes": p.get("quote_count"), "views": p.get("view_count"),
                         "engagement": engagement(p), "is_retweet": p.get("is_retweet"),
                         "relevant": is_relevant(s["trend"], q, p.get("text", ""), p.get("entities")),
                         "text": re.sub(r"\s+", " ", p.get("text", ""))[:280]})
    pdf = pd.DataFrame(prow)
    pdf.to_csv(f"{outdir}/posts-{date}.csv", index=False)
    top3 = pdf[pdf.kept_top3] if len(pdf) else pdf
    # dupes: same normalized text under different ids, same post id under several trends, same author many times
    if len(pdf):
        txt = pdf.assign(t=pdf.text.str.lower().str.replace(r"https?://\S+|\W+", " ", regex=True).str.strip())
        dup_text = txt[txt.t.str.len() > 20].groupby("t").id.nunique()
        dup_text = dup_text[dup_text > 1]
        multi_trend_ids = pdf.groupby("id").trend.nunique()
        multi_trend_ids = multi_trend_ids[multi_trend_ids > 1]
        heavy = pdf.groupby("author").id.nunique().sort_values(ascending=False)
        heavy = heavy[heavy >= 3]
    # ---- costs
    cdf = pd.DataFrame(raw.get("costs", []))
    if len(cdf):
        cdf.to_csv(f"{outdir}/costs-{date}.csv", index=False)
    # ---- chart: overlap heatmap + per-location share of top posts that mention the trend
    fig, ax = plt.subplots(1, 2, figsize=(14, 6), gridspec_kw={"width_ratios": [1.2, 1]})
    im = ax[0].imshow(jac.values, cmap="Blues", vmin=0, vmax=1)
    ax[0].set_xticks(range(len(locs)), locs, rotation=35, ha="right"); ax[0].set_yticks(range(len(locs)), locs)
    for i in range(len(locs)):
        for j in range(len(locs)):
            ax[0].text(j, i, f"{len(sets[locs[i]] & sets[locs[j]])}", ha="center", va="center",
                       color="white" if jac.values[i, j] > .5 else "black", fontsize=9)
    ax[0].set_title("Shared trends between locations (top 30 each)\ncolor = Jaccard, number = shared trends")
    fig.colorbar(im, ax=ax[0], fraction=.046)
    per_loc = []
    for l in locs:
        names = list(sup[sup.location == l].sort_values("rank").name[:top_n])
        sub = top3[top3.trend.isin(names)] if len(top3) else top3
        per_loc.append((l, sub.relevant.mean() * 100 if len(sub) else 0, sub.age_h.median() if len(sub) else 0))
    ax[1].barh([p[0] for p in per_loc][::-1], [p[1] for p in per_loc][::-1], color="#2a7ab9")
    ax[1].set_xlim(0, 100); ax[1].set_xlabel("% of kept top posts whose text mentions the trend")
    ax[1].set_title(f"Relevance of top posts (top {top_n} trends x top 3 posts)")
    fig.suptitle(f"City Trends Pulse, X trends fetched {now:%Y-%m-%d %H:%M} UTC via Desearch API")
    fig.tight_layout(); fig.savefig(f"{outdir}/overlap-{date}.png", dpi=120); plt.close(fig)
    # ---- markdown snapshot
    L = [f"# What's moving where, {date}", "",
         f"Made by Desearch (https://desearch.ai). Trends fetched {now:%Y-%m-%d %H:%M} UTC with `GET /twitter/trends`; "
         f"posts with `GET /twitter` (sort=Top, start_date={raw['params']['start_date']}, count={raw['params']['posts_count']}), ranked by likes + 2*retweets + replies + quotes.", "",
         f"![Shared trends and relevance](overlap-{date}.png)", ""]
    if unsupported:
        L += ["## Locations skipped (WOEID not supported)", ""]
        for label, w, echo, n in unsupported:
            L.append(f"- **{label}** (WOEID {w}): API returned HTTP 200 with `woeid: {json.dumps(echo)}` and {n} trends; treated as unsupported (looks like a Worldwide fallback).")
        L.append("")
    L += ["## Global vs local", "",
          f"- Trends in 3+ of {len(locs)} locations: " + (", ".join(f"{display[n]} ({c})" for n, c in multi.items()) or "none"),
          f"- Trend volume field present on {vol_share:.0%} of {len(sup)} trend rows (schema: name, query, rank).", ""]
    for l in locs:
        same = [m for m in locs if m != l and sets[m] == sets[l]]
        ex = ", e.g. " + ", ".join(local_only[l][:6]) if local_only[l] else (f" (identical trend list to {', '.join(same)})" if same else "")
        L.append(f"- Only in **{l}**: {len(local_only[l])} of {len(sets[l])}{ex}")
    L.append("")
    for l in locs:
        L += [f"## {l}", "", "| Rank | Trend | Also trending in | Top post (engagement, age, lang) |", "|---|---|---|---|"]
        for _, tr in sup[sup.location == l].sort_values("rank").head(top_n).iterrows():
            others = sorted(set(sup[sup.name.map(norm) == norm(tr["name"])].location) - {l})
            ps = top3[top3.trend == tr["name"]] if len(top3) else top3
            cells = []
            for _, p in ps.iterrows():
                flag = "" if p.relevant else " (does not mention trend)"
                cells.append(f"[@{p.author}]({p.url}) {p.engagement:,} eng, {p.age_h}h, {p.lang}{flag}: {p.text[:90].replace('|', '/')}")
            L.append(f"| {tr['rank']} | {tr['name']} | {', '.join(others) or 'local'} | " + ("<br>".join(cells) or "no posts returned") + " |")
        L.append("")
    if len(top3):
        lang = top3.lang.value_counts()
        L += ["## Data quality checks", "",
              f"- Kept top posts: {len(top3)} across {top3.trend.nunique()} trends; searches with 0 posts: {sum(1 for s in raw['searches'].values() if not s.get('posts'))}.",
              f"- Relevance: {top3.relevant.mean():.0%} of kept posts mention the trend in text or hashtags (all fetched posts: {pdf.relevant.mean():.0%}).",
              f"- Freshness: median age of kept posts {top3.age_h.median():.1f} h; {(top3.age_h <= 24).mean():.0%} within 24 h; oldest {top3.age_h.max():.1f} h; posts older than 48 h among all fetched: {(pdf.age_h > 48).sum()}.",
              "- Language mix of kept posts (X `lang` codes; `qme` = media only, `und` = undetermined): " + ", ".join(f"{k} {v}" for k, v in lang.items()),
              f"- Duplicates: {len(dup_text)} repeated texts under different post ids; {len(multi_trend_ids)} post ids returned under 2+ trends; authors with 3+ fetched posts: "
              + (", ".join(f"@{a} ({n})" for a, n in heavy.head(8).items()) or "none"), ""]
    if raw.get("replies"):
        L += ["## Reply sample (#1 post per location, `GET /twitter/replies/post`)", ""]
        for l, r in raw["replies"].items():
            reps = r.get("replies") or []
            langs = collections.Counter(x.get("lang") for x in reps)
            direct = sum(1 for x in reps if x.get("in_reply_to_status_id") == r["post_id"] or x.get("conversation_id") == r["post_id"])
            L.append(f"- {l}: post {r['post_id']}: {len(reps)} replies returned, {direct} in the same conversation; langs " + ", ".join(f"{k} {v}" for k, v in langs.most_common()))
        L.append("")
    if len(cdf):
        L += ["## Cost and latency", "",
              f"- Calls: {len(cdf)}, errors: {(~cdf.ok).sum()}, total cost ${cdf.cost_usd.fillna(0).sum():.4f} (sum of `X-Desearch-Cost-Usd`).",
              f"- Latency: trends median {cdf[cdf.call.str.startswith('x_trends')].latency_s.median():.2f}s, search median {cdf[cdf.call.str.startswith('x_search')].latency_s.median():.2f}s, max {cdf.latency_s.max():.2f}s.", ""]
    L += [f"Files: trends-{date}.csv, posts-{date}.csv, overlap-{date}.png, costs-{date}.csv, raw-{date}.json"]
    open(f"{outdir}/snapshot-{date}.md", "w").write("\n".join(L) + "\n")
    print(f"wrote {outdir}/snapshot-{date}.md")
    return {"unsupported": unsupported, "multi": multi, "jac": jac}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--top", type=int, default=4, help="trends per location to search posts for")
    ap.add_argument("--posts", type=int, default=20, help="posts fetched per trend (top 3 by engagement kept)")
    ap.add_argument("--no-replies", action="store_true", help="skip the reply sample for each location's #1 post")
    ap.add_argument("--out", default="output")
    ap.add_argument("--from-raw", help="re-run analysis from a saved raw JSON (no API calls)")
    a = ap.parse_args()
    if a.from_raw:
        raw = json.load(open(a.from_raw))
        date = raw["fetched_at"][:10]
    else:
        t0 = time.time()
        raw = asyncio.run(collect(a.top, a.posts, not a.no_replies))
        date = raw["fetched_at"][:10]
        os.makedirs(a.out, exist_ok=True)
        json.dump(raw, open(f"{a.out}/raw-{date}.json", "w"), ensure_ascii=False, indent=1, default=str)
        print(f"collected in {time.time() - t0:.1f}s")
    analyze(raw, a.out, date)


if __name__ == "__main__":
    main()
