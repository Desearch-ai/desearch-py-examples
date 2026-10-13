#!/usr/bin/env python3
"""Listicle Gap Finder: your brand + competitor names + buyer queries -> the pages that rank for those
searches -> read each page -> which brands each page mentions -> a "gap" list of pages that name
2+ competitors but not you. Built on the Desearch API.

Made by Desearch (https://desearch.ai)

Usage:
    export DESEARCH_API_KEY=...        # your key from console.desearch.ai
    python listicle_gap.py --brand "YourBrand" --competitors "Rival A,Rival B,Rival C" \
        -q "best <category> tools 2026" -q "<rival> alternatives" ...
    python listicle_gap.py --brand ... --competitors ... --queries-file queries.txt --max-pages 40
    python listicle_gap.py --from-raw output/raw-2026-10-08-<slug>.json   # offline, no API calls, no cost

Endpoints:
    GET  /web?query=&start=                      ranked web results (title, link, snippet)
    POST /desearch/ai/search/links/web           {"prompt", "tools": ["web"], "count"}  second list of links
    GET  /web/extract?url=&format=text&js=false  page text, used to count brand mentions
"""
import argparse, concurrent.futures as cf, datetime as dt, json, os, re, sys, time
from urllib.parse import urlsplit, urlunsplit

import requests
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE = "https://api.desearch.ai"
TBILISI = dt.timezone(dt.timedelta(hours=4))
STOP = {"best", "top", "the", "for", "and", "a", "an", "of", "to", "in", "vs", "with", "2024", "2025", "2026",
        "alternatives", "alternative", "tools", "tool", "how", "what", "is", "are", "on", "your", "my"}
ROUNDUP = re.compile(r"\b(best|top \d*|top|alternatives?|vs\.?|versus|compar\w*|review\w*|ranked|tested)\b", re.I)


def now_tb():
    return dt.datetime.now(TBILISI)


class Client:
    def __init__(self, key):
        self.s = requests.Session()
        self.s.headers["Authorization"] = key
        self.costs = []

    def _log(self, kind, target, r, lat, items, attempt=1):
        cost = r.headers.get("X-Desearch-Cost-Usd") if r is not None else None
        uc = r.headers.get("X-Desearch-Usage-Count") if r is not None else None
        row = {"ts": now_tb().isoformat(timespec="seconds"), "kind": kind, "target": target, "attempt": attempt,
               "status": r.status_code if r is not None else "error", "latency_s": lat, "items": items,
               "usage_count": int(uc) if uc else None, "cost_usd": round(float(cost), 6) if cost else None}
        self.costs.append(row)
        print(f"  {kind:<8} {str(target)[:70]:<70} {row['status']} {lat:>5.2f}s items={items} cost={row['cost_usd']}", flush=True)

    def _search(self, kind, target, send, key):
        """One search call; a 5xx answer is retried once after 2 s. Every attempt is logged."""
        attempts = []
        for attempt in (1, 2):
            t0 = time.time()
            r = send()
            data = (r.json().get(key) or []) if r.ok else []
            self._log(kind, target, r, round(time.time() - t0, 2), len(data), attempt)
            attempts.append({"status": r.status_code, "error": None if r.ok else r.text[:300]})
            if r.status_code < 500:
                break
            time.sleep(2)
        return {"status": r.status_code, "results": data, "attempts": attempts}

    def web(self, query, start):
        return self._search("web", f"{query} [start={start}]",
                            lambda: self.s.get(f"{BASE}/web", params={"query": query, "start": start}, timeout=120), "data")

    def links(self, query, count):
        return self._search("links", f"{query} [count={count}]",
                            lambda: self.s.post(f"{BASE}/desearch/ai/search/links/web",
                                                json={"prompt": query, "tools": ["web"], "count": count}, timeout=180), "search_results")

    def extract(self, url, attempt):
        t0 = time.time()
        try:
            r = self.s.get(f"{BASE}/web/extract", params={"url": url, "format": "text", "js": "false"}, timeout=120)
        except requests.RequestException as e:
            self._log("extract", url, None, round(time.time() - t0, 2), 0, attempt)
            return {"status": "error", "error": str(e)[:200], "text": "", "attempt": attempt}
        text = r.text if r.ok else ""
        self._log("extract", url, r, round(time.time() - t0, 2), len(text.strip()), attempt)
        return {"status": r.status_code, "text": text, "attempt": attempt, "error": None if r.ok else r.text[:200]}


def norm_url(u):
    p = urlsplit(u.strip())
    host = p.netloc.lower().removeprefix("www.")
    path = p.path.rstrip("/") or "/"
    return urlunsplit(("https", host, path, p.query, ""))


