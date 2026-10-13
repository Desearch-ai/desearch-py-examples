#!/usr/bin/env python3
"""RAG Corpus Builder: a topic and 3-5 sub-questions in, a starter corpus from pages Desearch found out.

Pipeline
  1. POST /desearch/ai/search/links/web  {"prompt", "tools": ["web"], "count"}   ranked links per sub-question
  2. normalise + dedupe URLs (within and across sub-questions), cap pages per domain and in total
  3. GET /web/extract?url=...&format=html&js=false   (one retry on an empty page, both tries logged)
  4. HTML -> heading-aware blocks -> chunks  ->  corpus.jsonl (source_url, title, heading_path on every row)
  5. sources.csv, run-report.md, snapshot.json, calls.jsonl (key redacted)

Base https://api.desearch.ai, header "Authorization: <key>". Cost is read from the X-Desearch-Cost-Usd header.
"""
import argparse, csv, concurrent.futures as cf, datetime as dt, hashlib, json, os, re, sys, time, threading
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

BASE = "https://api.desearch.ai"
LINKS_PATH = "/desearch/ai/search/links/web"
EXTRACT_PATH = "/web/extract"
TRACKING_PARAMS = re.compile(r"^(utm_.*|gclid|fbclid|msclkid|mc_cid|mc_eid|ref|ref_src|_ga|igshid|srsltid)$", re.I)
EMPTY_MIN_CHARS = 200          # parsed text shorter than this counts as an empty page


# ---------------------------------------------------------------- key

def api_key():
    """Key from the file named by DESEARCH_API_KEY_FILE, else DESEARCH_API_KEY. Never printed or saved."""
    path = os.environ.get("DESEARCH_API_KEY_FILE")
    k = ""
    if path:
        with open(os.path.expanduser(path)) as f:
            k = f.read().strip()
    if not k:
        k = os.environ.get("DESEARCH_API_KEY", "").strip()
    if not k:
        sys.exit("Set DESEARCH_API_KEY_FILE (path to a file holding your key) or DESEARCH_API_KEY. Get a key at console.desearch.ai")
    return k


# ---------------------------------------------------------------- URLs

def normalise_url(url):
    """Canonical form for dedupe: https, lowercase host without www, no fragment, no tracking params,
    sorted query, no trailing slash (except root), no default port, no index.html."""
    try:
        p = urlparse((url or "").strip())
    except ValueError:
        return ""
    if p.scheme not in ("http", "https") or not p.hostname:
        return ""
    host = p.hostname.lower()
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m.") and host.count(".") >= 2:
        host = host[2:]
    path = re.sub(r"/{2,}", "/", p.path or "/")
    path = re.sub(r"/(index|default)\.(html?|php|aspx?)$", "/", path, flags=re.I)
    if len(path) > 1:
        path = path.rstrip("/")
    q = sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not TRACKING_PARAMS.match(k))
    return urlunparse(("https", host, path, "", urlencode(q), ""))


