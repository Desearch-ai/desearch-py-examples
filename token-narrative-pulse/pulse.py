#!/usr/bin/env python3
"""Token Narrative Pulse: a daily X + Reddit chatter report for a token watchlist, built on the Desearch API.

Made by Desearch (https://desearch.ai)

Usage:
    export DESEARCH_API_KEY=...        # your key from console.desearch.ai
    python pulse.py                    # default watchlist
    python pulse.py --count 20 --out output
"""
import argparse, asyncio, collections, datetime as dt, json, os, re, sys, time
from email.utils import parsedate_to_datetime

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from desearch_py import Desearch

# token label -> (X search query, regex used to tag a post as mentioning that token)
WATCHLIST = {
    "TAO": ("$TAO", r"\$tao\b"),
    "Bittensor": ("Bittensor", r"bittensor"),
    "Desearch (SN22)": ("Desearch", r"desearch|\bsn22\b|subnet 22"),
    "Chutes (SN64)": ("Chutes SN64", r"chutes|\bsn64\b|subnet 64"),
}
SYSTEM_MESSAGE = (
    "You are a crypto market analyst. Using only the provided sources, answer in three sections "
    "titled Bullish, Bearish and Neutral. Every bullet must cite the source link it came from. "
    "If a source looks older than 24 hours, say so."
)
URL_RE = re.compile(r"https?://[^\s\)\]]+")


def parse_ts(s):
    """X returns legacy 'Sat Oct 03 08:00:00 +0000 2026' on GET /twitter and ISO on AI Search."""
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        return dt.datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y")
    except ValueError:
        try:
            return parsedate_to_datetime(s)
        except Exception:
            return None


def dump(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, list):
        return [dump(x) for x in obj]
    return obj


async def timed(costs, label, coro):
    t0 = time.time()
    err = None
    res = None
    try:
        res = await coro
    except Exception as e:  # never print repr(e): aiohttp's repr includes request headers (the API key)
        err = f"{type(e).__name__}: status={getattr(e, 'status', '?')} message={getattr(e, 'message', str(e))[:200]}"
    latency = round(time.time() - t0, 2)
    meta = getattr(res, "metadata", None)
    costs.append({
        "call": label, "latency_s": latency, "ok": err is None,
        "cost_usd": round(meta.cost_usd, 6) if meta and meta.cost_usd is not None else None,
        "usage_count": meta.usage_count if meta else None,
        "service": meta.service if meta else None, "error": err,
    })
    print(f"  {label:<45} {latency:>6.2f}s  cost={costs[-1]['cost_usd']}  {err or ''}", flush=True)
    return res.data if res is not None else None


async def collect(count, outdir, raw_dir):
    now = dt.datetime.now(dt.timezone.utc)
    since = now - dt.timedelta(hours=24)
    start_date = since.strftime("%Y-%m-%d")  # GET /twitter takes a UTC day, not a timestamp
    costs, x_raw, ai_raw = [], {}, {}
    async with Desearch(api_key=os.environ["DESEARCH_API_KEY"]) as ds:
        print("X search (GET /twitter via desearch-py x_search):")
        for label, (query, _) in WATCHLIST.items():
            for sort in ("Top", "Latest"):
                data = await timed(costs, f"x_search {query!r} sort={sort}",
                                   ds.x_search(query=query, sort=sort, count=count,
                                               start_date=start_date, include_metadata=True))
                x_raw[f"{label}|{sort}"] = dump(data) or []
        print("AI Search (POST /desearch/ai/search via desearch-py ai_search):")
        terms = " OR ".join(q for q, _ in WATCHLIST.values())
        for tools in (["reddit"], ["twitter", "reddit"]):
            data = await timed(costs, f"ai_search tools={tools}",
                               ds.ai_search(prompt=f"What are people saying in the last 24 hours about {terms}?",
                                            tools=tools, date_filter="PAST_24_HOURS",
                                            result_type="LINKS_WITH_FINAL_SUMMARY",
                                            system_message=SYSTEM_MESSAGE, count=10,
                                            include_metadata=True))
            ai_raw["+".join(tools)] = dump(data) or {}
    json.dump({"generated_utc": now.isoformat(), "x": x_raw, "ai": ai_raw, "costs": costs},
              open(os.path.join(raw_dir, f"raw-{now:%Y-%m-%d}.json"), "w"), indent=1, default=str)
    return now, since, x_raw, ai_raw, costs