def domain(u):
    return urlsplit(u).netloc.lower().removeprefix("www.")


def brand_regex(name):
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])", re.I)


def topic_words(queries, brands):
    bl = {w.lower() for b in brands for w in re.findall(r"[A-Za-z0-9]+", b)}
    words = set()
    for q in queries:
        for w in re.findall(r"[A-Za-z0-9]+", q.lower()):
            if w not in STOP and w not in bl and len(w) > 2:
                words.add(w)
    return sorted(words)


def collect(client, queries, starts, links_count):
    serp, links = {}, {}
    for q in queries:
        serp[q] = {str(s): client.web(q, s) for s in starts}
        if links_count:
            links[q] = client.links(q, links_count)
    return serp, links


def candidates(raw):
    """Merge SERP and links-only results into one row per page."""
    pages = {}
    for q, by_start in raw["serp"].items():
        for s, resp in by_start.items():
            for i, it in enumerate(resp["results"]):
                k = norm_url(it["link"])
                p = pages.setdefault(k, {"url": it["link"], "title": it.get("title", ""), "snippet": it.get("snippet", ""),
                                         "queries": set(), "serp_hits": 0, "links_hits": 0, "best_rank": None})
                p["queries"].add(q); p["serp_hits"] += 1
                rank = int(s) + i + 1
                p["best_rank"] = rank if p["best_rank"] is None else min(p["best_rank"], rank)
    for q, resp in raw["links"].items():
        for it in resp["results"]:
            k = norm_url(it["link"])
            p = pages.setdefault(k, {"url": it["link"], "title": it.get("title", ""), "snippet": it.get("snippet", ""),
                                     "queries": set(), "serp_hits": 0, "links_hits": 0, "best_rank": None})
            p["queries"].add(q); p["links_hits"] += 1
    return pages


def on_topic(text, words):
    t = text.lower()
    return any(w in t for w in words)


def pick(pages, words, max_pages):
    rows = []
    for k, p in pages.items():
        blob = f"{p['title']} {p['snippet']} {p['url']}"
        rows.append((k, p, on_topic(blob, words), bool(ROUNDUP.search(p["title"]))))
    # on-topic roundup-looking pages first, then pages found by more queries, then better rank
    rows.sort(key=lambda r: (not r[2], not r[3], -len(r[1]["queries"]), r[1]["best_rank"] or 999))
    return [r[0] for r in rows[:max_pages]]


def read_pages(client, pages, keys, workers=3):
    out = {}

    def one(k):
        tries = [client.extract(pages[k]["url"], 1)]
        if not tries[0]["text"].strip() and tries[0]["status"] not in (400, 401, 402, 422):
            time.sleep(1)
            tries.append(client.extract(pages[k]["url"], 2))  # no text (empty 200 or 404 "No content found"): retry once, keep both attempts
        return k, tries

    with cf.ThreadPoolExecutor(workers) as ex:
        for k, tries in ex.map(one, keys):
            out[k] = tries
    return out


def page_text(tries):
    return next((t["text"] for t in reversed(tries) if t.get("text", "").strip()), "")


def slim(raw, redact):
    """Copy of raw for saving: brand counts per page instead of full page text, and the --redact words
    replaced in titles, snippets and error strings. analyse() gives the same result on the full or slim copy."""
    regs = {b: brand_regex(b) for b in [raw["brand"]] + raw["competitors"]}
    rx = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(re.escape(w) for w in redact) + r")(?![A-Za-z0-9])", re.I) if redact else None
    def fix(v):
        if rx and isinstance(v, str):
            return rx.sub("[redacted]", v)
        if rx and isinstance(v, list):
            return [fix(x) for x in v]
        return v
    out = json.loads(json.dumps(raw))
    for by in out["serp"].values():
        for resp in by.values():
            resp["results"] = [{**it, "title": fix(it.get("title", "")), "snippet": fix(it.get("snippet", ""))} for it in resp["results"]]
            for a in resp.get("attempts", []): a["error"] = fix(a.get("error"))
    for resp in out["links"].values():
        resp["results"] = [{k: fix(v) if k in ("title", "snippet", "highlights", "author") else v for k, v in it.items()} for it in resp["results"]]
        for a in resp.get("attempts", []): a["error"] = fix(a.get("error"))
    out["mentions"] = {}
    for k, tries in out["extracts"].items():
        text = page_text(tries)
        out["mentions"][k] = {b: len(r.findall(text)) for b, r in regs.items()} if text else None
        for t in tries:
            t["chars"] = len(t.pop("text", "").strip())
            t["error"] = fix(t.get("error"))
    out["page_text"] = "not saved (brand counts per page are in 'mentions')"
    return out


