"""Repo Buzz Tracker: public X posts and web pages Desearch returned for one GitHub repo.

python repobuzz.py heygen-com/hyperframes --days 14
"""
import argparse, datetime as dt, json, os, pathlib, sys, time, urllib.error, urllib.parse, urllib.request
import core

BASE = "https://api.desearch.ai"
UA = "repo-buzz-tracker/0.1 (+https://desearch.ai)"


def api_key():
    path = os.environ.get("DESEARCH_API_KEY_FILE")
    key = pathlib.Path(path).expanduser().read_text().strip() if path else os.environ.get("DESEARCH_API_KEY", "").strip()
    if not key:
        raise SystemExit("Set DESEARCH_API_KEY_FILE (a file holding your key from console.desearch.ai) or DESEARCH_API_KEY")
    return key


class Client:
    """Plain HTTP. Logs every call to calls.jsonl and saves each response to raw/ with the key redacted."""

    def __init__(self, key, out):
        self.key, self.out, self.n, self.total = key, out, 0, 0.0
        (out / "raw").mkdir(parents=True, exist_ok=True)

    def _save(self, path, obj):
        s = json.dumps(obj, indent=1, ensure_ascii=False)
        if self.key in s:
            raise RuntimeError("refusing to write a file that contains the API key")
        path.write_text(s)

    def call(self, method, path, tag, params=None, body=None):
        self.n += 1
        url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": self.key, "User-Agent": UA, "Content-Type": "application/json"})
        ts = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        t0 = time.perf_counter()
        try:
            r = urllib.request.urlopen(req, timeout=120)
            st, hd, raw = r.status, dict(r.headers), r.read().decode()
        except urllib.error.HTTPError as e:
            st, hd, raw = e.code, dict(e.headers), e.read().decode()
        lat = round(time.perf_counter() - t0, 2)
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = None
        items = len(parsed) if isinstance(parsed, list) else None
        if isinstance(parsed, dict) and "search_results" in parsed:
            items = len(parsed.get("search_results") or [])
        bill = {k: v for k, v in hd.items() if k.lower().startswith("x-desearch")}
        cost, src = core.cost_of(bill, items if path == "/twitter" and st == 200 else None)
        self.total += cost
        rec = {"n": self.n, "tag": tag, "ts": ts, "method": method, "url": url, "body": body, "status": st,
               "latency_s": lat, "items": items, "billing_headers": bill, "cost_usd": cost, "cost_source": src}
        self._save(self.out / "raw" / f"{self.n:03d}-{tag}.json",
                   {**rec, "request_headers": {"Authorization": "<redacted>", "User-Agent": UA}, "response": parsed if parsed is not None else raw})
        with open(self.out / "calls.jsonl", "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[{ts}] {st} {lat}s {tag} items={items} cost={cost} ({src})", file=sys.stderr)
        return st, parsed


