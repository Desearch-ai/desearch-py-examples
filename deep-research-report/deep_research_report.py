"""Deep Research Report: one research question in, a cited and dated report out.

Made by Desearch (https://desearch.ai).

The script splits a topic into a few sub-questions with a fixed template (no LLM), runs the
Desearch Search API (POST /search) once per sub-question with a published-date window, dedupes the
pages by URL and by near-identical title, and writes:
  report-<slug>-YYYY-MM-DD.md   findings per sub-question + a source table
  sources-<slug>-YYYY-MM-DD.csv one row per page (title, outlet, date, sub-questions, passage)
Every finding is one sentence copied exactly from the page text Desearch returned (from inside the
passage Desearch matched), followed by its link and the page's published date as returned. The
script does not write any sentence of its own about the topic.

Live:     python deep_research_report.py --topic "stablecoin adoption" --key-file ~/.desearch_api_key
Offline:  python deep_research_report.py --from-raw samples/sample-raw.json
Key: read only from a key file (--key-file PATH). Never from the environment.
"""
import argparse, csv, datetime as dt, json, os, re, sys, time
from urllib.parse import urlsplit

BASE = "https://api.desearch.ai"
DEFAULT_KEY_FILE = "~/.desearch_api_key"
USER_AGENT = "deep-research-report/1.0 (desearch-py-examples)"
# SUB_QUESTIONS: the fixed template. {topic} is replaced by --topic. Edit freely (4 to 6 work well).
SUB_QUESTIONS = [
    ("overview", "What is driving {topic}?"),
    ("latest", "Latest news and announcements on {topic}"),
    ("numbers", "{topic} data, statistics and market size"),
    ("players", "Companies and projects leading {topic}"),
    ("risks", "Risks, concerns and criticism of {topic}"),
]
FINDINGS_PER_QUESTION = 3
FIELDS = ["n", "title", "outlet", "published_date", "in_window", "sub_questions", "url", "quote", "quote_kind", "passage", "page_text_chars"]
STOP = set("a an and are as at be by for from has have how in is it its of on or that the this to was what were which who why will with".split())


def now():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def read_key(path):
    p = os.path.expanduser(path)
    if not os.path.isfile(p):
        raise SystemExit(f"key file not found: {p} (put your Desearch API key in it, one line)")
    k = open(p).read().strip()
    if not k:
        raise SystemExit(f"key file is empty: {p}")
    return k


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48] or "report"


def plan(topic, subs=None):
    if subs:
        return [(f"q{i + 1}", s) for i, s in enumerate(subs)]
    return [(tag, tpl.format(topic=topic)) for tag, tpl in SUB_QUESTIONS]


# ---------- live calls ----------
def search(session, tag, query, mode="balanced", count=20, start_date=None, end_date=None, page_text=True, highlights=True):
    """POST /search over REST (desearch-py 1.2.1 has no method for this endpoint)."""
    body = {"query": query, "mode": mode, "count": count, "highlights": highlights, "page_text": page_text}
    if start_date: body["start_date"] = start_date
    if end_date: body["end_date"] = end_date
    at, t0 = now(), time.time()
    try:
        r = session.post(BASE + "/search", json=body, timeout=120)
        status, hdr = r.status_code, {k.lower(): v for k, v in r.headers.items()}
        try: resp = r.json()
        except ValueError: resp = {"_text": r.text[:3000]}
    except Exception as e:
        status, hdr, resp = None, {}, {"_error": repr(e)[:500]}
    rec = {"tag": tag, "params": body, "at": at, "seconds": round(time.time() - t0, 2), "status": status,
           "cost_usd": hdr.get("x-desearch-cost-usd", resp.get("cost_usd") if isinstance(resp, dict) else None),
           "headers": {k: v for k, v in hdr.items() if k.startswith("x-desearch") or k == "date"},
           "header_names": sorted(hdr), "body": resp}
    print(f"{at} {tag:10s} {status} {rec['seconds']:6.2f}s results={len(results_of(rec))} cost={rec['cost_usd']}", file=sys.stderr, flush=True)
    return rec