def analyse(raw):
    brand, comps = raw["brand"], raw["competitors"]
    words = raw["topic_words"]
    pages = candidates(raw)
    regs = {b: brand_regex(b) for b in [brand] + comps}
    own_tokens = {b: re.sub(r"[^a-z0-9]", "", b.lower()) for b in [brand] + comps}
    saved = raw.get("mentions")
    rows, ext_rows = [], []
    for k, p in pages.items():
        tries = raw["extracts"].get(k)
        text, counts, chars = "", None, None
        if tries:
            for t in tries:
                c = t["chars"] if "chars" in t else len(t["text"].strip())
                ext_rows.append({"url": p["url"], "attempt": t["attempt"], "status": t["status"], "chars": c,
                                 "empty_200": t["status"] == 200 and c == 0})
            if saved is not None:
                counts = saved.get(k)
                chars = max((t["chars"] for t in tries), default=0) if counts else 0
            else:
                text = page_text(tries)
                counts = {b: len(regs[b].findall(text)) for b in regs} if text else None
                chars = len(text.strip())
        has_text = counts is not None
        if not has_text:
            counts = {b: None for b in regs}
        text = has_text
        d = domain(p["url"])
        owner = next((b for b, tok in own_tokens.items() if tok and tok in d.replace("-", "").replace(".", "")), "")
        comp_named = [c for c in comps if counts[c]] if text else []
        row = {"url": p["url"], "domain": d, "title": p["title"], "queries": " | ".join(sorted(p["queries"])),
               "n_queries": len(p["queries"]), "best_serp_rank": p["best_rank"], "in_serp": p["serp_hits"] > 0,
               "in_links": p["links_hits"] > 0, "on_topic_by_title": on_topic(f"{p['title']} {p['snippet']} {p['url']}", words),
               "roundup_title": bool(ROUNDUP.search(p["title"])), "owned_by": owner, "read": bool(tries),
               "text_chars": chars if tries else None}
        for b in regs:
            row[f"m_{b}"] = counts[b]
        row["competitors_named"] = len(comp_named) if text else None
        row["brand_named"] = (counts[brand] or 0) > 0 if text else None
        row["gap"] = bool(text) and len(comp_named) >= 2 and not counts[brand] and owner == ""
        rows.append(row)
    df = pd.DataFrame(rows).sort_values(["gap", "competitors_named", "n_queries"], ascending=[False, False, False], na_position="last")
    return df, pd.DataFrame(ext_rows)


def topic_stats(raw):
    words = raw["topic_words"]
    out = {}
    for src in ("serp", "links"):
        tot = off = 0
        items = []
        if src == "serp":
            for q, by in raw["serp"].items():
                for s, resp in by.items():
                    items += resp["results"]
        else:
            for q, resp in raw["links"].items():
                items += resp["results"]
        for it in items:
            tot += 1
            off += not on_topic(f"{it.get('title','')} {it.get('snippet','')} {it.get('link','')}", words)
        out[src] = {"results": tot, "off_topic_by_keyword": off}
    return out


