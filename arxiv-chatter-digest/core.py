"""Pure helpers for arxivchatter.py (no network): arXiv ids, X queries, arXiv metadata, ranking, output files."""
import csv, datetime as dt, difflib, io, json, re, xml.etree.ElementTree as ET

# Public rates (desearch.ai/pricing, "Reference rates as of 7 May 2026", checked 2026-10-12).
# X Search is billed by posts returned, 10-post minimum, never above the count requested.
RATES = {"ai-search": 0.0004, "extract": 0.0005, "x-search": 0.00015}  # per item / page / post
X_MIN_POSTS = 10

ID_RE = re.compile(r"(?:arxiv\.org|ar5iv(?:\.labs)?\.arxiv\.org)/(?:abs|html|pdf)/(\d{4}\.\d{4,5})(v\d+)?", re.I)
ATOM = {"a": "http://www.w3.org/2005/Atom"}


def arxiv_id(link):
    """'https://arxiv.org/html/2609.30079v1' -> '2609.30079'. None for list, search and home pages."""
    m = ID_RE.search(link or "")
    return m.group(1) if m else None


def strip_id_prefix(title):
    return re.sub(r"^\s*\[\d{4}\.\d{4,5}(v\d+)?\]\s*", "", title or "").strip()


def norm_title(t):
    return " ".join(re.findall(r"[a-z0-9]+", (t or "").lower()))


def title_similarity(a, b):
    return round(difflib.SequenceMatcher(None, norm_title(a), norm_title(b)).ratio(), 3)


def collect_papers(search_results):
    """List of (prompt, [result dicts]) -> {id: {...}} in first-seen order, with every link form seen."""
    papers, skipped = {}, []
    for prompt, results in search_results:
        for r in results:
            link = r.get("link") or r.get("url") or ""
            pid = arxiv_id(link)
            if not pid:
                skipped.append(link)
                continue
            p = papers.setdefault(pid, {"arxiv_id": pid, "desearch_title": strip_id_prefix(r.get("title", "")),
                                        "links_seen": [], "prompts": []})
            if link not in p["links_seen"]:
                p["links_seen"].append(link)
            if prompt not in p["prompts"]:
                p["prompts"].append(prompt)
    return papers, skipped


def parse_arxiv_atom(xml_text):
    """arXiv export API Atom feed -> {id: {title, published, authors, summary}}."""
    out = {}
    root = ET.fromstring(xml_text)
    for e in root.findall("a:entry", ATOM):
        eid = (e.findtext("a:id", "", ATOM) or "")
        m = re.search(r"abs/(\d{4}\.\d{4,5})", eid)
        if not m:
            continue
        out[m.group(1)] = {
            "title": " ".join((e.findtext("a:title", "", ATOM) or "").split()),
            "published": (e.findtext("a:published", "", ATOM) or "")[:10],
            "authors": [a.findtext("a:name", "", ATOM) for a in e.findall("a:author", ATOM)],
            "summary": " ".join((e.findtext("a:summary", "", ATOM) or "").split()),
        }
    return out


def short_title(title, words=8):
    """First words of the title, cut at a colon if the part before it is long enough."""
    t = clean(title).replace('"', "")
    head = t.split(":")[0]
    if len(head.split()) >= 3:
        t = head
    return " ".join(t.split()[:words])


def x_query(pid, title):
    """Parenthesised OR group: the arXiv id or the (short) title as exact phrases."""
    return f'("{pid}" OR "{short_title(title)}")'


def status_id(url):
    m = re.search(r"/status(?:es)?/(\d+)", url or "")
    return m.group(1) if m else None


def handle_free(url):
    sid = status_id(url)
    return f"https://x.com/i/status/{sid}" if sid else None


def clean(text):
    return re.sub(r"\s+", " ", (text or "").replace("\u2014", " - ").replace("\u2013", "-")).strip()


def scrub_text(text):
    """Post text for public files: no @handles, no links that carry a handle."""
    t = re.sub(r"https?://(?:www\.)?(?:x|twitter)\.com/[A-Za-z0-9_]+/status/(\d+)\S*", r"https://x.com/i/status/\1", text or "")
    t = re.sub(r"https?://(?:www\.)?(?:x|twitter)\.com/(?!i/status/)[A-Za-z0-9_]+\S*", "(an X profile)", t)
    t = re.sub(r"(?<![\w.])@[A-Za-z0-9_]{1,15}", "@user", t)
    return clean(t)


