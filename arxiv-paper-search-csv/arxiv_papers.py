"""arXiv Paper Search to CSV: topic queries in, one deduped CSV of arXiv papers out.

Made by Desearch (https://desearch.ai).

Live:     python arxiv_papers.py --queries "retrieval augmented generation evaluation" "small language models on device"
Offline:  python arxiv_papers.py --from-raw samples/raw-sample.json
Key: DESEARCH_API_KEY env var, or a file named by DESEARCH_KEY_FILE.
"""
import argparse, csv, datetime as dt, json, os, re, time

BASE = "https://api.desearch.ai"
FIELDS = ["arxiv_id", "title", "authors", "abs_link", "id_month", "published_date", "summary_snippet", "queries", "links_seen"]
ID_RX = re.compile(r"arxiv\.org/(?:abs|html|pdf)/(\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?", re.I)


def now():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def call(s, query, count, label):
    """One REST AI Search call restricted to the arxiv tool (worked in testing; the docs list web and twitter)."""
    body = {"prompt": query, "tools": ["arxiv"], "streaming": False, "result_type": "ONLY_LINKS", "count": count}
    at, t0 = now(), time.time()
    try:
        r = s.post(f"{BASE}/desearch/ai/search", json=body, timeout=180)
        status, hdr = r.status_code, {k.lower(): v for k, v in r.headers.items()}
        try: data = r.json()
        except ValueError: data = {"_text": r.text[:5000]}
    except Exception as e:
        status, hdr, data = None, {}, {"_error": repr(e)}
    rec = {"label": label, "query": query, "request": body, "at": at, "seconds": round(time.time() - t0, 2),
           "status": status, "cost_usd": hdr.get("x-desearch-cost-usd"), "usage_count": hdr.get("x-desearch-usage-count"),
           "body": data}
    print(f"{at} {label:20s} {status} {rec['seconds']:6.2f}s n={len(results(rec))} cost={rec['cost_usd']}", flush=True)
    return rec


def results(rec):
    b = rec.get("body")
    return b.get("search") or [] if isinstance(b, dict) else []


def arxiv_id(link):
    m = ID_RX.search(link or "")
    return m.group(1) if m else None


def clean_title(t, pid):
    t = re.sub(r"^\[[^\]]+\]\s*", "", t or "")
    return " ".join(t.split())


def authors(v):
    # The author field came back as one ';'-joined string of name parts in testing, so it is kept as returned.
    if isinstance(v, list): return "; ".join(map(str, v))
    return " ".join(str(v or "").split())


def id_month(pid):
    m = re.match(r"(\d{2})(\d{2})\.", pid)
    return f"20{m.group(1)}-{m.group(2)}" if m else ""


def pub_date(r, pid):
    """Date only from abstract-page results, and only if not before the month in the id.
    HTML-page results carried dates older than the paper itself in testing, so they are skipped."""
    d = r.get("published_date") or ""
    if "/abs/" not in (r.get("link") or "") or not d: return ""
    return d if not id_month(pid) or d[:7] >= id_month(pid) else ""


def snippet(r):
    for h in r.get("highlights") or []:
        if "Abstract:" in h:
            return " ".join(h.split("Abstract:", 1)[1].split())[:300]
    return ""  # only abstract text is kept; HTML-page snippets were random passages in testing


def build(raw, out_csv):
    papers, other, total = {}, [], 0
    for rec in raw["calls"]:
        if rec.get("empty_check"): continue
        for r in results(rec):
            total += 1
            pid = arxiv_id(r.get("link"))
            if not pid:
                other.append(r.get("link")); continue
            p = papers.setdefault(pid, {"arxiv_id": pid, "title": "", "authors": "", "abs_link": f"https://arxiv.org/abs/{pid}",
                                        "id_month": id_month(pid), "published_date": "", "summary_snippet": "", "queries": [], "links_seen": 0})
            p["links_seen"] += 1
            if rec["query"] not in p["queries"]: p["queries"].append(rec["query"])
            p["title"] = p["title"] or clean_title(r.get("title"), pid)
            if "/abs/" in (r.get("link") or ""): p["authors"] = p["authors"] or authors(r.get("author"))
            p["published_date"] = p["published_date"] or pub_date(r, pid)
            p["summary_snippet"] = p["summary_snippet"] or snippet(r)
    rows = sorted(papers.values(), key=lambda p: p["id_month"] or "", reverse=True)
    for p in rows: p["queries"] = " | ".join(p["queries"])
    os.makedirs(os.path.dirname(out_csv) or ".", exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS); w.writeheader(); w.writerows(rows)
    print(f"links returned={total} unique arXiv papers={len(rows)} non-arXiv links={len(other)} "
          f"with date={sum(bool(p['published_date']) for p in rows)} with authors={sum(bool(p['authors']) for p in rows)}")
    print(f"wrote {out_csv}")
    return rows


def run_live(a):
    import requests
    key = os.environ.get("DESEARCH_API_KEY") or open(os.path.expanduser(os.environ["DESEARCH_KEY_FILE"])).read().strip()
    s = requests.Session(); s.headers["Authorization"] = key
    raw = {"started": now(), "count": a.count, "calls": []}
    for i, q in enumerate(a.queries, 1):
        raw["calls"].append(call(s, q, a.count, f"query {i}"))
    if a.empty_check:
        rec = call(s, a.empty_check, a.count, "empty-result check"); rec["empty_check"] = True; raw["calls"].append(rec)
    os.makedirs("output", exist_ok=True)
    json.dump(raw, open(f"output/raw-{a.label}.json", "w"), indent=1, default=str)
    return raw


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Search arXiv papers with the Desearch API and save a CSV.")
    ap.add_argument("--queries", nargs="+", help="topic queries")
    ap.add_argument("--count", type=int, default=10, help="links per query (10 is the smallest billed unit seen)")
    ap.add_argument("--empty-check", help="optional made-up topic to see what an empty result returns and costs")
    ap.add_argument("--label", default="run-1"); ap.add_argument("--from-raw", help="rebuild the CSV from a saved raw JSON, no API calls")
    a = ap.parse_args()
    if not a.from_raw and not a.queries: ap.error("--queries or --from-raw is required")
    raw = json.load(open(a.from_raw)) if a.from_raw else run_live(a)
    label = a.label if not a.from_raw else os.path.basename(a.from_raw).removeprefix("raw-").removesuffix(".json")
    build(raw, f"output/arxiv-papers-{label}.csv")