def analyse(now, since, x_raw, ai_raw, costs, outdir):
    day = dt.datetime.now().strftime("%Y-%m-%d")
    rows, seen = [], {}
    for key, items in x_raw.items():
        label, sort = key.split("|")
        for t in items:
            tid = str(t.get("id"))
            if tid in seen:
                seen[tid]["found_by"] += f";{key}"
                continue
            u = t.get("user") or {}
            ts = parse_ts(t.get("created_at"))
            r = {
                "id": tid, "url": t.get("url"), "created_utc": ts.isoformat() if ts else None,
                "author": u.get("username"), "followers": u.get("followers_count"),
                "author_created": u.get("created_at"), "lang": t.get("lang"),
                "likes": t.get("like_count"), "retweets": t.get("retweet_count"),
                "replies": t.get("reply_count"), "quotes": t.get("quote_count"),
                "views": t.get("view_count"), "bookmarks": t.get("bookmark_count"),
                "is_retweet": t.get("is_retweet"), "text": (t.get("text") or "").replace("\r", " "),
                "found_by": key, "_ts": ts,
            }
            seen[tid] = r
            rows.append(r)
    df = pd.DataFrame(rows)
    total_returned = sum(len(v) for v in x_raw.values())
    eng_cols = ["likes", "retweets", "replies", "quotes"]
    for c in eng_cols + ["views", "bookmarks", "followers"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    missing_eng = int(df[eng_cols].isna().any(axis=1).sum())
    df["engagement"] = df["likes"].fillna(0) + 2 * df["retweets"].fillna(0) + df["replies"].fillna(0) + df["quotes"].fillna(0)
    df["in_window"] = df["_ts"].apply(lambda x: bool(x and x >= since))
    out_of_window = df[~df["in_window"]]
    d = df[df["in_window"]].copy()
    for label, (_, rx) in WATCHLIST.items():
        d[label] = d["text"].str.contains(rx, case=False, regex=True)
    mentions = {label: int(d[label].sum()) for label in WATCHLIST}
    authors = {label: int(d.loc[d[label], "author"].nunique()) for label in WATCHLIST}
    # spam / dedup heuristics
    d["norm"] = d["text"].str.lower().str.replace(URL_RE, "", regex=True).str.replace(r"[^a-z0-9$ ]", "", regex=True).str.split().str.join(" ")
    dup_groups = d[d.duplicated("norm", keep=False) & (d["norm"].str.len() > 20)].groupby("norm")
    per_author = d["author"].value_counts()
    heavy = per_author[per_author >= 3]
    d["cashtags"] = d["text"].str.count(r"\$[A-Za-z]{2,10}\b")
    cashtag_spam = d[d["cashtags"] >= 5]
    low_follower = d[(d["followers"] < 50) & (d["engagement"] == 0)]
    # template bots: different authors, same closing 30 characters (e.g. an identical cashtag list)
    d["tail"] = d["text"].str.replace(URL_RE, "", regex=True).str.strip().str[-30:]
    tails = d[d["tail"].str.len() >= 20].groupby("tail")["author"].nunique()
    template_tails = tails[tails >= 2].index
    templ = d[d["tail"].isin(template_tails)]
    d["spam_flag"] = (d["norm"].isin(dup_groups.groups.keys()) | d["author"].isin(heavy.index)
                      | (d["cashtags"] >= 5) | d["tail"].isin(template_tails))
    top5 = d.sort_values("engagement", ascending=False).head(5)
    lang_mix = d["lang"].fillna("unknown").value_counts()
    d["hour"] = d["_ts"].apply(lambda x: x.replace(minute=0, second=0, microsecond=0))

    # CSV
    csv_path = os.path.join(outdir, f"posts-{day}.csv")
    d.drop(columns=["_ts", "norm", "hour", "tail"]).to_csv(csv_path, index=False)

    # chart
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 4.5))
    a1.bar(list(mentions), list(mentions.values()), color="#2b4fd8")
    a1.set_title("Mentions per token (X, last 24h, deduped)")
    a1.tick_params(axis="x", rotation=15)
    hours = pd.date_range(since.replace(minute=0, second=0, microsecond=0), now, freq="h")
    for label in WATCHLIST:
        s = d[d[label]].groupby("hour").size().reindex(hours, fill_value=0)
        a2.plot(s.index, s.values, marker=".", label=label)
    a2.set_title("Mentions per hour (UTC), sample-based")
    a2.legend(fontsize=8)
    fig.autofmt_xdate()
    fig.tight_layout()
    png_path = os.path.join(outdir, f"mentions-{day}.png")
    fig.savefig(png_path, dpi=110)

    # AI search checks: are cited links among the returned sources? do sources carry dates?
    ai_sections = []
    for key, data in ai_raw.items():
        comp = data.get("completion") or ""
        src_links = set()
        for k, v in data.items():
            if isinstance(v, list):
                for it in v:
                    if isinstance(it, dict):
                        for f in ("link", "url"):
                            if it.get(f):
                                src_links.add(it[f].rstrip("/"))
        cited = sorted(set(l.rstrip("/").rstrip(".,") for l in URL_RE.findall(comp)))
        unmatched = [c for c in cited if c not in src_links]
        reddit = data.get("reddit_search") or data.get("search") or []
        dated = sum(1 for it in reddit if any(k in it for k in ("created_at", "published_date", "date")))
        has_sections = all(s.lower() in comp.lower() for s in ("bullish", "bearish", "neutral"))
        tweets_ai = data.get("tweets") or []
        tw_out = sum(1 for t in tweets_ai if (parse_ts(t.get("created_at")) or now) < since)
        ai_sections.append((key, comp, reddit, cited, unmatched, dated, has_sections, len(tweets_ai), tw_out))

    spend = sum(c["cost_usd"] or 0 for c in costs)
    L = []
    L.append(f"# Token Narrative Pulse, {day}\n")
    L.append("Made by Desearch ([desearch.ai](https://desearch.ai))\n")
    L.append(f"Window: {since:%Y-%m-%d %H:%M} to {now:%Y-%m-%d %H:%M} UTC. Source: Desearch API (X search + AI Search with Reddit).\n")
    L.append("## Mentions (X, deduplicated, inside the 24h window)\n")
    L.append("| Token | Mentions | Unique authors |\n|---|---|---|")
    for label in WATCHLIST:
        L.append(f"| {label} | {mentions[label]} | {authors[label]} |")
    L.append(f"\nPosts returned: {total_returned}; unique: {len(df)}; inside window: {len(d)}; outside window (dropped): {len(out_of_window)}; posts missing an engagement field: {missing_eng}.\n")
    L.append(f"![mentions](mentions-{day}.png)\n")
    L.append("These are counts inside a sample (Top + Latest, `--count` posts per query), not total X volume. "
             "Latest returns the newest posts, so the last hours look busier in the hourly chart.\n")
    L.append("## Top 5 posts by engagement\n")
    L.append("Engagement = likes + 2 x reposts + replies + quotes.\n")
    L.append("| # | Author | Likes | Reposts | Replies | Views | Posted (UTC) | Post |\n|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(top5.itertuples(), 1):
        txt = re.sub(r"\s+", " ", r.text)[:110].replace("|", "/")
        L.append(f"| {i} | @{r.author} | {int(r.likes or 0)} | {int(r.retweets or 0)} | {int(r.replies or 0)} | {int(r.views) if pd.notna(r.views) else '-'} | {r._asdict()['created_utc'][:16]} | [{txt}]({r.url}) |")
    L.append("\n## Spam and duplicate check\n")
    L.append(f"- Identical-text groups (after stripping links/punctuation): {dup_groups.ngroups}")
    for norm, g in list(dup_groups)[:5]:
        L.append(f"  - {len(g)} posts by {', '.join('@' + a for a in g['author'].unique()[:5])}: \"{norm[:80]}\"")
    L.append(f"- Authors with 3+ posts in the sample: {', '.join(f'@{a} ({n})' for a, n in heavy.items()) or 'none'}")
    L.append(f"- Template groups (2+ authors, same closing text): {len(template_tails)} groups, {len(templ)} posts")
    for tail in list(template_tails)[:5]:
        g = templ[templ["tail"] == tail]
        L.append(f"  - {len(g)} posts by {', '.join('@' + a for a in g['author'].unique()[:6])}: \"...{tail.strip()}\"")
    L.append(f"- Cashtag-stuffed posts (5+ cashtags): {len(cashtag_spam)}")
    L.append(f"- Zero-engagement posts from accounts under 50 followers: {len(low_follower)}")
    L.append(f"- Posts flagged by any rule: {int(d['spam_flag'].sum())} of {len(d)}\n")
    L.append("## Language mix\n")
    L.append(", ".join(f"{k}: {v}" for k, v in lang_mix.items()) + "\n")
    L.append("## AI Search narrative (bull / bear / neutral)\n")
    L.append("> Note: Reddit links come back without a post date, and in testing many were older than the requested 24h window. "
             "Treat Reddit points as background unless you confirm the thread date yourself.\n")
    for key, comp, reddit, cited, unmatched, dated, has_sections, n_tw, tw_out in ai_sections:
        L.append(f"### tools = {key}\n")
        L.append((comp.strip() or "_(no completion returned)_") + "\n")
        L.append(f"Checks: {len(reddit)} Reddit links returned, {dated} of them carry a date field; "
                 f"{n_tw} X posts returned, {tw_out} older than 24h; {len(cited)} links cited in the summary, "
                 f"{len(unmatched)} not found among returned sources; bull/bear/neutral sections present: {has_sections}.\n")
        if reddit:
            L.append("Reddit sources returned:\n")
            for it in reddit[:10]:
                L.append(f"- [{(it.get('title') or '').strip()[:90]}]({it.get('link')})")
            L.append("")
    L.append("## Cost and latency per call\n")
    L.append("| Call | Latency (s) | Cost (USD, X-Desearch-Cost-Usd) | Usage units | Error |\n|---|---|---|---|---|")
    for c in costs:
        L.append(f"| {c['call']} | {c['latency_s']} | {c['cost_usd']} | {c['usage_count']} | {c['error'] or ''} |")
    L.append(f"\n**Total spend this run: ${spend:.4f}**\n")
    rep_path = os.path.join(outdir, f"report-{day}.md")
    open(rep_path, "w").write("\n".join(L))
    pd.DataFrame(costs).to_csv(os.path.join(outdir, f"costs-{day}.csv"), index=False)
    print(f"\nWrote {rep_path}\n      {csv_path}\n      {png_path}\nTotal spend: ${spend:.4f}")
    return spend


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, default=20, help="posts per X query (default 20)")
    ap.add_argument("--out", default="output", help="output folder (default ./output)")
    ap.add_argument("--from-raw", help="re-analyse a saved raw-YYYY-MM-DD.json without calling the API")
    a = ap.parse_args()
    if a.from_raw:
        r = json.load(open(a.from_raw))
        now = dt.datetime.fromisoformat(r["generated_utc"])
        os.makedirs(a.out, exist_ok=True)
        analyse(now, now - dt.timedelta(hours=24), r["x"], r["ai"], r.get("costs", []), a.out)
        return
    if not os.environ.get("DESEARCH_API_KEY"):
        sys.exit("Set DESEARCH_API_KEY (get one at https://console.desearch.ai)")
    os.makedirs(a.out, exist_ok=True)
    now, since, x_raw, ai_raw, costs = asyncio.run(collect(a.count, a.out, a.out))
    analyse(now, since, x_raw, ai_raw, costs, a.out)


if __name__ == "__main__":
    main()