def domain(url):
    h = (urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def dedupe(link_lists):
    """link_lists: [(sq_index, [ {link,title,snippet}, ...ranked ]), ...]
    Returns (unique, stats). unique: list of dicts keyed by normalised URL, first sighting wins, with every
    (sub-question, rank) where it appeared. stats: within / across duplicate counts."""
    seen, order = {}, []
    within = 0
    total = 0
    for sq, items in link_lists:
        local = set()
        for rank, it in enumerate(items, 1):
            raw = it.get("link") or it.get("url") or ""
            n = normalise_url(raw)
            if not n:
                continue
            total += 1
            if n in local:
                within += 1
                continue
            local.add(n)
            if n in seen:
                seen[n]["hits"].append((sq, rank))
            else:
                seen[n] = {"url": raw, "norm": n, "domain": domain(n), "title": it.get("title") or "",
                           "snippet": it.get("snippet") or "", "sq": sq, "rank": rank, "hits": [(sq, rank)]}
                order.append(n)
    unique = [seen[n] for n in order]
    after_within = total - within
    across = after_within - len(unique)
    stats = {"links_total": total, "dup_within": within, "dup_across": across, "unique": len(unique),
             "dup_rate": round((total - len(unique)) / total, 4) if total else 0.0}
    return unique, stats


STOPWORDS = {"home", "what", "which", "when", "where", "does", "with", "from", "your", "that", "this", "have", "many",
             "much", "long", "need", "needs", "best", "guide", "about", "into", "they", "them", "last", "work", "works",
             "period", "cost", "should", "would", "could", "there", "their", "than", "then", "more", "most", "vs"}
SHORT_TERMS = {"lfp", "nmc", "kwh", "llm", "gpu", "api", "sql", "css", "rag"}


def topic_stems(*texts):
    """5-letter stems of the content words in the topic and sub-question (short technical terms kept whole)."""
    out = set()
    for t in texts:
        for w in re.findall(r"[a-z0-9]+", (t or "").lower()):
            if (len(w) >= 4 or w in SHORT_TERMS) and w not in STOPWORDS:
                out.add(w[:5])
    return out


def looks_on_topic(item, stems):
    """Cheap relevance gate on title + URL: at least one stem starts a word. Built after the links endpoint padded
    long result lists with generic pages (see report.md); checked on one topic only, so it can be switched off."""
    if not stems:
        return True
    hay = ((item.get("title") or "") + " " + (item.get("url") or item.get("link") or "")).lower()
    return any(re.search(r"(?<![a-z0-9])" + re.escape(s), hay) for s in stems)


def select_pages(unique, max_pages, max_per_domain):
    """Round-robin over sub-questions by rank, so each sub-question gets pages; cap per domain and in total.
    Returns (selected, skipped) where skipped items carry a 'skip' reason."""
    by_sq = {}
    for u in unique:
        by_sq.setdefault(u["sq"], []).append(u)
    for lst in by_sq.values():
        lst.sort(key=lambda u: u["rank"])
    queues = [by_sq[k] for k in sorted(by_sq)]
    selected, skipped, per_dom = [], [], {}
    i = 0
    while any(queues):
        q = queues[i % len(queues)]
        i += 1
        if not q:
            continue
        u = q.pop(0)
        if per_dom.get(u["domain"], 0) >= max_per_domain:
            skipped.append(dict(u, skip="domain_cap"))
        elif len(selected) >= max_pages:
            skipped.append(dict(u, skip="max_pages"))
        else:
            per_dom[u["domain"]] = per_dom.get(u["domain"], 0) + 1
            selected.append(u)
    return selected, skipped


# ---------------------------------------------------------------- HTML -> heading-aware blocks

DROP_TAGS = ["script", "style", "noscript", "svg", "nav", "header", "footer", "aside", "form", "iframe",
             "button", "select", "template", "dialog"]
BOILER_RE = re.compile(r"(cookie|consent|newsletter|subscribe|breadcrumb|share|social|related|sidebar|menu|"
                       r"advert|promo|popup|modal|banner|comment)", re.I)
BLOCK_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "blockquote", "td", "th", "dd", "dt", "figcaption"]


def _clean(t):
    return re.sub(r"\s+", " ", t or "").strip()