def write(raw, df, ext, costs, outdir):
    os.makedirs(outdir, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", raw["brand"].lower()).strip("-")
    fetched = dt.datetime.fromisoformat(raw["fetched_at"]).astimezone(TBILISI)
    base = f"{outdir}/{fetched.date()}-{slug}"
    df.to_csv(f"{base}-pages.csv", index=False)
    if len(ext):
        ext.to_csv(f"{base}-extract-log.csv", index=False)
    if costs:
        pd.DataFrame(costs).to_csv(f"{base}-costs.csv", index=False)
    read = df[df.read]
    gaps = df[df.gap]
    brand, comps = raw["brand"], raw["competitors"]
    ts = topic_stats(raw)
    lines = [f"# Listicle Gap Finder: {brand} ({fetched:%Y-%m-%d})", "",
             f"Made by [Desearch](https://desearch.ai). Data fetched {fetched:%Y-%m-%d %H:%M} Asia/Tbilisi.", "",
             f"- Queries: {len(raw['queries'])} ({'; '.join(raw['queries'])})",
             f"- Competitors tracked: {', '.join(comps)}",
             f"- Unique pages found: {len(df)} (ranked results: {ts['serp']['results']}, links-only results: {ts['links']['results']})",
             f"- Pages read: {len(read)}; pages with text: {int((read.text_chars > 0).sum())}",
             f"- Pages naming {brand}: {int(read.brand_named.fillna(False).astype(bool).sum())}",
             f"- Gap pages (2+ competitors named, {brand} not named, not a competitor's own site): {len(gaps)}", ""]
    if len(read):
        mention = {b: int((read[f"m_{b}"].fillna(0) > 0).sum()) for b in [brand] + comps}
        lines += ["## Pages naming each brand (of pages read with text)", "", "| brand | pages |", "|---|---|"]
        lines += [f"| {b} | {n} |" for b, n in mention.items()] + [""]
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.barh(list(mention.keys())[::-1], list(mention.values())[::-1], color=["#888"] * len(comps) + ["#2a7"])
        ax.set_xlabel("pages that name the brand"); ax.set_title(f"Brand mentions across {int((read.text_chars > 0).sum())} pages")
        fig.tight_layout(); fig.savefig(f"{base}-mentions.png", dpi=120)
    lines += ["## Outreach list (gap pages)", ""]
    if len(gaps):
        cols = ["title", "url", "competitors_named", "n_queries", "best_serp_rank"]
        lines += [gaps[cols].to_markdown(index=False), ""]
    else:
        lines += ["No gap pages in this run.", ""]
    if costs:
        c = pd.DataFrame(costs)
        lines += ["## Cost", "", f"{len(c)} calls, ${c.cost_usd.fillna(0).sum():.4f} (sum of X-Desearch-Cost-Usd headers). "
                  + ", ".join(f"{k}: {len(g)} calls ${g.cost_usd.fillna(0).sum():.4f}" for k, g in c.groupby("kind")), ""]
    open(f"{base}-gaps.md", "w").write("\n".join(lines))
    print(f"wrote {base}-gaps.md / -pages.csv / -extract-log.csv / -costs.csv / -mentions.png")


def main():
    ap = argparse.ArgumentParser(description="Find pages that rank for your buyer searches and name competitors but not you.")
    ap.add_argument("--brand")
    ap.add_argument("--competitors", help="comma separated")
    ap.add_argument("-q", "--query", action="append", default=[])
    ap.add_argument("--queries-file")
    ap.add_argument("--start", default="0", help="comma separated GET /web start values, e.g. 0,20 (each call returned 20 results in testing)")
    ap.add_argument("--links-count", type=int, default=10, help="links-only results per query (10-200; 0 = skip)")
    ap.add_argument("--max-pages", type=int, default=40, help="pages to read with Extract")
    ap.add_argument("--out", default="output")
    ap.add_argument("--redact", default="", help="comma separated words to replace with [redacted] in saved files (titles, snippets)")
    ap.add_argument("--full-raw", help="also save the unredacted raw file with full page text to this path")
    ap.add_argument("--from-raw")
    a = ap.parse_args()
    costs = []
    if a.from_raw:
        raw = json.load(open(a.from_raw))
    else:
        queries = a.query + ([l.strip() for l in open(a.queries_file) if l.strip()] if a.queries_file else [])
        if not a.brand or not a.competitors or not queries:
            ap.error("give --brand, --competitors and at least one query")
        if a.links_count and not 10 <= a.links_count <= 200:
            ap.error("--links-count must be 0 or 10..200")
        key = os.environ.get("DESEARCH_API_KEY") or sys.exit("Set DESEARCH_API_KEY (create a key at console.desearch.ai).")
        client = Client(key)
        comps = [c.strip() for c in a.competitors.split(",") if c.strip()]
        starts = [int(s) for s in a.start.split(",")]
        raw = {"fetched_at": now_tb().isoformat(timespec="seconds"), "brand": a.brand, "competitors": comps,
               "queries": queries, "starts": starts, "links_count": a.links_count, "max_pages": a.max_pages,
               "topic_words": topic_words(queries, [a.brand] + comps)}
        print("topic words for the on-topic check:", ", ".join(raw["topic_words"]))
        raw["serp"], raw["links"] = collect(client, queries, starts, a.links_count)
        pages = candidates(raw)
        keys = pick(pages, raw["topic_words"], a.max_pages)
        print(f"{len(pages)} unique pages, reading {len(keys)}")
        raw["extracts"] = read_pages(client, pages, keys)
        raw["costs"] = costs = client.costs
        if a.full_raw:
            json.dump(raw, open(a.full_raw, "w")); print("full raw saved:", a.full_raw)
        raw = slim(raw, [w.strip() for w in a.redact.split(",") if w.strip()])
        os.makedirs(a.out, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", a.brand.lower()).strip("-")
        path = f"{a.out}/raw-{now_tb().date()}-{slug}.json"
        json.dump(raw, open(path, "w")); print("raw saved:", path)
    df, ext = analyse(raw)
    write(raw, df, ext, costs or raw.get("costs", []), a.out)


if __name__ == "__main__":
    main()