def parse_x_created(s):
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return dt.datetime.strptime(s, fmt)
        except (TypeError, ValueError):
            pass
    return None


def x_posts(data, start_date=None):
    """x-search list -> unique posts with handle-free links and an in-window flag."""
    out, seen = [], set()
    for p in data if isinstance(data, list) else []:
        if not isinstance(p, dict):
            continue
        sid = str(p.get("id") or status_id(p.get("url", "")) or "")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        created = parse_x_created(p.get("created_at", ""))
        in_win = None if (created is None or not start_date) else created.date() >= dt.date.fromisoformat(start_date)
        out.append({"id": sid, "url": f"https://x.com/i/status/{sid}", "created": created.date().isoformat() if created else "",
                    "in_window": in_win, "likes": p.get("like_count") or 0, "text": scrub_text(p.get("text", ""))[:200]})
    return out


def x_cost_calculated(n_posts, count):
    """Pricing-page rule: posts returned, 10-post minimum, never above count."""
    return round(RATES["x-search"] * min(max(n_posts, X_MIN_POSTS), count), 6)


def abstract_from_page(text):
    t = clean(text)
    m = re.search(r"Abstract:\s*(.+?)(?:\s+(?:Comments|Subjects|Submission history|Cite as):|$)", t)
    return m.group(1).strip() if m else ""


def page_text(data):
    if isinstance(data, str):
        return data.strip()
    if isinstance(data, dict):
        return str(data.get("content") or data.get("text") or "").strip()
    return ""


def rank(papers):
    """Most X posts first, then most likes on those posts, then newest."""
    return sorted(papers, key=lambda p: (-p["mention_count"], -sum(x["likes"] for x in p["posts"]),
                                         -int((p["published"] or "0").replace("-", ""))))


def papers_csv(papers, fetched_at):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["rank", "arxiv_id", "title", "abs_url", "published", "in_window", "title_match", "x_mention_count",
                "x_posts_out_of_window", "sample_post_urls", "extract_status", "fetched_at"])
    for i, p in enumerate(papers, 1):
        w.writerow([i, p["arxiv_id"], p["title"], p["abs_url"], p["published"], p["in_window"], p["title_match"],
                    p["mention_count"], p["out_of_window_posts"], " ".join(x["url"] for x in p["posts"][:3]),
                    p["extract_status"], fetched_at])
    return buf.getvalue()


def digest_md(topic, papers, window, fetched_at, top=10, min_top=5):
    talked = [p for p in papers if p["mention_count"] > 0]
    shown = (talked + [p for p in papers if p["mention_count"] == 0])[:max(min(top, len(papers)), 0)]
    if len(talked) >= min_top:
        shown = talked[:top]
    lines = [f"# Arxiv Chatter Digest: {topic}", "",
             f"Papers Desearch returned and public X posts that named them. Paper window {window[0]} to {window[1]} (arXiv first-version date), "
             f"X posts from each paper's date. Fetched {fetched_at}.", "",
             f"{len(papers)} papers checked, {len(talked)} with at least one X post naming them.", ""]
    for i, p in enumerate(shown, 1):
        authors = ", ".join(p["authors"][:3]) + (" et al." if len(p["authors"]) > 3 else "")
        lines += [f"## {i}. {clean(p['title'])}", "",
                  f"{p['abs_url']} . {p['published']} . {authors}", "",
                  f"**X posts naming it:** {p['mention_count']}", ""]
        if p["abstract"]:
            a = p["abstract"]
            lines += ["> " + (a if len(a) <= 400 else a[:400].rsplit(" ", 1)[0] + "..."), ""]
        for x in p["posts"][:3]:
            lines.append(f"- {x['url']} ({x['created']}, {x['likes']} likes, an X account): \"{x['text'][:140]}\"")
        lines.append("")
    return "\n".join(lines)


def assert_no_key(text, key):
    if key and key in text:
        raise RuntimeError("refusing to write a file that contains the API key")
    return text