def html_to_blocks(html):
    """Returns (title, blocks). blocks = [{"heading_path": [...], "text": str, "kind": "p"|"li"|"pre"...}].
    Uses <article> or <main> when it holds most of the text, drops nav/header/footer/scripts and elements
    whose class or id looks like boilerplate."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html or "", "html.parser")
    title = _clean(soup.title.get_text()) if soup.title else ""
    for t in soup(DROP_TAGS):
        t.decompose()
    for t in soup.find_all(True):
        if t.attrs is None:
            continue
        attrs = " ".join([" ".join(t.get("class") or []), t.get("id") or "", t.get("role") or ""])
        if t.name not in ("body", "html", "main", "article") and attrs.strip() and BOILER_RE.search(attrs):
            if len(_clean(t.get_text())) < 2000:      # don't drop a whole wrapper that happens to say "menu"
                t.decompose()
    root = soup.body or soup
    for cand in (soup.find("article"), soup.find("main"), soup.find(attrs={"role": "main"})):
        if cand is not None and len(_clean(cand.get_text())) >= 0.4 * max(1, len(_clean(root.get_text()))):
            root = cand
            break
    blocks, path = [], []
    for el in root.find_all(BLOCK_TAGS):
        if el.find_parent(["li", "pre", "blockquote", "td"]) is not None and el.name not in ("pre",):
            if el.find_parent("pre") is not None or el.name in ("p", "li"):
                continue                                   # nested: parent block already carries the text
        if el.name[0] == "h" and el.name[1:].isdigit():
            lvl = int(el.name[1])
            text = _clean(el.get_text(" "))
            if not text:
                continue
            path = [h for h in path if h[0] < lvl] + [(lvl, text[:200])]
            continue
        text = el.get_text("\n") if el.name == "pre" else _clean(el.get_text(" "))
        if el.name != "pre" and len(text) < 3:
            continue
        blocks.append({"heading_path": [h[1] for h in path], "text": text.strip(), "kind": el.name})
    if not blocks:                                          # pages built from bare <div>s: fall back to text lines
        for line in root.get_text("\n").splitlines():
            line = _clean(line)
            if len(line) >= 40:
                blocks.append({"heading_path": [], "text": line, "kind": "div"})
    return title, blocks


def text_to_blocks(text):
    """Fallback for format=text: blank-line paragraphs; a short line without end punctuation followed by a
    paragraph is treated as a heading (format=text carries no heading markers)."""
    paras = [_clean(p) for p in re.split(r"\n\s*\n|\n", text or "") if _clean(p)]
    blocks, path = [], []
    for i, p in enumerate(paras):
        nxt = paras[i + 1] if i + 1 < len(paras) else ""
        if len(p) <= 80 and not re.search(r"[.!?:;,]$", p) and len(nxt) > 120:
            path = [p]
            continue
        if len(p) >= 40:
            blocks.append({"heading_path": list(path), "text": p, "kind": "p"})
    return blocks


def _split_long(text, max_chars):
    if len(text) <= max_chars:
        return [text]
    out, cur = [], ""
    for s in re.split(r"(?<=[.!?])\s+", text):
        while len(s) > max_chars:                          # one huge "sentence": hard split
            if cur:
                out.append(cur); cur = ""
            out.append(s[:max_chars]); s = s[max_chars:]
        if len(cur) + len(s) + 1 > max_chars and cur:
            out.append(cur); cur = s
        else:
            cur = (cur + " " + s).strip()
    if cur:
        out.append(cur)
    return out


def chunk_blocks(blocks, max_chars=1200, min_chars=200):
    """Group consecutive blocks under the same heading path into chunks of up to max_chars. A chunk never
    spans two heading paths. Chunks shorter than min_chars are merged into the previous chunk of the same
    path, or dropped when they stand alone and are shorter than 40 chars."""
    chunks = []
    cur_path, cur = None, []

    def flush():
        if not cur:
            return
        text = "\n".join(cur).strip()
        for piece in _split_long(text, max_chars):
            if chunks and chunks[-1]["heading_path"] == cur_path and len(piece) < min_chars \
                    and len(chunks[-1]["text"]) + len(piece) + 1 <= max_chars + min_chars:
                chunks[-1]["text"] += "\n" + piece
            elif len(piece) >= 40:
                chunks.append({"heading_path": list(cur_path), "text": piece})

    for b in blocks:
        if b["heading_path"] != cur_path:
            flush(); cur, cur_path = [], b["heading_path"]
        t = b["text"] if b.get("kind") != "li" else "- " + b["text"]
        if cur and sum(len(x) + 1 for x in cur) + len(t) > max_chars:
            flush(); cur = []
        cur.append(t)
    flush()
    return chunks


def sha(text):
    return hashlib.sha256(re.sub(r"\s+", " ", text).strip().lower().encode()).hexdigest()


def is_empty_page(status, text_chars):
    return status != 200 or text_chars < EMPTY_MIN_CHARS


# ---------------------------------------------------------------- client

class Client:
    def __init__(self, key, outdir, max_spend, session=None, timeout=90):
        import requests
        self.key, self.outdir, self.max_spend, self.timeout = key, outdir, max_spend, timeout
        self.s = session or requests.Session()
        self.spent, self.calls, self.lock = 0.0, [], threading.Lock()
        self.log = open(os.path.join(outdir, "calls.jsonl"), "a")

    def _safe_write(self, path, text):
        if self.key and self.key in text:
            raise RuntimeError("refusing to write a file that contains the API key")
        with open(path, "w") as f:
            f.write(text)

    def request(self, kind, method, path, params=None, body=None, raw_name=None, save_body=True):
        if self.spent >= self.max_spend:
            raise BudgetExceeded(f"spent ${self.spent:.4f} >= --max-spend ${self.max_spend}")
        t0 = time.time()
        at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        err, r = None, None
        try:
            r = self.s.request(method, BASE + path, params=params, json=body,
                               headers={"Authorization": self.key}, timeout=self.timeout)
            status = r.status_code
        except Exception as e:                                      # network error / timeout
            status, err = 0, type(e).__name__ + ": " + str(e)[:200]
        lat = round(time.time() - t0, 2)
        h = {k.lower(): v for k, v in (r.headers.items() if r is not None else [])}
        cost = float(h.get("x-desearch-cost-usd") or 0)
        units = int(float(h.get("x-desearch-usage-count") or 0))
        ctype = h.get("content-type", "")
        data, text = None, ""
        if r is not None:
            if "json" in ctype:
                try:
                    data = r.json()
                except ValueError:
                    text = r.text
            else:
                text = r.text
        rec = {"at": at, "kind": kind, "method": method, "path": path, "params": params, "json": body,
               "status": status, "latency_s": lat, "cost_usd": cost, "usage_count": units,
               "service": h.get("x-desearch-service", ""), "content_type": ctype,
               "body_chars": len(text) if text else len(json.dumps(data)) if data is not None else 0,
               "detail": (data or {}).get("detail") if isinstance(data, dict) else None, "error": err,
               "raw": raw_name}
        with self.lock:
            self.spent += cost
            self.calls.append(rec)
            self.log.write(json.dumps(rec, ensure_ascii=False) + "\n"); self.log.flush()
        if raw_name and save_body:
            full = dict(rec, request_headers={"Authorization": "<redacted>"},
                        response_headers={k: v for k, v in h.items() if k.startswith("x-desearch") or k == "content-type"},
                        response=data if data is not None else text)
            self._safe_write(os.path.join(self.outdir, "raw", raw_name), json.dumps(full, indent=1, ensure_ascii=False))
        return rec, data, text

    def links(self, prompt, count, raw_name):
        rec, data, _ = self.request("links", "POST", LINKS_PATH,
                                    body={"prompt": prompt, "tools": ["web"], "count": count}, raw_name=raw_name)
        items = (data or {}).get("search_results") or [] if isinstance(data, dict) else []
        rec["returned"] = len(items)
        return rec, items

    def extract(self, url, fmt, raw_name):
        rec, data, text = self.request("extract", "GET", EXTRACT_PATH,
                                       params={"url": url, "format": fmt, "js": "false"}, raw_name=raw_name)
        return rec, text if rec["status"] == 200 else ""


class BudgetExceeded(Exception):
    pass


# ---------------------------------------------------------------- pipeline

def slug(s, n=40):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:n]


def page_from_body(body, fmt):
    if fmt == "html":
        title, blocks = html_to_blocks(body)
    else:
        title, blocks = "", text_to_blocks(body)
    return title, blocks


def run(cfg, args, client, outdir):
    started = dt.datetime.now().astimezone()
    topic, sqs = cfg["topic"], cfg["sub_questions"]
    link_lists, link_calls = [], []
    for i, sq in enumerate(sqs):
        q = sq if isinstance(sq, str) else sq["q"]
        count = args.count if isinstance(sq, str) else int(sq.get("count", args.count))
        prompt = f"{topic}: {q}" if args.prefix_topic else q
        rec, items = client.links(prompt, count, f"links-{i+1:02d}-{slug(q)}.json")
        rec.update({"sq": i, "sub_question": q, "requested": count})
        link_calls.append(rec)
        link_lists.append((i, items))
        print(f"[links] sq{i+1} count={count} -> {rec['status']} returned={rec['returned']} "
              f"units={rec['usage_count']} ${rec['cost_usd']} {rec['latency_s']}s", file=sys.stderr)
    unique, dstats = dedupe(link_lists)
    # per sub-question within-dup counts for the report
    per_sq = []
    for (i, items), rec in zip(link_lists, link_calls):
        norms = [normalise_url(it.get("link") or "") for it in items]
        norms = [n for n in norms if n]
        per_sq.append({"sq": i, "returned": len(items), "unique_within": len(set(norms)),
                       "dup_within": len(norms) - len(set(norms))})
    filtered_out = []
    if getattr(args, "topic_filter", True):
        keep = []
        for u in unique:
            st = topic_stems(topic, sq_text(sqs[u["sq"]]))
            (keep if looks_on_topic(u, st) else filtered_out).append(u)
        unique_sel = keep
    else:
        unique_sel = unique
    selected, skipped = select_pages(unique_sel, args.max_pages, args.max_per_domain)
    skipped += [dict(u, skip="topic_filter") for u in filtered_out]
    print(f"[dedupe] {dstats} -> topic filter dropped {len(filtered_out)}, selected {len(selected)} pages", file=sys.stderr)

    pages = {}

    def work(idx_u):
        idx, u = idx_u
        tries = []
        body = ""
        for t in (1, 2) if args.retry else (1,):
            try:
                rec, body = client.extract(u["url"], args.format, f"extract-{idx:03d}-try{t}.json" if args.save_pages else None)
            except BudgetExceeded as e:
                tries.append({"try": t, "status": "budget", "detail": str(e)}); body = ""; break
            title, blocks = page_from_body(body, args.format) if body else ("", [])
            chars = sum(len(b["text"]) for b in blocks)
            tries.append({"try": t, "at": rec["at"], "status": rec["status"], "detail": rec["detail"],
                          "error": rec["error"], "cost_usd": rec["cost_usd"], "latency_s": rec["latency_s"],
                          "body_chars": rec["body_chars"], "text_chars": chars})
            if not is_empty_page(rec["status"], chars):
                return idx, {"u": u, "tries": tries, "title": title or u["title"], "blocks": blocks}
        return idx, {"u": u, "tries": tries, "title": u["title"], "blocks": []}

    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for idx, res in ex.map(work, list(enumerate(selected, 1))):
            pages[idx] = res
            t = res["tries"][-1]
            print(f"[extract] {idx:03d} tries={len(res['tries'])} status={t['status']} chars={t.get('text_chars')} "
                  f"{res['u']['domain']}", file=sys.stderr)

    # chunks, page-level and chunk-level near-dup removal
    fetched_at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    seen_page, seen_chunk = {}, set()
    rows, sources = [], []
    for idx in sorted(pages):
        p = pages[idx]; u = p["u"]
        status = "kept"
        n_chunks = 0
        text_all = "\n".join(b["text"] for b in p["blocks"])
        if not p["blocks"] or is_empty_page(200, len(text_all)):
            status = "empty"
        else:
            h = sha(text_all)
            if h in seen_page:
                status = "duplicate_content"
            else:
                seen_page[h] = idx
                for c in chunk_blocks(p["blocks"], args.chunk_chars):
                    ch = sha(c["text"])
                    if ch in seen_chunk:
                        continue                              # boilerplate repeated across pages
                    seen_chunk.add(ch)
                    rows.append({"id": f"p{idx:03d}-c{n_chunks:03d}", "source_url": u["url"], "domain": u["domain"],
                                 "title": p["title"], "heading_path": c["heading_path"],
                                 "heading": " > ".join(c["heading_path"]), "chunk_index": n_chunks,
                                 "text": c["text"], "n_chars": len(c["text"]), "sha256": ch,
                                 "topic": topic, "sub_question": sq_text(sqs[u["sq"]]), "search_rank": u["rank"],
                                 "fetched_at": fetched_at})
                    n_chunks += 1
                if n_chunks == 0:
                    status = "empty"
        t1, t2 = p["tries"][0], (p["tries"][1] if len(p["tries"]) > 1 else {})
        sources.append({"page": idx, "status": status, "source_url": u["url"], "normalised_url": u["norm"],
                        "domain": u["domain"], "title": p["title"], "sub_questions": ";".join(str(s + 1) for s, _ in u["hits"]),
                        "best_rank": u["rank"], "try1_status": t1.get("status"), "try1_detail": t1.get("detail") or t1.get("error") or "",
                        "try1_text_chars": t1.get("text_chars"), "try2_status": t2.get("status", ""),
                        "try2_detail": t2.get("detail") or t2.get("error") or "", "try2_text_chars": t2.get("text_chars", ""),
                        "extract_cost_usd": round(sum(t.get("cost_usd") or 0 for t in p["tries"]), 6),
                        "chunks": n_chunks})
    for s in skipped:
        sources.append({"page": "", "status": "skipped_" + s["skip"], "source_url": s["url"], "normalised_url": s["norm"],
                        "domain": s["domain"], "title": s["title"], "sub_questions": ";".join(str(x + 1) for x, _ in s["hits"]),
                        "best_rank": s["rank"], "try1_status": "", "try1_detail": "", "try1_text_chars": "",
                        "try2_status": "", "try2_detail": "", "try2_text_chars": "", "extract_cost_usd": 0, "chunks": 0})

    with open(os.path.join(outdir, "corpus.jsonl"), "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(outdir, "sources.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(sources[0].keys()) if sources else ["page"])
        w.writeheader(); w.writerows(sources)
    summary = summarise(cfg, args, started, link_calls, per_sq, dstats, pages, sources, rows, client)
    summary["topic_filter_dropped"] = len(filtered_out)
    client._safe_write(os.path.join(outdir, "snapshot.json"), json.dumps(
        {"summary": summary, "link_calls": link_calls, "unique_links": unique}, indent=1, ensure_ascii=False))
    client._safe_write(os.path.join(outdir, "run-report.md"), render_report(summary))
    return summary


def sq_text(sq):
    return sq if isinstance(sq, str) else sq["q"]


def summarise(cfg, args, started, link_calls, per_sq, dstats, pages, sources, rows, client):
    ex_calls = [c for c in client.calls if c["kind"] == "extract"]
    first = [p["tries"][0] for p in pages.values()]
    retried = [p for p in pages.values() if len(p["tries"]) > 1]
    rec2 = [p for p in retried if not is_empty_page(p["tries"][1]["status"], p["tries"][1].get("text_chars") or 0)]
    empty_final = [s for s in sources if s["status"] == "empty"]
    kept = [s for s in sources if s["status"] == "kept"]
    det = {}
    for t in first:
        if is_empty_page(t["status"], t.get("text_chars") or 0):
            k = f"{t['status']} {t.get('detail') or ('short text' if t['status'] == 200 else t.get('error') or '')}".strip()
            det[k] = det.get(k, 0) + 1
    link_cost = sum(c["cost_usd"] for c in link_calls)
    ex_cost = sum(c["cost_usd"] for c in ex_calls)
    billed_pages = sum(1 for c in ex_calls if c["cost_usd"] > 0)
    lat = sorted(c["latency_s"] for c in ex_calls)
    llat = sorted(c["latency_s"] for c in link_calls)
    med = lambda xs: xs[len(xs) // 2] if xs else None
    return {
        "topic": cfg["topic"], "sub_questions": [sq_text(s) for s in cfg["sub_questions"]],
        "started": started.isoformat(timespec="seconds"),
        "finished": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "settings": {"count": args.count, "max_pages": args.max_pages, "max_per_domain": args.max_per_domain,
                     "format": args.format, "js": "false", "retry": args.retry, "chunk_chars": args.chunk_chars,
                     "topic_filter": getattr(args, "topic_filter", True)},
        "links": [{"sq": c["sq"] + 1, "requested": c["requested"], "returned": c["returned"], "status": c["status"],
                   "usage_count": c["usage_count"], "cost_usd": c["cost_usd"], "latency_s": c["latency_s"]} for c in link_calls],
        "per_sq": per_sq, "dedupe": dstats,
        "pages_selected": len(pages), "pages_kept": len(kept), "pages_empty": len(empty_final),
        "pages_duplicate_content": sum(1 for s in sources if s["status"] == "duplicate_content"),
        "empty_try1": sum(1 for t in first if is_empty_page(t["status"], t.get("text_chars") or 0)),
        "empty_try1_reasons": det, "retried": len(retried), "recovered_on_retry": len(rec2),
        "chunks": len(rows), "chunk_chars_median": med(sorted(r["n_chars"] for r in rows)),
        "chunks_with_heading": sum(1 for r in rows if r["heading_path"]),
        "extract_calls": len(ex_calls), "extract_billed_calls": billed_pages,
        "cost": {"links_usd": round(link_cost, 6), "extract_usd": round(ex_cost, 6), "total_usd": round(link_cost + ex_cost, 6),
                 "extract_usd_per_billed_call": round(ex_cost / billed_pages, 6) if billed_pages else None,
                 "usd_per_kept_page": round((link_cost + ex_cost) / len(kept), 6) if kept else None},
        "latency_s": {"links_median": med(llat), "links_max": llat[-1] if llat else None,
                      "extract_median": med(lat), "extract_max": lat[-1] if lat else None},
        "errors": sum(1 for c in client.calls if c["status"] not in (200, 404)),
    }


def render_report(s):
    L = [f"# Corpus run: {s['topic']}", "", f"Started {s['started']}, finished {s['finished']}.", "",
         "## Links", "", "| Sub-question | Requested | Returned | Billed units | Cost (USD) | Latency (s) |", "|---|---|---|---|---|---|"]
    for l, q in zip(s["links"], s["sub_questions"]):
        L.append(f"| {l['sq']}. {q} | {l['requested']} | {l['returned']} | {l['usage_count']} | {l['cost_usd']} | {l['latency_s']} |")
    d = s["dedupe"]
    L += ["", f"Links: {d['links_total']}, duplicates within a sub-question: {d['dup_within']}, across sub-questions: "
              f"{d['dup_across']}, unique: {d['unique']} (duplicate rate {d['dup_rate']:.1%}).", "",
          f"Topic filter (title + URL must share a word stem with the topic or sub-question): "
          f"{'on' if s['settings']['topic_filter'] else 'off'}, dropped {s.get('topic_filter_dropped', 0)} links.", "",
          "## Pages", "",
          f"Selected {s['pages_selected']} (max {s['settings']['max_pages']}, max {s['settings']['max_per_domain']} per domain). "
          f"Kept {s['pages_kept']}, empty after retry {s['pages_empty']}, duplicate content {s['pages_duplicate_content']}.", "",
          f"Empty on the first try: {s['empty_try1']} of {s['pages_selected']}; recovered on retry: {s['recovered_on_retry']} of {s['retried']}.", ""]
    for k, v in sorted(s["empty_try1_reasons"].items(), key=lambda kv: -kv[1]):
        L.append(f"- first-try empty, `{k}`: {v}")
    c = s["cost"]
    L += ["", "## Corpus", "", f"{s['chunks']} chunks, median {s['chunk_chars_median']} chars, "
              f"{s['chunks_with_heading']} with a heading path.", "",
          "## Cost (from X-Desearch-Cost-Usd)", "",
          f"- links: ${c['links_usd']}", f"- extract: ${c['extract_usd']} over {s['extract_billed_calls']} billed of {s['extract_calls']} calls "
          f"(${c['extract_usd_per_billed_call']} per billed call)", f"- total: ${c['total_usd']}, ${c['usd_per_kept_page']} per kept page", "",
          f"Latency: links median {s['latency_s']['links_median']} s (max {s['latency_s']['links_max']}), "
          f"extract median {s['latency_s']['extract_median']} s (max {s['latency_s']['extract_max']}). Errors (not 200/404): {s['errors']}.", ""]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build a starter RAG corpus from pages Desearch found.")
    ap.add_argument("config", nargs="?", help='JSON: {"topic": str, "sub_questions": [str | {"q": str, "count": int}]}')
    ap.add_argument("--topic"); ap.add_argument("--q", action="append", help="sub-question (repeat 3-5 times)")
    ap.add_argument("--count", type=int, default=50, help="links per sub-question (10-200)")
    ap.add_argument("--max-pages", type=int, default=150)
    ap.add_argument("--max-per-domain", type=int, default=3)
    ap.add_argument("--format", choices=["html", "text"], default="html", help="Extract format (html keeps headings)")
    ap.add_argument("--no-retry", dest="retry", action="store_false")
    ap.add_argument("--chunk-chars", type=int, default=1200)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--max-spend", type=float, default=1.0, help="stop calling once this many USD are spent")
    ap.add_argument("--no-prefix-topic", dest="prefix_topic", action="store_false",
                    help="send the sub-question alone instead of 'topic: sub-question'")
    ap.add_argument("--no-topic-filter", dest="topic_filter", action="store_false",
                    help="keep links whose title and URL share no word with the topic or sub-question")
    ap.add_argument("--save-pages", action="store_true", help="save every Extract response under raw/")
    ap.add_argument("--out", default="runs")
    a = ap.parse_args(argv)
    if a.config:
        cfg = json.load(open(a.config))
    elif a.topic and a.q:
        cfg = {"topic": a.topic, "sub_questions": a.q}
    else:
        ap.error("give a config file or --topic with --q")
    if not 1 <= len(cfg["sub_questions"]) <= 8:
        ap.error("use 3-5 sub-questions (max 8)")
    outdir = os.path.join(a.out, dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + slug(cfg["topic"], 30))
    os.makedirs(os.path.join(outdir, "raw"), exist_ok=True)
    client = Client(api_key(), outdir, a.max_spend)
    s = run(cfg, a, client, outdir)
    print(render_report(s))
    print(f"\nwrote {outdir}/corpus.jsonl, sources.csv, run-report.md, snapshot.json", file=sys.stderr)


if __name__ == "__main__":
    main()
