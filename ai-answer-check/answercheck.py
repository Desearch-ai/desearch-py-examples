#!/usr/bin/env python3
"""AI Answer Check: is my brand named in an AI answer built from live web and X sources?

Asks each buyer question N times through Desearch AI Search with a fixed system message, then records per run:
brand named or not, its first-mention position, the other brands named, the sentence that names the brand,
and the cited domains. Writes a share-of-answer table, the top cited domains, runs.csv, a JSON snapshot and
a cost line from the X-Desearch-Cost-Usd response header.

Endpoint (base https://api.desearch.ai, header Authorization: <key>):
  POST /desearch/ai/search  {"prompt", "tools", "result_type": "LINKS_WITH_FINAL_SUMMARY",
                             "system_message", "streaming": false, "count", "date_filter"}
"""
import argparse, collections, csv, datetime as dt, json, os, re, sys, time
from urllib.parse import urlparse

BASE = "https://api.desearch.ai"
ENDPOINT = "/desearch/ai/search"
DEFAULT_SYSTEM_MESSAGE = ("Answer like a neutral buyer's advisor. Name specific products, "
                          "say who each one suits, and cite your sources.")
DATE_FILTERS = ["PAST_24_HOURS", "PAST_2_DAYS", "PAST_WEEK", "PAST_2_WEEKS", "PAST_MONTH",
                "PAST_2_MONTHS", "PAST_YEAR", "PAST_2_YEARS"]


# ---------------------------------------------------------------- key

def api_key():
    """DESEARCH_API_KEY, else the file named by DESEARCH_API_KEY_FILE. Never printed or saved."""
    k = os.environ.get("DESEARCH_API_KEY", "").strip()
    if not k and os.environ.get("DESEARCH_API_KEY_FILE"):
        with open(os.path.expanduser(os.environ["DESEARCH_API_KEY_FILE"])) as f:
            k = f.read().strip()
    if not k:
        sys.exit("Set DESEARCH_API_KEY (or DESEARCH_API_KEY_FILE) to your key from console.desearch.ai")
    return k


# ---------------------------------------------------------------- pure logic

