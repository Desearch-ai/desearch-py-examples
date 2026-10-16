"""Launch Video Swipe File: public X video posts Desearch returned for launch / demo posts in one category.

python swipe.py "productivity apps" --terms "productivity app" "habit tracker" "todo app" --min-likes 50
"""
import argparse, datetime as dt, json, os, pathlib, sys, time, urllib.error, urllib.parse, urllib.request
import core

BASE = "https://api.desearch.ai"
UA = "launch-video-swipe-file/0.1 (+https://desearch.ai)"


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
        url = BASE + path + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
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
        cost, src = core.cost_of(bill, items if path.startswith("/twitter") and st == 200 else None)
        self.total += cost
        rec = {"n": self.n, "tag": tag, "ts": ts, "method": method, "url": url, "body": body, "status": st,
               "latency_s": lat, "items": items, "billing_headers": bill, "cost_usd": cost, "cost_source": src}
        self._save(self.out / "raw" / f"{self.n:03d}-{tag}.json",
                   {**rec, "request_headers": {"Authorization": "<redacted>", "User-Agent": UA}, "response": parsed if parsed is not None else raw})
        with open(self.out / "calls.jsonl", "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[{ts}] {st} {lat}s {tag} items={items} cost={cost} ({src})", file=sys.stderr)
        return st, parsed


def search(c, tag, query, start, count, sort, **flt):
    params = {"query": query, "sort": sort, "start_date": start, "count": count, **{k: v for k, v in flt.items() if v is not None}}
    st, res = c.call("GET", "/twitter", tag, params)
    return st, (res if st == 200 and isinstance(res, list) else [])


def refresh(c, posts, tag="urls"):
    """GET /twitter/urls with repeated urls= params; copies fresh metrics back onto the posts."""
    urls = [f"https://x.com/{(p.get('user') or {}).get('username') or 'i'}/status/{p['id']}" for p in posts]
    st, res = c.call("GET", "/twitter/urls", tag, {"urls": urls})
    got = res if isinstance(res, list) else (list(res.values()) if isinstance(res, dict) else [])
    fresh = {str(r.get("id")): r for r in got if isinstance(r, dict)}
    for p in posts:
        f = fresh.get(str(p["id"]))
        if f:
            for k in ("like_count", "retweet_count", "reply_count", "quote_count"):
                if k in f:
                    p[k] = f[k]
            p["_refreshed"] = True
    return st, len(fresh)


def run(a):
    start = (dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=a.days)).isoformat()
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = "".join(ch if ch.isalnum() else "-" for ch in a.category.lower()).strip("-")
    out = pathlib.Path(a.out) / f"{stamp}-{slug}"
    c = Client(api_key(), out)
    q = core.build_query(a.terms or [a.category])
    passes, seen = [], {}
    plan = [("main-top", "Top", "true", a.min_likes), ("main-latest", "Latest", "true", a.min_likes)]
    if a.compare:
        plan += [("video-only-top", "Top", "true", None), ("likes-only-top", "Top", None, a.min_likes)]
    ids = {}
    for tag, sort, vid, ml in plan:
        st, posts = search(c, tag, q, start, a.count, sort, is_video=vid, min_likes=ml)
        ids[tag] = [p["id"] for p in posts]
        passes.append({"tag": tag, "sort": sort, "is_video": vid, "min_likes": ml, "status": st, "count": a.count,
                       "returned": len(posts), "with_video": sum(core.has_video(p) for p in posts),
                       "below_min_likes": sum(1 for p in posts if ml and core.likes(p) < ml),
                       "before_start": [p["id"] for p in posts if not core.in_window(p, start)]})
        if tag.startswith("main"):
            for p in posts:
                seen.setdefault(p["id"], {**p, "_found_by": set()})["_found_by"].add(tag)
    final = core.select(list(seen.values()), start, a.min_likes, a.top)
    st, n_fresh = refresh(c, final, f"urls-{len(final)}") if final else (None, 0)
    final.sort(key=core.likes, reverse=True)
    gen = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    rs = core.rows(final, a.brand)
    (out / "swipe.csv").write_text(core.to_csv(rs))
    (out / "swipe.md").write_text(core.swipe_md(a.category, q, start, a.min_likes, final, gen, a.brand))
    sets = {k: set(v) for k, v in ids.items()}
    overlap = {}
    if a.compare:
        both, v, l = sets["main-top"], sets["video-only-top"], sets["likes-only-top"]
        overlap = {"both&video_only": len(both & v), "both&likes_only": len(both & l), "video_only&likes_only": len(v & l)}
    snap = {"category": a.category, "query": q, "start_date": start, "min_likes": a.min_likes, "generated": gen,
            "passes": passes, "overlap_top": overlap, "unique_main": len(seen),
            "dropped_before_start": sorted({i for ps in passes if ps["tag"].startswith("main") for i in ps["before_start"]}),
            "final": [p["id"] for p in final], "urls_status": st, "urls_returned": n_fresh,
            "calls": c.n, "cost_usd_total": round(c.total, 6)}
    (out / "snapshot.json").write_text(json.dumps(snap, indent=1))
    print(json.dumps({"out": str(out), **{k: snap[k] for k in ("unique_main", "final", "urls_returned", "calls", "cost_usd_total")}}))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("category", help="label for the output, e.g. 'productivity apps'")
    ap.add_argument("--terms", nargs="+", help="category terms ORed in parentheses (default: the category)")
    ap.add_argument("--min-likes", type=int, default=50)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--count", type=int, default=50)
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--brand", nargs="*", default=[], help="org/brand accounts that may be named in the output")
    ap.add_argument("--compare", action="store_true", help="also run is_video-only and min_likes-only Top passes")
    ap.add_argument("--out", default="runs")
    run(ap.parse_args(argv))


if __name__ == "__main__":
    main()
