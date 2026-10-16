"""Trending Hashtags Finder: which hashtags are trending on X in the countries you pick, and are people actually posting them right now.

usage: python find_hashtags.py --countries US=23424977,GB=23424975 [--trends 50] [--top 6] [--sample 20] [--hours 6] [--out runs]
Key: DESEARCH_API_KEY, or a file path in DESEARCH_API_KEY_FILE.
"""
import argparse, csv, datetime as dt, json, os, pathlib, sys, time, urllib.error, urllib.parse, urllib.request
import core

BASE = "https://api.desearch.ai"
UA = "trending-hashtags-finder/0.1 (+made-by-desearch)"


def items_of(body):
    if isinstance(body, list):
        return body
    return core.trends_of(body)


def parse_countries(s):
    out = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        label, _, w = part.rpartition("=")
        out.append((label or w, int(w)))
    return out
    if not k and os.environ.get("DESEARCH_API_KEY_FILE"):
        k = pathlib.Path(os.environ["DESEARCH_API_KEY_FILE"]).read_text().strip()
    if not k:
        sys.exit("Set DESEARCH_API_KEY or DESEARCH_API_KEY_FILE")
    return k


def api_key():
    k = os.environ.get("DESEARCH_API_KEY")
    if not k and os.environ.get("DESEARCH_API_KEY_FILE"):
        k = pathlib.Path(os.environ["DESEARCH_API_KEY_FILE"]).read_text().strip()
    if not k:
        sys.exit("Set DESEARCH_API_KEY or DESEARCH_API_KEY_FILE")
    return k


class Client:
    """Plain HTTP. Logs each call to calls.jsonl and saves each response to raw/ with the key redacted."""

    def __init__(self, key, out):
        self.key, self.out, self.n, self.total = key, pathlib.Path(out), 0, 0.0
        (self.out / "raw").mkdir(parents=True, exist_ok=True)

    def _save(self, path, obj):
        s = json.dumps(obj, indent=1, ensure_ascii=False)
        if self.key in s:
            raise RuntimeError("refusing to write a file that contains the API key")
        path.write_text(s)

    def get(self, path, params, tag):
        self.n += 1
        url = BASE + path + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"Authorization": self.key, "User-Agent": UA})
        ts = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        t0 = time.perf_counter()
        try:
            r = urllib.request.urlopen(req, timeout=120)
            st, hd, raw = r.status, dict(r.headers), r.read().decode()
        except urllib.error.HTTPError as e:
            st, hd, raw = e.code, dict(e.headers), e.read().decode()
        lat = round(time.perf_counter() - t0, 2)
        try:
            body = json.loads(raw)
        except ValueError:
            body = raw[:2000]
        bill = {k: v for k, v in hd.items() if k.lower().startswith("x-desearch")}
        cost = next((float(v) for k, v in bill.items() if k.lower() == "x-desearch-cost-usd"), 0.0)
        self.total += cost
        rec = {"n": self.n, "tag": tag, "time": ts, "request": {"method": "GET", "url": url,
               "headers": {"Authorization": "<redacted>", "User-Agent": UA}}, "status": st,
               "latency_s": lat, "billing_headers": bill, "items": len(items_of(body))}
        self._save(self.out / "raw" / f"{self.n:03d}-{tag}.json", {**rec, "body": body})
        with open(self.out / "calls.jsonl", "a") as f:
            line = json.dumps(rec)
            if self.key in line:
                raise RuntimeError("refusing to log the API key")
            f.write(line + "\n")
        print(f"[{ts}] {st} {tag} {lat}s items={rec['items']} cost={cost}", file=sys.stderr)
        return st, body




def slug(s):
    return "".join(ch if ch.isalnum() else "-" for ch in s.lower()).strip("-")[:30] or "x"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--countries", default="US=23424977", help="LABEL=WOEID pairs, comma separated (Worldwide is 1)")
    ap.add_argument("--trends", type=int, default=50, help="trends per country, 30 to 100")
    ap.add_argument("--top", type=int, default=6, help="how many hashtags to sample with X search")
    ap.add_argument("--sample", type=int, default=20, help="latest posts per hashtag")
    ap.add_argument("--hours", type=float, default=6, help="only count posts from the last N hours")
    ap.add_argument("--out", default="runs")
    ap.add_argument("--check-empty", metavar="TAG", help="also search one made-up hashtag to see what an empty result costs")
    a = ap.parse_args(argv)

    run = pathlib.Path(a.out) / dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    c = Client(api_key(), run)
    now = dt.datetime.now(dt.timezone.utc)
    start = now - dt.timedelta(hours=a.hours)

    bodies = {}
    for label, woeid in parse_countries(a.countries):
        st, body = c.get("/twitter/trends", {"woeid": woeid, "count": a.trends}, f"trends-{slug(label)}")
        bodies[label] = body if st < 300 else {}
    by_country, counts = core.hashtags_by_country(bodies)
    rows = core.merge_countries(by_country)

    stats = {}
    for r in rows[: a.top]:
        q = core.build_query([r["hashtag"]])
        st, body = c.get("/twitter", {"query": q, "sort": "Latest", "count": a.sample,
                                      "start_date": start.strftime("%Y-%m-%d")}, f"x-{slug(r['hashtag'])}")
        posts = body if st < 300 and isinstance(body, list) else []
        kept, dropped = core.keep_after(posts, start)
        s = core.post_stats(r["hashtag"], kept, now)
        s["dropped_old"] = dropped
        stats[r["hashtag"].lower()] = s

    if a.check_empty:
        st, body = c.get("/twitter", {"query": a.check_empty, "sort": "Latest", "count": 10}, "empty-check")

    generated = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    md = core.render_md(rows, stats, counts, generated)
    (run / "shortlist.md").write_text(md)
    with open(run / "shortlist.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["hashtag", "countries", "best_rank", "sample", "accounts", "newest_min", "posts_per_hour",
                    "median_likes", "top_lang", "co_hashtags", "verdict", "examples"])
        for r in rows:
            s = stats.get(r["hashtag"].lower())
            w.writerow([r["hashtag"], ";".join(f"{k}:{v}" for k, v in r["countries"].items()), r["best_rank"],
                        *( [s["sample"], s["authors"], s["newest_min"], s["posts_per_hour"], s["median_likes"], s["top_lang"],
                            " ".join(s["co_hashtags"]), core.verdict(r, s), " ".join(s["examples"])] if s else [""] * 8 + ["not sampled", ""])])
    (run / "summary.json").write_text(json.dumps({"generated": generated, "counts": counts, "rows": rows, "stats": stats,
                                                  "calls": c.n, "header_total_usd": round(c.total, 6)}, indent=1, ensure_ascii=False))
    print(md)
    print(f"{c.n} calls, header total ${c.total:.4f}, files in {run}", file=sys.stderr)


if __name__ == "__main__":
    main()