def session_for(key):
    import requests
    s = requests.Session()
    s.headers.update({"Authorization": key, "User-Agent": USER_AGENT, "Content-Type": "application/json"})
    return s


def live(args):
    s = session_for(read_key(args.key_file))
    raw = {"started": now(), "topic": args.topic, "question": args.question or f"What is driving {args.topic}?",
           "start_date": args.start_date, "end_date": args.end_date, "mode": args.mode, "count": args.count, "calls": []}
    for tag, q in plan(args.topic, args.sub):
        raw["calls"].append(search(s, tag, q, args.mode, args.count, args.start_date, args.end_date, not args.no_page_text))
    return raw


# ---------- parsing ----------
def results_of(rec):
    b = rec.get("body")
    return b.get("results") or [] if isinstance(b, dict) else []


def norm_url(u):
    """Dedupe key: host without www, path without trailing slash; query strings (tracking, cache busters) dropped."""
    p = urlsplit((u or "").strip())
    if not p.netloc: return (u or "").strip()
    return f"{p.netloc.lower().removeprefix('www.')}{p.path.rstrip('/')}"


def outlet(u):
    return urlsplit(u or "").netloc.lower().removeprefix("www.")


def title_key(t):
    """Title without a trailing ' - Outlet' / ' | Outlet' part, as a set of lowercase words."""
    t = t or ""
    while True:  # strip trailing site-name parts, one at a time
        cut = re.sub(r"\s+[|\-\u2013\u2014\u00b7]\s+[^|\-\u2013\u2014\u00b7]{0,40}$", "", t)
        if cut == t or not cut.strip(): break
        t = cut
    return frozenset(w for w in re.findall(r"[a-z0-9]+", t.lower()) if w not in STOP)


def near_same(a, b):
    if not a or not b: return False
    if a == b: return True
    return min(len(a), len(b)) >= 4 and len(a & b) / len(a | b) >= 0.8


def parse_date(v):
    try: return dt.date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError): return None


def in_window(d, start, end):
    if d is None: return None
    return (start is None or d >= start) and (end is None or d <= end)


def words_of(s):
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if w not in STOP}


def squash(s):
    """Compare text with whitespace removed and ellipses folded, because highlights come back with
    the spaces after punctuation removed (see README)."""
    return re.sub(r"\s+", "", s or "").replace("\u2026", ".").replace("...", ".")


ABBREV = re.compile(r"(?:\b(?:Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|Mr|Mrs|Ms|Dr|St|Inc|Corp|Ltd|Co|vs|No|U\.S|U\.K|e\.g|i\.e)|\b[A-Z])\.$")


def sentences(text):
    """Sentences of a text, unedited. Splits after . ! ? when the next part starts like a sentence,
    but not after common abbreviations (Oct., U.S., Inc.)."""
    for line in re.split(r"\n+", text or ""):
        parts, buf = [], ""
        for piece in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\u201c\"'])", line):
            buf = f"{buf} {piece}" if buf else piece
            if not ABBREV.search(buf):
                parts.append(buf); buf = ""
        if buf: parts.append(buf)
        for part in parts:
            part = part.strip()
            if 40 <= len(part) <= 400:
                yield part


def pick_quote(r, query):
    """The sentence to quote for a page, copied exactly from the returned text.
    1. a page_text sentence that lies inside the matched passage (highlight), best overlap with the sub-question
    2. otherwise the page_text sentence with the best overlap
    3. otherwise the best sentence of the highlight itself, as returned"""
    want = words_of(query)
    hl = next((h for h in (r.get("highlights") or []) if isinstance(h, str) and h.strip()), "")
    hs = squash(hl)
    best = {}
    for kind, text, inside in (("page text, inside matched passage", r.get("page_text"), True),
                               ("page text", r.get("page_text"), False), ("highlight as returned", hl, False)):
        for snt in sentences(text):
            if inside and (not hs or squash(snt) not in hs): continue
            sc = len(want & words_of(snt)) + (0.5 if re.search(r"[.!?][\u201d\"']?$", snt) else 0)  # prefer full sentences
            if kind not in best or sc > best[kind][0]: best[kind] = (sc, snt)
        if kind in best and best[kind][0] > 0:
            return best[kind][1], kind
    return None, None


