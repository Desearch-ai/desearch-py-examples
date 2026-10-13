"""Arxiv Chatter Digest (Made by Desearch, https://desearch.ai).

topic -> Desearch MCP ai-search (tools ["arxiv"] only) -> arXiv ids -> public arXiv API check (id, title, date)
-> Extract abs page (js false, one retry) -> X search per paper with a parenthesised OR -> papers.csv + digest.md.
"""
import argparse, asyncio, datetime as dt, json, os, pathlib, sys, time, urllib.error, urllib.request
import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
import core

MCP_URL = os.environ.get("DESEARCH_MCP_URL", "https://mcp.desearch.ai/mcp")
ARXIV_API = "https://export.arxiv.org/api/query"
# Different wordings of one ask. The month and year words and the arXiv id prefix (YYMM) pull in newer papers;
# the date window sent with the call did not narrow results in our runs (see report.md).
PROMPTS = ["recent papers on {topic}",
           "{topic} arXiv papers submitted {m1} or {m2} {y}",
           "new {topic} preprints {m2} {y}",
           "arXiv {p2} {topic}",
           "arXiv {p1} {topic}",
           "{topic} new method arXiv {m1} {y}",
           "{topic} benchmark or dataset paper {m2} {y}",
           "{topic} theory paper arXiv {m1} {y}"]


def api_key():
    path = os.environ.get("DESEARCH_API_KEY_FILE")
    key = pathlib.Path(path).read_text().strip() if path else os.environ.get("DESEARCH_API_KEY", "").strip()
    if not key:
        raise SystemExit("Set DESEARCH_API_KEY_FILE (a file holding your key from console.desearch.ai) or DESEARCH_API_KEY")
    return key


class Client:
    """Logs every MCP call (args, latency, status, items, cost) to calls.jsonl and saves the raw result."""

    def __init__(self, session, out, key, sem=4):
        self.s, self.out, self.key, self.calls, self.sem = session, out, key, [], asyncio.Semaphore(sem)

    async def call(self, tool, args, tag):
        async with self.sem:
            ts = dt.datetime.now().astimezone().isoformat(timespec="seconds")
            t0 = time.perf_counter()
            try:
                res = await self.s.call_tool(tool, args)
                err, body = bool(getattr(res, "is_error", False)), res.model_dump(mode="json")
            except Exception as e:  # transport error: log and carry on
                err, body, res = True, {"exception": repr(e)}, None
            lat = round(time.perf_counter() - t0, 2)
        texts = [c.get("text", "") for c in body.get("content", []) or [] if c.get("type") == "text"]
        raw = "\n".join(texts)
        try:
            data = json.loads(raw)
        except ValueError:
            data = raw
        cost = data.get("cost_usd") if isinstance(data, dict) else None
        rec = {"ts": ts, "n": len(self.calls) + 1, "tag": tag, "tool": tool, "args": args, "latency_s": lat, "is_error": err,
               "items": len(data) if isinstance(data, list) else len(data.get("search", [])) if isinstance(data, dict) else int(bool(raw.strip())),
               "cost_usd": cost, "usage_count": data.get("usage_count") if isinstance(data, dict) else None}
        if tool == "x-search" and not err and cost is None:
            rec["cost_calculated_usd"] = core.x_cost_calculated(rec["items"], args.get("count", 20))
        self.calls.append(rec)
        rawdir = self.out / "raw"
        rawdir.mkdir(parents=True, exist_ok=True)
        (rawdir / f"{rec['n']:03d}-{tag}.json").write_text(core.assert_no_key(json.dumps({**rec, "result": body}, indent=1, ensure_ascii=False), self.key))
        with (self.out / "calls.jsonl").open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return (None if err else data), rec


