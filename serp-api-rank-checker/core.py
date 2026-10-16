"""Network-free logic for the SERP API Rank Checker. No I/O, no HTTP: easy to unit-test."""
import csv, io, urllib.parse

PAGE_SIZE = 10


def normalize_url(url):
    """Lowercase scheme/host, drop leading www., fragment, trailing slash and common tracking params."""
    p = urllib.parse.urlsplit((url or "").strip())
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
         if not k.lower().startswith("utm_") and k.lower() not in ("gclid", "fbclid")]
    path = p.path.rstrip("/") or "/"
    return urllib.parse.urlunsplit(("https", host, path, urllib.parse.urlencode(q), ""))


def domain_of(url):
    host = (urllib.parse.urlsplit((url or "").strip()).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def matches_domain(url, domain):
    """True if url's host is domain or a subdomain of it."""
    d, h = domain.lower().lstrip(".").removeprefix("www."), domain_of(url)
    return bool(d) and (h == d or h.endswith("." + d))


def items_of(body):
    """GET /web returns {"data": [...]}. Anything else yields []."""
    if isinstance(body, dict) and isinstance(body.get("data"), list):
        return [i for i in body["data"] if isinstance(i, dict)]
    return []


def merge_pages(pages):
    """pages: list of (start, items) in request order. Returns ranked rows (dedup by normalized URL)
    and per-page stats {start, returned, new, dupes}."""
    seen, rows, stats = set(), [], []
    for start, items in pages:
        new = 0
        for it in items:
            url = it.get("link") or it.get("url") or ""
            key = normalize_url(url)
            if not url or key in seen:
                continue
            seen.add(key)
            new += 1
            rows.append({"rank": len(rows) + 1, "title": (it.get("title") or "").strip(), "url": url,
                         "domain": domain_of(url), "page_start": start})
        stats.append({"start": start, "returned": len(items), "new": new, "dupes": len(items) - new})
    return rows, stats


def best_rank(rows, domain):
    for r in rows:
        if matches_domain(r["url"], domain):
            return r["rank"]
    return None


def rank_label(rank, depth):
    return str(rank) if rank else f"not in top {depth}"


def keyword_summary(keyword, domain, rows):
    br = best_rank(rows, domain)
    hit = next((r for r in rows if r["rank"] == br), None)
    return {"keyword": keyword, "domain": domain, "best_rank": br, "label": rank_label(br, len(rows)),
            "best_url": hit["url"] if hit else "", "depth": len(rows)}


def to_csv(results):
    """results: list of {keyword, rows}. One CSV row per result."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["keyword", "rank", "title", "url", "domain", "page_start"])
    for res in results:
        for r in res["rows"]:
            w.writerow([res["keyword"], r["rank"], r["title"], r["url"], r["domain"], r["page_start"]])
    return buf.getvalue()


def diff_runs(old, new):
    """old/new: {keyword: best_rank or None}. Returns list of change dicts."""
    out = []
    for kw in sorted(set(old) | set(new)):
        a, b = old.get(kw), new.get(kw)
        if a == b:
            change = "same"
        elif a is None:
            change = "entered"
        elif b is None:
            change = "dropped out"
        else:
            change = f"up {a - b}" if b < a else f"down {b - a}"
        out.append({"keyword": kw, "before": a, "after": b, "change": change})
    return out


def url_overlap(rows_a, rows_b, top=10):
    """Share of normalized URLs in the top N of run A that also appear in the top N of run B."""
    a = {normalize_url(r["url"]) for r in rows_a[:top]}
    b = {normalize_url(r["url"]) for r in rows_b[:top]}
    return (len(a & b), len(a))


def parse_keywords(text):
    seen, out = set(), []
    for line in text.splitlines():
        k = line.strip()
        if k and not k.startswith("#") and k.lower() not in seen:
            seen.add(k.lower())
            out.append(k)
    return out