def build(raw, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    start, end = parse_date(raw.get("start_date")), parse_date(raw.get("end_date"))
    day = (raw.get("started") or now())[:10]
    slug = slugify(raw.get("topic") or raw.get("question") or "report")
    sources, by_url, findings, used = [], {}, [], set()
    st = {"calls": 0, "cost_usd": 0.0, "returned": 0, "dup_url": 0, "dup_title": 0, "undated": 0, "out_of_window": 0,
          "no_passage": 0, "page_text_chars": 0, "quote_kinds": {}}
    for rec in raw["calls"]:
        if rec.get("probe"): continue
        st["calls"] += 1
        try: st["cost_usd"] += float(rec.get("cost_usd") or 0)
        except (TypeError, ValueError): pass
        q = rec["params"]["query"]
        picked, cands = [], []
        for r in results_of(rec):
            st["returned"] += 1
            url = r.get("url") or ""
            key = norm_url(url)
            d = parse_date(r.get("published_date"))
            win = in_window(d, start, end)
            if d is None: st["undated"] += 1
            elif not win: st["out_of_window"] += 1
            pt = r.get("page_text")
            st["page_text_chars"] += len(pt) if isinstance(pt, str) else int(r.get("page_text_chars") or 0)
            src = by_url.get(key)
            if src is None:
                tk = title_key(r.get("title"))
                twin = next((s for s in sources if near_same(tk, s["_tk"])), None)
                if twin is not None:
                    st["dup_title"] += 1
                    twin.setdefault("_also", []).append(url)
                    if rec["tag"] not in twin["sub_questions"]: twin["sub_questions"].append(rec["tag"])
                    by_url[key] = twin
                    continue
                quote_, how = pick_quote(r, q)
                hl = next((h for h in (r.get("highlights") or []) if isinstance(h, str)), "")
                if not quote_: st["no_passage"] += 1
                st["quote_kinds"][how or "none"] = st["quote_kinds"].get(how or "none", 0) + 1
                src = {"n": len(sources) + 1, "title": r.get("title") or "", "outlet": outlet(url),
                       "published_date": d.isoformat() if d else "", "in_window": win, "sub_questions": [rec["tag"]],
                       "url": url, "quote": quote_ or "", "quote_kind": how or "", "passage": hl,
                       "page_text_chars": len(pt) if isinstance(pt, str) else r.get("page_text_chars") or 0, "_tk": tk}
                sources.append(src); by_url[key] = src
            else:
                st["dup_url"] += 1
                if rec["tag"] not in src["sub_questions"]: src["sub_questions"].append(rec["tag"])
            if src["quote"] and src["in_window"] and src not in cands:  # a finding needs a quote and an in-window date
                cands.append(src)
        # up to N findings per sub-question, one per outlet, preferring sources not quoted for an earlier sub-question
        for fresh in (True, False):
            for src in cands:
                if (len(picked) < FINDINGS_PER_QUESTION and src not in picked and (src["n"] not in used) == fresh
                        and src["outlet"] not in {p["outlet"] for p in picked}):
                    picked.append(src)
        used.update(p["n"] for p in picked)
        findings.append((rec["tag"], q, picked))
    st["cost_usd"] = round(st["cost_usd"], 6)
    st["sources"] = len(sources)
    csv_path = os.path.join(out_dir, f"sources-{slug}-{day}.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, FIELDS); w.writeheader()
        for s in sources:
            w.writerow({k: ("; ".join(s[k]) if k == "sub_questions" else s[k]) for k in FIELDS})
    md_path = os.path.join(out_dir, f"report-{slug}-{day}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render(raw, findings, sources, st))
    return sources, findings, st, csv_path, md_path


def quote(text):
    return "\n".join("> " + line if line.strip() else ">" for line in text.splitlines())


def cell(s):
    return (s or "").replace("|", "\\|").replace("\n", " ")


def render(raw, findings, sources, st):
    win = f"{raw.get('start_date') or 'any'} to {raw.get('end_date') or 'any'}"
    L = [f"# Research report: {raw.get('question') or raw.get('topic')}", "",
         "Made by [Desearch](https://desearch.ai).", "",
         f"A cited research report built from pages Desearch returned on {(raw.get('started') or '')[:10]} for "
         f"{st['calls']} searches (published-date window {win}). It is not complete research: it shows what these searches found.", "",
         "How it was built: each sub-question below was sent to the Desearch Search API. Each finding is one sentence copied "
         "exactly from the page text Desearch returned, taken from inside the passage Desearch matched to the sub-question, "
         "followed by its link and the page's published date as returned. "
         "Only dated pages inside the window are used as findings, at most one per outlet per sub-question, "
         "and a page already quoted for an earlier sub-question is used again only when no other page fits. "
         "The script adds no claims of its own.", ""]
    for i, (tag, q, picked) in enumerate(findings, 1):
        L += [f"## {i}. {q[:1].upper() + q[1:]}", ""]
        if not picked:
            L += ["No dated page inside the window with a matching passage came back for this sub-question.", ""]
        for s in picked:
            L += [quote(s["quote"]), "", f"Source [{s['n']}]: [{cell(s['title'])}]({s['url']}), {s['outlet']}, published {s['published_date']}", ""]
    L += ["## Sources", "", "| # | Title | Outlet | Published | In window | Sub-questions |", "|---|---|---|---|---|---|"]
    for s in sources:
        iw = "no date" if s["in_window"] is None else ("yes" if s["in_window"] else "no")
        L.append(f"| {s['n']} | [{cell(s['title'])}]({s['url']}) | {s['outlet']} | {s['published_date'] or 'no date'} | {iw} | {', '.join(s['sub_questions'])} |")
    L += ["", "The quoted sentence and the full matched passage for every source are in the sources CSV.", "",
          "## Run", "",
          f"- Searches: {st['calls']} (mode {raw.get('mode')}, {raw.get('count')} results each)",
          f"- Pages returned: {st['returned']}; unique sources after dedupe: {st['sources']} "
          f"({st['dup_url']} repeated links, {st['dup_title']} near-identical titles merged)",
          f"- Pages with no published date: {st['undated']}; dated outside the window: {st['out_of_window']}",
          f"- Quotes taken from: " + ", ".join(f"{k} {v}" for k, v in sorted(st["quote_kinds"].items())),
          f"- Cost reported by the API: ${st['cost_usd']}", ""]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--topic", default="stablecoin adoption", help="topic used in the sub-question template")
    ap.add_argument("--question", help="heading for the report (default: 'What is driving <topic>?')")
    ap.add_argument("--sub", action="append", help="your own sub-question (repeat 4 to 6 times); replaces the template")
    today = dt.date.today()
    ap.add_argument("--start-date", default=(today - dt.timedelta(days=30)).isoformat(), help="YYYY-MM-DD (default 30 days ago)")
    ap.add_argument("--end-date", default=today.isoformat(), help="YYYY-MM-DD (default today)")
    ap.add_argument("--mode", choices=["fast", "balanced"], default="balanced")
    ap.add_argument("--count", type=int, choices=[10, 15, 20], default=20)
    ap.add_argument("--no-page-text", action="store_true", help="do not ask for full page text")
    ap.add_argument("--key-file", default=DEFAULT_KEY_FILE)
    ap.add_argument("--from-raw", help="rebuild the report from a saved raw JSON, no API calls")
    ap.add_argument("--raw-out", help="where to save the raw responses (default <out>/raw-<date>.json)")
    ap.add_argument("--out", default="output")
    a = ap.parse_args(argv)
    if a.from_raw:
        with open(a.from_raw, encoding="utf-8") as f:
            raw = json.load(f)
    else:
        raw = live(a)
        os.makedirs(a.out, exist_ok=True)
        rp = a.raw_out or os.path.join(a.out, f"raw-{raw['started'][:10]}.json")
        with open(rp, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=1, ensure_ascii=False)
        print(f"raw saved: {rp}", file=sys.stderr)
    sources, findings, st, c, m = build(raw, a.out)
    n = sum(len(p) for _, _, p in findings)
    print(f"{n} findings from {st['sources']} sources, {st['calls']} searches, ${st['cost_usd']} reported -> {m}, {c}")


if __name__ == "__main__":
    main()