def run(a):
    owner, repo = core.parse_repo(a.repo)
    start = (dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=a.days)).isoformat()
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = pathlib.Path(a.out) / f"{stamp}-{owner}-{repo}"
    c = Client(api_key(), out)
    queries = {"url": core.url_query(owner, repo), "name": core.name_query(repo)}
    passes, seen = [], {}
    for qname, q in queries.items():
        for sort in ("Latest", "Top"):
            st, res = c.call("GET", "/twitter", f"x-{qname}-{sort.lower()}",
                             {"query": q, "sort": sort, "start_date": start, "count": a.count})
            posts = res if st == 200 and isinstance(res, list) else []
            stats = {"query_name": qname, "query": q, "sort": sort, "status": st, "count": a.count, "returned": len(posts),
                     "before_start": sum(1 for p in posts if core.created(p) and core.created(p).date().isoformat() < start),
                     "match": {}}
            for p in posts:
                m = core.classify(p, owner, repo)
                stats["match"][m] = stats["match"].get(m, 0) + 1
                cur = seen.setdefault(p["id"], {**p, "_match": m, "_found_by": set()})
                cur["_found_by"].add(f"{qname}-{sort.lower()}")
            passes.append(stats)
    keep = core.STRICT if a.strict else core.KEEP
    dropped_edge = [p["id"] for p in seen.values() if not core.in_window(p, start)]
    kept = [p for p in seen.values() if p["_match"] in keep and core.in_window(p, start)]
    top3 = sorted(kept, key=core.loudness, reverse=True)[:3]
    replies, reply_stats = {}, []
    for p in top3:
        st, res = c.call("GET", "/twitter/replies/post", f"replies-{p['id']}", {"post_id": p["id"], "count": a.replies})
        rs = res if st == 200 and isinstance(res, list) else []
        replies[p["id"]] = rs
        reply_stats.append({"post_id": p["id"], "status": st, "count": a.replies, "returned": len(rs),
                            "reply_count_on_post": p.get("reply_count"),
                            "not_replies_to_post": sum(1 for r in rs if str(r.get("in_reply_to_status_id")) != str(p["id"])
                                                       and str(r.get("conversation_id")) != str(p["id"]))})
    st, res = c.call("POST", "/desearch/ai/search/links/web", "links-web",
                     body={"prompt": a.web_prompt or f"{owner}/{repo} github", "tools": ["web"], "count": 10})
    web = (res or {}).get("search_results") or [] if st == 200 and isinstance(res, dict) else []
    for w in web:
        w["_match"] = core.web_match(w, owner, repo)
    rs = core.rows(kept, web, owner)
    (out / "mentions.csv").write_text(core.to_csv(rs))
    gen = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    (out / "buzz.md").write_text(core.buzz_md(owner, repo, start, kept, top3, replies, web, gen))
    snap = {"repo": f"{owner}/{repo}", "start_date": start, "generated": gen, "passes": passes, "replies": reply_stats,
            "unique_posts": len(seen), "dropped_before_start": dropped_edge, "kept": len(kept),
            "match_totals": {m: sum(1 for p in seen.values() if p["_match"] == m) for m in
                             ("url", "owner/repo", "name+context", "name-only", "x-article", "no-match")},
            "web_returned": len(web), "web_match": {m: sum(1 for w in web if w["_match"] == m) for m in ("repo-page", "mentions-name", "no-match")},
            "calls": c.n, "cost_usd_total": round(c.total, 6)}
    (out / "snapshot.json").write_text(json.dumps(snap, indent=1))
    print(json.dumps({"out": str(out), **{k: snap[k] for k in ("unique_posts", "kept", "match_totals", "web_returned", "calls", "cost_usd_total")}}))


def render(run_dir):
    """Rebuild buzz.md from a run folder's raw/ files and snapshot.json. No API calls."""
    d = pathlib.Path(run_dir)
    snap = json.loads((d / "snapshot.json").read_text())
    owner, repo = snap["repo"].split("/")
    start, seen, replies, web = snap["start_date"], {}, {}, []
    for f in sorted((d / "raw").glob("*.json")):
        r = json.loads(f.read_text())
        if r["tag"].startswith("x-") and isinstance(r["response"], list):
            for p in r["response"]:
                cur = seen.setdefault(p["id"], {**p, "_match": core.classify(p, owner, repo), "_found_by": set()})
                cur["_found_by"].add(r["tag"][2:])
        elif r["tag"].startswith("replies-"):
            replies[r["tag"][8:]] = r["response"] if isinstance(r["response"], list) else []
        elif r["tag"] == "links-web" and isinstance(r["response"], dict):
            web = r["response"].get("search_results") or []
    for w in web:
        w["_match"] = core.web_match(w, owner, repo)
    kept = [p for p in seen.values() if p["_match"] in core.KEEP and core.in_window(p, start)]
    top3 = [seen[i] for i in replies if i in seen]
    (d / "mentions.csv").write_text(core.to_csv(core.rows(kept, web, owner)))
    (d / "buzz.md").write_text(core.buzz_md(owner, repo, start, kept, top3, replies, web, snap["generated"]))
    print(d)


def main(argv=None):
    if argv is None and len(sys.argv) > 2 and sys.argv[1] == "--render":
        return render(sys.argv[2])
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("repo", help="owner/repo or a github.com URL")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--count", type=int, default=50, help="posts per X Search pass")
    ap.add_argument("--replies", type=int, default=20)
    ap.add_argument("--out", default="runs")
    ap.add_argument("--web-prompt", help='links/web prompt (default "<owner>/<repo> github")')
    ap.add_argument("--strict", action="store_true", help="drop posts that only name the repo without repo words")
    run(ap.parse_args(argv))


if __name__ == "__main__":
    main()
