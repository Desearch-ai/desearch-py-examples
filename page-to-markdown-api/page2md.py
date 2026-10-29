"""Page to Markdown: turn a list of URLs into Markdown files with Desearch Extract (js=false).

python page2md.py urls.txt --out out/
python page2md.py https://example.com https://docs.python.org/3/tutorial/
"""
import argparse, datetime as dt, json, os, pathlib, sys, time, urllib.error, urllib.parse, urllib.request
import core

BASE = "https://api.desearch.ai"
UA = "page-to-markdown/0.1 (+https://desearch.ai)"


def api_key():
    path = os.environ.get("DESEARCH_API_KEY_FILE")
    key = pathlib.Path(path).expanduser().read_text().strip() if path else os.environ.get("DESEARCH_API_KEY", "").strip()
    if not key:
        raise SystemExit("Set DESEARCH_API_KEY_FILE (a file holding your key from console.desearch.ai) or DESEARCH_API_KEY")
    return key


def now():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


class Client:
    """One GET /web/extract per call. Logs to calls.jsonl and saves raw responses with the key redacted."""

    def __init__(self, key, out=None, fmt="markdown", timeout=120):
        self.key, self.out, self.fmt, self.timeout, self.n, self.total = key, out, fmt, timeout, 0, 0.0
        if out:
            (out / "raw").mkdir(parents=True, exist_ok=True)

    def extract(self, url, tag="page"):
        self.n += 1
        q = urllib.parse.urlencode({"url": url, "format": self.fmt, "js": "false"})
        req = urllib.request.Request(f"{BASE}/web/extract?{q}", headers={"Authorization": self.key, "User-Agent": UA})
        ts, t0 = now(), time.perf_counter()
        try:
            r = urllib.request.urlopen(req, timeout=self.timeout)
            st, hd, body = r.status, dict(r.headers), r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            st, hd, body = e.code, dict(e.headers), e.read().decode("utf-8", "replace")
        except Exception as e:  # timeout, DNS, reset
            st, hd, body = 0, {}, f"{type(e).__name__}: {e}"
        lat = round(time.perf_counter() - t0, 2)
        bill = {k: v for k, v in hd.items() if k.lower().startswith("x-desearch")}
        cost, src = core.cost_of(bill)
        self.total += cost
        rec = {"n": self.n, "tag": tag, "ts": ts, "url": url, "format": self.fmt, "js": "false", "status": st,
               "latency_s": lat, "bytes": len(body), "billing_headers": bill, "cost_usd": cost, "cost_source": src}
        if self.out:
            raw = {**rec, "request": {"method": "GET", "url": f"{BASE}/web/extract?{q}",
                                      "headers": {"Authorization": "<redacted>", "User-Agent": UA}},
                   "content_type": hd.get("Content-Type") or hd.get("content-type"), "body": body}
            s = core.redact(json.dumps(raw, indent=1, ensure_ascii=False), self.key)
            (self.out / "raw" / f"{self.n:03d}-{tag}.json").write_text(s)
            with open(self.out / "calls.jsonl", "a") as f:
                f.write(json.dumps(rec) + "\n")
        return st, body, rec


def to_markdown(body, fmt, base=""):
    if fmt == "markdown":
        return core.markdown_parts(body)
    if fmt == "html":
        return core.html_to_markdown(body, base)
    return "", core.text_to_markdown(body), []


def page_to_markdown(client, url, tag="page", retry=True):
    """Fetch one URL. Retries once (after 2 s) when a 200 comes back empty. Returns a result dict."""
    if not core.valid_url(url):
        return {"url": url, "status": "skipped", "attempts": 0, "title": "", "markdown": "", "links": [], "words": 0,
                "empty": False, "empty_first": False, "latency_s": 0.0, "latency_each": [], "cost_usd": 0.0,
                "error": "not an http(s) URL, skipped locally (no call made)", "fetched": now()}
    attempts, lats, cost = [], [], 0.0
    for i in range(2 if retry else 1):
        st, body, rec = client.extract(url, f"{tag}-a{i + 1}")
        title, md, links = to_markdown(body, client.fmt, url) if st == 200 else ("", "", [])
        attempts.append(rec); lats.append(rec["latency_s"]); cost += rec["cost_usd"]
        empty = st == 200 and core.is_empty(md)
        if not (empty and retry and i == 0):
            break
        time.sleep(2)
    return {"url": url, "status": st, "attempts": len(attempts), "title": title, "markdown": md, "links": links,
            "words": core.word_count(md), "empty": st == 200 and core.is_empty(md),
            "empty_first": attempts[0]["status"] == 200 and len(attempts) > 1,
            "latency_s": round(sum(lats), 2), "latency_each": lats, "cost_usd": round(cost, 6),
            "error": None if st == 200 else body[:300], "fetched": attempts[-1]["ts"]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("urls", nargs="+", help="URLs, or a .txt file with one URL per line")
    ap.add_argument("--out", default="out", help="folder for .md files, calls.jsonl, raw/ and summary.md")
    ap.add_argument("--format", default="markdown", choices=["markdown", "html", "text"],
                    help="Extract format: markdown comes back ready to save; html and text are converted locally")
    ap.add_argument("--no-retry", action="store_true", help="skip the one retry on an empty 200")
    a = ap.parse_args(argv)
    urls = []
    for u in a.urls:
        if u.endswith(".txt") and pathlib.Path(u).exists():
            urls += [l.strip() for l in pathlib.Path(u).read_text().splitlines() if l.strip() and not l.startswith("#")]
        else:
            urls.append(u)
    out = pathlib.Path(a.out); (out / "pages").mkdir(parents=True, exist_ok=True)
    c = Client(api_key(), out, a.format)
    rows = []
    for n, u in enumerate(urls, 1):
        r = page_to_markdown(c, u, core.slug(u, n), retry=not a.no_retry)
        rows.append(r)
        if r["status"] == 200 and not r["empty"]:
            (out / "pages" / f"{core.slug(u, n)}.md").write_text(
                core.front_matter(u, r["title"], r["fetched"], r["status"], r["attempts"], r["words"]) + r["markdown"] + "\n")
        print(f"[{now()}] {r['status']} {'EMPTY ' if r['empty'] else ''}{r['words']}w a={r['attempts']} "
              f"{r['latency_s']}s ${r['cost_usd']:.4f} {u}", flush=True)
    (out / "results.json").write_text(json.dumps([{k: v for k, v in r.items() if k != "markdown"} for r in rows], indent=1))
    (out / "summary.md").write_text(f"# Page to Markdown run, {now()}\n\n" + core.summary_table(rows) +
                                    f"\n\nHeader total: ${c.total:.4f} over {c.n} calls\n")
    print(f"done: {len(rows)} URLs, {c.n} calls, header total ${c.total:.4f}")
    return rows


if __name__ == "__main__":
    main()