LINK_RE = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")
BARE_URL_RE = re.compile(r"https?://[^\s)\]>\"']+")
BARE_CITE_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\](?!\()")
HTML_A_RE = re.compile(r"<a\s[^>]*?href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
X_STATUS_RE = re.compile(r"https?://(?:www\.)?(?:x|twitter)\.com/[A-Za-z0-9_]{1,15}(?:/status/\d+)?\S*")
HANDLE_RE = re.compile(r"(?<![\w@.])@[A-Za-z0-9_]{1,15}\b")


def redact_x_users(text):
    """For public output: X post links and @handles become 'an X user'. Raw files keep the originals."""
    t = X_STATUS_RE.sub("an X user", text or "")
    return HANDLE_RE.sub("an X user", t)


def domain(url):
    """'https://www.Example.com/x' -> 'example.com'. twitter.com is shown as x.com."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    if host.startswith("www."):
        host = host[4:]
    if host in ("twitter.com", "mobile.twitter.com", "mobile.x.com"):
        host = "x.com"
    return host


def cited_urls(completion):
    """URLs cited in the summary, in order, unique: markdown links first, then bare URLs."""
    out = []
    for _, u in LINK_RE.findall(completion or ""):
        if u not in out:
            out.append(u)
    for u, _ in HTML_A_RE.findall(completion or ""):
        if u.startswith("http") and u not in out:
            out.append(u)
    rest = TAG_RE.sub(" ", HTML_A_RE.sub(" ", LINK_RE.sub(" ", completion or "")))
    for u in BARE_URL_RE.findall(rest):
        u = u.rstrip(".,;")
        if u not in out:
            out.append(u)
    return out


def unlinked_citations(completion):
    """Citation markers with no URL, e.g. '[8, 17]'."""
    return len(BARE_CITE_RE.findall(LINK_RE.sub(" ", completion or "")))


def plain_text(completion):
    """Summary text without link targets, citation markers or markdown emphasis (used for brand matching)."""
    t = LINK_RE.sub(" ", completion or "")
    t = HTML_A_RE.sub(lambda m: TAG_RE.sub("", m.group(2)), t)
    t = TAG_RE.sub(" ", t)
    t = BARE_URL_RE.sub(" ", t)
    t = BARE_CITE_RE.sub(" ", t)
    t = re.sub(r"[*_`#]+", "", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" +([.,;:!?])", r"\1", t)
    return t.strip()


def brand_patterns(brands):
    """{'Asana': {'aliases': [...], 'case_sensitive': False}, ...} -> {'Asana': compiled regex}.
    Names match whole words, case-insensitive unless case_sensitive is set (use it for names that are
    also common words, e.g. Notion). A plain list of aliases is accepted too."""
    out = {}
    for name, spec in brands.items():
        if isinstance(spec, dict):
            aliases, cs = spec.get("aliases", []), spec.get("case_sensitive", False)
        else:
            aliases, cs = spec, False
        terms = sorted({name, *aliases}, key=len, reverse=True)
        alt = "|".join(re.escape(t) for t in terms if t)
        out[name] = re.compile(r"(?<![\w.])(?:" + alt + r")(?![\w])", 0 if cs else re.I)
    return out


def find_mentions(text, patterns):
    """{brand: first char offset} for every brand named in text."""
    found = {}
    for name, rx in patterns.items():
        m = rx.search(text)
        if m:
            found[name] = m.start()
    return found


def split_sentences(text):
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])|\n+", text)
    return [p.strip(" -\u2022") for p in parts if p.strip(" -\u2022")]


def brand_sentence(text, rx):
    for s in split_sentences(text):
        if rx.search(s):
            return s
    return ""


def analyse_run(completion, brand, patterns):
    """Per-run record from one summary."""
    text = plain_text(completion)
    found = find_mentions(text, patterns)
    order = sorted(found, key=found.get)
    urls = cited_urls(completion)
    return {
        "brand_named": brand in found,
        "brand_position": order.index(brand) + 1 if brand in found else None,
        "brands_named": order,
        "others_named": [b for b in order if b != brand],
        "brand_sentence": brand_sentence(text, patterns[brand]) if brand in found else "",
        "cited_urls": urls,
        "cited_domains": sorted({domain(u) for u in urls if domain(u)}),
        "unlinked_citations": unlinked_citations(completion),
        "html_links": len(HTML_A_RE.findall(completion or "")),
        "summary_chars": len(completion or ""),
    }


def source_links(body):
    """Links the API returned as sources: [(kind, url, title)]."""
    out = []
    if not isinstance(body, dict):
        return out
    for it in body.get("search") or []:
        out.append(("web", it.get("link") or "", it.get("title") or ""))
    for t in body.get("tweets") or []:
        url = t.get("url") or ""
        if not url and t.get("id") and isinstance(t.get("user"), dict):
            url = f"https://x.com/{t['user'].get('username', 'i')}/status/{t['id']}"
        out.append(("x", url, (t.get("text") or "")[:120]))
    return out


def share_table(runs, brands):
    """Rows per brand: runs named, share, questions named at least once, mean first-mention position."""
    ok = [r for r in runs if r.get("ok")]
    n = len(ok)
    qs = sorted({r["question"] for r in ok})
    rows = []
    for b in brands:
        named = [r for r in ok if b in r["brands_named"]]
        pos = [r["brands_named"].index(b) + 1 for r in named]
        rows.append({
            "brand": b, "runs_named": len(named), "runs": n,
            "share": round(len(named) / n, 3) if n else 0.0,
            "questions_named": len({r["question"] for r in named}), "questions": len(qs),
            "first_named": sum(1 for p in pos if p == 1),
            "unprompted_runs_named": sum(1 for r in named if b not in r.get("brands_in_question", [])),
            "unprompted_runs": sum(1 for r in ok if b not in r.get("brands_in_question", [])),
            "mean_position": round(sum(pos) / len(pos), 2) if pos else None,
        })
    rows.sort(key=lambda r: (-r["runs_named"], r["mean_position"] or 99, r["brand"]))
    return rows


def top_domains(runs, key="cited_domains", limit=15):
    """[(domain, runs citing it)] counted once per run."""
    c = collections.Counter()
    for r in runs:
        if r.get("ok"):
            c.update(set(r.get(key) or []))
    return c.most_common(limit)


def jaccard(a, b):
    a, b = set(a), set(b)
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def consistency(runs):
    """Per question: brand named in k of n runs, positions, identical brand lists, mean pairwise domain overlap."""
    by_q = collections.OrderedDict()
    for r in runs:
        if r.get("ok"):
            by_q.setdefault(r["question"], []).append(r)
    out = []
    for q, rs in by_q.items():
        lists = [tuple(sorted(r["brands_named"])) for r in rs]
        pairs = [(i, j) for i in range(len(rs)) for j in range(i + 1, len(rs))]
        overlap = [jaccard(rs[i]["cited_domains"], rs[j]["cited_domains"]) for i, j in pairs]
        out.append({
            "question": q, "runs": len(rs),
            "brand_named_runs": sum(1 for r in rs if r["brand_named"]),
            "positions": [r["brand_position"] for r in rs],
            "same_brand_set_all_runs": len(set(lists)) == 1,
            "distinct_brand_sets": len(set(lists)),
            "domain_overlap": round(sum(overlap) / len(overlap), 2) if overlap else None,
        })
    return out


def cost_summary(calls):
    billed = [c for c in calls if c.get("cost_usd") is not None]
    total = round(sum(c["cost_usd"] for c in billed), 6)
    return {"calls": len(calls), "billed_calls": len(billed), "total_usd": total,
            "units": sum(c.get("usage_count") or 0 for c in billed),
            "errors": sum(1 for c in calls if not c.get("ok"))}


def fmt_pct(x):
    return f"{round(100 * x)}%"


def md_escape(s):
    return (s or "").replace("|", "\\|").replace("\n", " ")


def render_markdown(meta, runs, calls, brands, ab=None):
    L = []
    ok_runs = [r for r in runs if r.get("ok")]
    L.append(f"# AI Answer Check: {meta['brand']}")
    L.append("")
    L.append(f"{meta['started']} (Asia/Tbilisi). {len(meta['questions'])} questions x {meta['runs']} runs = "
             f"{len(ok_runs)} answers. Desearch AI Search, tools `{','.join(meta['tools'])}`, "
             f"system message: \"{meta['system_message']}\".")
    L.append("")
    L.append("## Share of answer")
    L.append("")
    L.append("| Brand | Runs that name it | Share | Share when the question does not name it | Questions (of %d) | Named first | Mean position |" % len(meta["questions"]))
    L.append("|---|---|---|---|---|---|---|")
    for r in share_table(runs, brands):
        star = " (you)" if r["brand"] == meta["brand"] else ""
        un = (f"{r['unprompted_runs_named']} / {r['unprompted_runs']} ({fmt_pct(r['unprompted_runs_named'] / r['unprompted_runs'])})"
              if r["unprompted_runs"] else "-")
        L.append(f"| {r['brand']}{star} | {r['runs_named']} / {r['runs']} | {fmt_pct(r['share'])} | {un} | "
                 f"{r['questions_named']} | {r['first_named']} | {r['mean_position'] if r['mean_position'] else '-'} |")
    L.append("")
    L.append("Position = order of first mention among the brands you listed (1 = named first). "
             "A question that names a brand (\"<brand> alternatives\") almost always gets it back, so the fourth column leaves those questions out.")
    L.append("")
    L.append("## Per question")
    L.append("")
    L.append(f"| Question | {meta['brand']} named | Positions | Same brand set in all runs | Cited-domain overlap |")
    L.append("|---|---|---|---|---|")
    for c in consistency(runs):
        pos = ", ".join(str(p) if p else "-" for p in c["positions"])
        L.append(f"| {md_escape(c['question'])} | {c['brand_named_runs']} / {c['runs']} | {pos} | "
                 f"{'yes' if c['same_brand_set_all_runs'] else 'no (%d sets)' % c['distinct_brand_sets']} | "
                 f"{c['domain_overlap'] if c['domain_overlap'] is not None else '-'} |")
    L.append("")
    L.append("Cited-domain overlap = mean Jaccard overlap of the cited domains between runs of the same question (1 = identical).")
    L.append("")
    L.append("## Top cited domains")
    L.append("")
    L.append("Domains linked inside the answers, counted once per answer. These are the pages worth being on. "
             "Links to individual X posts are counted under x.com and not listed one by one.")
    L.append("")
    L.append("| Domain | Answers citing it |")
    L.append("|---|---|")
    for d, n in top_domains(runs):
        L.append(f"| {d} | {n} |")
    L.append("")
    L.append("## Top source domains")
    L.append("")
    L.append("All links returned with the answers (web results and X posts), counted once per answer.")
    L.append("")
    L.append("| Domain | Answers |")
    L.append("|---|---|")
    for d, n in top_domains(runs, key="source_domains", limit=10):
        L.append(f"| {d} | {n} |")
    L.append("")
    L.append(f"## How the answers describe {meta['brand']}")
    L.append("")
    seen = set()
    for r in ok_runs:
        s = r.get("brand_sentence")
        if s and s not in seen:
            seen.add(s)
            L.append(f"- ({md_escape(r['question'])}, run {r['run']}) {md_escape(redact_x_users(s))}")
    if not seen:
        L.append("- Not named in any answer.")
    L.append("")
    if ab:
        L.append("## With vs without the system message")
        L.append("")
        L.append("| Question | Variant | Brands named per run | Summary length (chars) | Cited domains per run |")
        L.append("|---|---|---|---|---|")
        for row in ab:
            L.append(f"| {md_escape(row['question'])} | {row['variant']} | {row['brands']} | {row['chars']} | {row['domains']} |")
        L.append("")
    cs = cost_summary(calls)
    lat = sorted(c["latency_s"] for c in calls if c.get("ok"))
    L.append("## Cost")
    L.append("")
    line = (f"{cs['calls']} calls, {cs['units']} billed units, **${cs['total_usd']:.4f}** "
            f"(sum of the `X-Desearch-Cost-Usd` response headers).")
    if lat:
        line += f" Latency {lat[0]:.1f} to {lat[-1]:.1f} s per call (median {lat[len(lat) // 2]:.1f} s)."
    if cs["errors"]:
        line += f" {cs['errors']} call(s) failed, see snapshot.json."
    L.append(line)
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------- network

class Client:
    def __init__(self, key, session=None, base=BASE, timeout=120, raw_dir=None):
        import requests
        self._key = key
        self.s = session or requests.Session()
        self.base = base
        self.timeout = timeout
        self.raw_dir = raw_dir
        self.calls = []

    def _save(self, name, obj):
        if not self.raw_dir:
            return
        os.makedirs(self.raw_dir, exist_ok=True)
        s = json.dumps(obj, indent=1, ensure_ascii=False)
        if self._key and self._key in s:
            raise RuntimeError("refusing to write the API key to disk")
        with open(os.path.join(self.raw_dir, name), "w") as f:
            f.write(s)

    def ai_search(self, body, tag="call"):
        """One non-streamed AI Search call; one retry on 429/5xx/network error. Returns (ok, body, call)."""
        attempt = 0
        while True:
            attempt += 1
            ts = dt.datetime.now().astimezone().isoformat(timespec="seconds")
            t0 = time.perf_counter()
            status, headers, data, err = None, {}, None, None
            try:
                r = self.s.post(self.base + ENDPOINT, json=body, timeout=self.timeout,
                                headers={"Authorization": self._key, "Content-Type": "application/json"})
                status, headers = r.status_code, {k.lower(): v for k, v in r.headers.items()}
                try:
                    data = r.json()
                except ValueError:
                    data = r.text
            except Exception as e:  # network error
                err = f"{type(e).__name__}: {e}"
            lat = round(time.perf_counter() - t0, 3)
            cost = headers.get("x-desearch-cost-usd")
            call = {"ts": ts, "tag": tag, "attempt": attempt, "status": status, "latency_s": lat,
                    "ok": status == 200 and isinstance(data, dict) and err is None,
                    "cost_usd": float(cost) if cost not in (None, "") else None,
                    "usage_count": int(headers["x-desearch-usage-count"]) if headers.get("x-desearch-usage-count") else None,
                    "service": headers.get("x-desearch-service"), "error": err,
                    "content_type": headers.get("content-type")}
            if not call["ok"] and err is None:
                call["error"] = (json.dumps(data)[:300] if not isinstance(data, str) else data[:300])
            self.calls.append(call)
            self._save(f"{len(self.calls):03d}-{tag}.json", {
                "request": {"method": "POST", "url": self.base + ENDPOINT,
                            "headers": {"Authorization": "<redacted>"}, "body": body},
                "call": call, "response_headers": headers, "body": data})
            retry = err is not None or status == 429 or (status or 0) >= 500
            print(f"  {tag} {status} {lat}s cost={cost}", file=sys.stderr)
            if call["ok"] or not retry or attempt >= 2:
                return call["ok"], data, call
            time.sleep(3)


def build_body(question, system_message, tools, count=None, date_filter=None):
    body = {"prompt": question, "tools": list(tools), "result_type": "LINKS_WITH_FINAL_SUMMARY", "streaming": False}
    if system_message:
        body["system_message"] = system_message
    if count:
        body["count"] = count
    if date_filter:
        body["date_filter"] = date_filter
    return body


def slug(s, n=40):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:n] or "q"


def run_check(cfg, client, runs_per_q, system_message, tools, count, date_filter, max_spend, ab_n=0, log=print):
    brand = cfg["brand"]["name"]
    brands = brand_map(cfg)
    patterns = brand_patterns(brands)
    jobs = [(q, k, system_message, "main") for q in cfg["questions"] for k in range(1, runs_per_q + 1)]
    if ab_n:
        jobs += [(q, k, "", "no_system_message") for q in cfg["questions"][:ab_n] for k in range(1, runs_per_q + 1)]
    runs, ab_runs = [], []
    spent = 0.0
    for i, (q, k, sm, variant) in enumerate(jobs, 1):
        if spent >= max_spend:
            log(f"stopping: spend ${spent:.4f} reached --max-spend ${max_spend}")
            break
        n_before = len(client.calls)
        ok, body, call = client.ai_search(build_body(q, sm, tools, count, date_filter),
                                          tag=f"{variant[:4]}-{slug(q)}-r{k}")
        spent += sum(c.get("cost_usd") or 0.0 for c in client.calls[n_before:])
        rec = make_record(q, k, variant, ok, body, call, brand, patterns)
        (runs if variant == "main" else ab_runs).append(rec)
    return brands, runs, ab_runs


def brand_map(cfg):
    brands = {}
    for c in [cfg["brand"]] + cfg.get("competitors", []):
        brands[c["name"]] = {"aliases": c.get("aliases", []), "case_sensitive": bool(c.get("case_sensitive"))}
    return brands


def make_record(q, k, variant, ok, body, call, brand, patterns):
    rec = {"question": q, "run": k, "variant": variant, "ok": ok, "ts": call["ts"],
           "latency_s": call["latency_s"], "cost_usd": call["cost_usd"], "status": call["status"],
           "brands_in_question": sorted(find_mentions(q, patterns))}
    if ok:
        comp = body.get("completion") or ""
        rec.update(analyse_run(comp, brand, patterns))
        src = source_links(body)
        rec["source_counts"] = dict(collections.Counter(kd for kd, _, _ in src))
        rec["source_domains"] = sorted({domain(u) for _, u, _ in src if domain(u)})
        rec["sources"] = [{"kind": kd, "url": u, "title": t} for kd, u, t in src]
        rec["completion"] = comp
    else:
        rec["error"] = call.get("error")
    return rec


def reanalyse(cfg, raw_dir):
    """Rebuild runs from a previous run's raw/ folder (no API calls). The last attempt of each job wins."""
    brands = brand_map(cfg)
    brand = cfg["brand"]["name"]
    patterns = brand_patterns(brands)
    calls, jobs = [], collections.OrderedDict()
    for name in sorted(os.listdir(raw_dir)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(raw_dir, name)) as f:
            d = json.load(f)
        calls.append(d["call"])
        req = d["request"]["body"]
        variant = "main" if req.get("system_message") else "no_system_message"
        jobs[d["call"]["tag"]] = (req["prompt"], variant, d)
    runs, ab_runs, counter = [], [], collections.Counter()
    for tag, (q, variant, d) in jobs.items():
        counter[(q, variant)] += 1
        rec = make_record(q, counter[(q, variant)], variant, d["call"]["ok"], d["body"], d["call"], brand, patterns)
        (runs if variant == "main" else ab_runs).append(rec)
    return brands, runs, ab_runs, calls


def ab_rows(runs, ab_runs):
    rows = []
    for q in dict.fromkeys(r["question"] for r in ab_runs):
        for variant, src in (("with", runs), ("without", ab_runs)):
            rs = [r for r in src if r["question"] == q and r.get("ok")]
            rows.append({"question": q, "variant": variant,
                         "brands": "; ".join(", ".join(r["brands_named"]) or "(none)" for r in rs),
                         "chars": ", ".join(str(r["summary_chars"]) for r in rs),
                         "domains": ", ".join(str(len(r["cited_domains"])) for r in rs)})
    return rows


def write_outputs(out, meta, brands, runs, ab_runs, calls):
    md = render_markdown(meta, runs, calls, list(brands), ab_rows(runs, ab_runs) if ab_runs else None)
    with open(os.path.join(out, "answer-check.md"), "w") as f:
        f.write(md)
    with open(os.path.join(out, "runs.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["variant", "question", "run", "ok", "brand_named", "brand_position", "others_named",
                    "cited_domains", "unlinked_citations", "brand_sentence", "latency_s", "cost_usd"])
        for r in runs + ab_runs:
            w.writerow([r["variant"], r["question"], r["run"], r["ok"], r.get("brand_named"), r.get("brand_position"),
                        ";".join(r.get("others_named") or []), ";".join(r.get("cited_domains") or []),
                        r.get("unlinked_citations"), r.get("brand_sentence"), r["latency_s"], r["cost_usd"]])
    snap = {"meta": meta, "brands": brands, "share": share_table(runs, list(brands)),
            "consistency": consistency(runs), "top_cited_domains": top_domains(runs),
            "runs": runs, "ab_runs": ab_runs, "calls": calls, "cost": cost_summary(calls)}
    with open(os.path.join(out, "snapshot.json"), "w") as f:
        json.dump(snap, f, indent=1, ensure_ascii=False)
    return md, snap


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("config", help="JSON file with brand, competitors and questions (see examples/)")
    ap.add_argument("--runs", type=int, default=3, help="runs per question")
    ap.add_argument("--system-message", default=DEFAULT_SYSTEM_MESSAGE)
    ap.add_argument("--tools", default="web,twitter", help="AI Search tools, comma separated")
    ap.add_argument("--count", type=int, default=None, help="results per source (10-200); default is the API's 10")
    ap.add_argument("--date-filter", choices=DATE_FILTERS, default=None)
    ap.add_argument("--questions", type=int, default=None, help="only the first N questions")
    ap.add_argument("--ab", type=int, default=0, help="also ask the first N questions without the system message")
    ap.add_argument("--max-spend", type=float, default=0.50, help="stop calling once the run has cost this much (USD)")
    ap.add_argument("--out", default="runs")
    ap.add_argument("--no-raw", action="store_true", help="do not save raw responses")
    ap.add_argument("--reanalyse", metavar="RUN_DIR", help="re-score a previous run's saved answers with this config "
                    "(new brands or aliases); no API calls, no cost")
    a = ap.parse_args(argv)

    with open(a.config) as f:
        cfg = json.load(f)
    if a.questions:
        cfg["questions"] = cfg["questions"][:a.questions]
    if a.reanalyse:
        brands, runs, ab_runs, calls = reanalyse(cfg, os.path.join(a.reanalyse, "raw"))
        old = {}
        if os.path.exists(os.path.join(a.reanalyse, "snapshot.json")):
            with open(os.path.join(a.reanalyse, "snapshot.json")) as f:
                old = json.load(f).get("meta", {})
        meta = dict(old, brand=cfg["brand"]["name"], questions=list(dict.fromkeys(r["question"] for r in runs)))
        md, snap = write_outputs(a.reanalyse, meta, brands, runs, ab_runs, calls)
        print(md)
        print(f"re-scored {len(runs) + len(ab_runs)} saved answers in {a.reanalyse} (no API calls)", file=sys.stderr)
        return 0
    started = dt.datetime.now().astimezone()
    out = os.path.join(a.out, started.strftime("%Y%m%d-%H%M%S") + "-" + slug(cfg["brand"]["name"], 20))
    os.makedirs(out, exist_ok=True)
    client = Client(api_key(), raw_dir=None if a.no_raw else os.path.join(out, "raw"))
    tools = [t.strip() for t in a.tools.split(",") if t.strip()]
    brands, runs, ab_runs = run_check(cfg, client, a.runs, a.system_message, tools, a.count, a.date_filter,
                                      a.max_spend, a.ab, log=lambda m: print(m, file=sys.stderr))
    meta = {"brand": cfg["brand"]["name"], "questions": cfg["questions"], "runs": a.runs, "tools": tools,
            "system_message": a.system_message, "count": a.count, "date_filter": a.date_filter,
            "started": started.strftime("%Y-%m-%d %H:%M"), "endpoint": BASE + ENDPOINT}
    md, snap = write_outputs(out, meta, brands, runs, ab_runs, client.calls)
    print(md)
    cs = snap["cost"]
    print(f"cost: {cs['calls']} calls, {cs['units']} units, ${cs['total_usd']:.4f}; output: {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