def arxiv_metadata(ids):
    url = ARXIV_API + "?id_list=" + ",".join(ids) + f"&max_results={len(ids)}"
    req = urllib.request.Request(url, headers={"User-Agent": "arxiv-chatter-digest/0.1"})
    for wait in (5, 20, 60, None):  # the public arXiv API answers 429 when called too often
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                xml = r.read().decode()
            return xml, core.parse_arxiv_atom(xml)
        except urllib.error.HTTPError as e:
            if e.code != 429 or wait is None:
                raise
            print(f"arXiv API 429, retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)


async def run(a):
    key = api_key()
    today = dt.date.today()
    start = today - dt.timedelta(days=a.days)
    window = (start.isoformat(), today.isoformat())
    slug = "-".join(core.norm_title(a.topic).split())[:40]
    out = pathlib.Path(a.out) / f"{dt.datetime.now():%Y%m%d-%H%M%S}-{slug}"
    out.mkdir(parents=True, exist_ok=True)
    fetched = dt.datetime.now().astimezone().isoformat(timespec="minutes")
    months = [(today.replace(day=1) - dt.timedelta(days=1)).strftime("%B"), today.strftime("%B")]
    prev = today.replace(day=1) - dt.timedelta(days=1)
    prompts = [p.format(topic=a.topic, m1=months[0], m2=months[1], y=today.year, p1=prev.strftime("%y%m"), p2=today.strftime("%y%m")) for p in PROMPTS[:a.prompts]]
    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {key}"}, timeout=httpx2.Timeout(30, read=240)) as http:
        async with streamable_http_client(MCP_URL, http_client=http) as (r, w, *_):
            async with ClientSession(r, w) as s:
                await s.initialize()
                c = Client(s, out, key)
                # 1. arXiv papers through ai-search, arxiv only (never mixed with web or wikipedia)
                found = await asyncio.gather(*[c.call("ai-search", {
                    "prompt": p, "tools": ["arxiv"], "result_type": "ONLY_LINKS",
                    "start_date": f"{window[0]}T00:00:00Z", "end_date": f"{window[1]}T23:59:59Z"}, f"arxiv-{i}")
                    for i, p in enumerate(prompts, 1)])
                results = [(p, (d or {}).get("search", []) if isinstance(d, dict) else []) for p, (d, _) in zip(prompts, found)]
                cands, skipped = core.collect_papers(results)
                # 2. check ids and titles against the public arXiv API (free, not Desearch)
                meta = {}
                if cands:
                    xml, meta = arxiv_metadata(list(cands))
                    (out / "arxiv-api.xml").write_text(xml)
                papers = []
                for pid, p in cands.items():
                    m = meta.get(pid)
                    pub = m["published"] if m else ""
                    papers.append({**p, "resolves": bool(m), "title": m["title"] if m else p["desearch_title"],
                                   "abs_url": f"https://arxiv.org/abs/{pid}", "published": pub,
                                   "authors": m["authors"] if m else [], "api_summary": m["summary"] if m else "",
                                   "title_match": core.title_similarity(p["desearch_title"], m["title"]) if m else None,
                                   "in_window": bool(pub) and window[0] <= pub <= window[1]})
                pool = [p for p in papers if p["resolves"] and (p["in_window"] or a.include_older)]
                pool.sort(key=lambda p: p["published"], reverse=True)
                chosen = pool[:a.max_papers]

                # 3. abs page text with Extract (js false), one retry when empty
                async def extract(p):
                    p["extract_status"], p["abstract"] = "empty", ""
                    for attempt in (1, 2):
                        d, rec = await c.call("extract", {"url": p["abs_url"], "format": "text", "js": False}, f"extract-{p['arxiv_id']}-try{attempt}")
                        txt = core.page_text(d)
                        if txt:
                            p["extract_status"] = f"ok_try{attempt}"
                            p["abstract"] = core.abstract_from_page(txt)
                            return
                    p["abstract"] = ""

                # 4. X posts that name the paper: ("<id>" OR "<short title>") from the paper's date
                async def xsearch(p):
                    xs = max(p["published"] or window[0], window[0]) if not a.include_older else (p["published"] or window[0])
                    q = core.x_query(p["arxiv_id"], p["title"])
                    d, rec = await c.call("x-search", {"query": q, "count": a.posts, "start_date": xs,
                                                       "end_date": (today + dt.timedelta(days=1)).isoformat()}, f"x-{p['arxiv_id']}")
                    posts = core.x_posts(d, xs)
                    p.update(x_query=q, x_start=xs, x_error=rec["is_error"], posts=posts, mention_count=len(posts),
                             out_of_window_posts=sum(1 for x in posts if x["in_window"] is False))

                await asyncio.gather(*[f(p) for p in chosen for f in (extract, xsearch)])
    for p in chosen:
        if not p["abstract"] and p["api_summary"]:
            p["abstract"] = p["api_summary"]
    ranked = core.rank(chosen)
    (out / "papers.csv").write_text(core.papers_csv(ranked, fetched))
    (out / "digest.md").write_text(core.digest_md(a.topic, ranked, window, fetched, top=a.top))
    snap = {"topic": a.topic, "window": window, "fetched_at": fetched, "prompts": prompts, "skipped_links": skipped,
            "candidates": papers, "chosen": [p["arxiv_id"] for p in ranked]}
    (out / "snapshot.json").write_text(core.assert_no_key(json.dumps(snap, indent=1, ensure_ascii=False), key))
    reported = sum(x["cost_usd"] or 0 for x in c.calls)
    calc = sum(x.get("cost_calculated_usd") or 0 for x in c.calls)
    summary = {"out": str(out), "calls": len(c.calls), "candidates": len(papers), "resolving": sum(p["resolves"] for p in papers),
               "in_window": sum(p["in_window"] for p in papers), "chosen": len(chosen),
               "zero_mention": sum(p["mention_count"] == 0 for p in chosen), "cost_reported_usd": round(reported, 6),
               "x_cost_calculated_usd": round(calc, 6)}
    print(json.dumps(summary, indent=1))
    return summary


def render(run_dir, top=10):
    """Rebuild papers.csv and digest.md from a run's snapshot.json (no API calls)."""
    d = pathlib.Path(run_dir)
    snap = json.loads((d / "snapshot.json").read_text())
    by_id = {p["arxiv_id"]: p for p in snap["candidates"]}
    ranked = core.rank([by_id[i] for i in snap["chosen"]])
    (d / "papers.csv").write_text(core.papers_csv(ranked, snap["fetched_at"]))
    (d / "digest.md").write_text(core.digest_md(snap["topic"], ranked, snap["window"], snap["fetched_at"], top=top))
    print(f"rebuilt {d}/papers.csv and digest.md")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("topic", nargs="?", help='research topic, e.g. "graph neural networks"')
    p.add_argument("--render", metavar="RUN_DIR", help="only rebuild papers.csv and digest.md from RUN_DIR/snapshot.json")
    p.add_argument("--days", type=int, default=30, help="paper window: arXiv first-version date within the last N days")
    p.add_argument("--max-papers", type=int, default=15)
    p.add_argument("--posts", type=int, default=20, help="X posts per paper (count)")
    p.add_argument("--prompts", type=int, default=8, choices=range(1, len(PROMPTS) + 1), metavar="1-8", help="ai-search arxiv calls (different wordings)")
    p.add_argument("--top", type=int, default=10, help="papers in the digest")
    p.add_argument("--include-older", action="store_true", help="also keep papers older than the window")
    p.add_argument("--out", default="runs")
    a = p.parse_args(argv)
    if a.render:
        return render(a.render, a.top)
    if not a.topic:
        p.error("topic is required")
    asyncio.run(run(a))


if __name__ == "__main__":
    main()
