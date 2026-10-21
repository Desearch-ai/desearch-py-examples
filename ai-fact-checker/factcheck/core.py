"""Network-free logic for the AI Fact Checker: input checks, request bodies, source cleanup, citations, limits."""
import collections, html, json, re, threading, time, urllib.parse

MIN_CLAIM, MAX_CLAIM = 8, 200
X_COUNT = 10
STRONG_SHARE = 0.6        # a source "matches" when it contains at least 60% of the claim's key terms
MIN_STRONG = 2            # legacy overlap metadata only; never used for display
STOP = set("""a an the is are was were be been being of to in on at by for with from as and or but not no nor
this that these those it its it's into than then so such can could will would should may might must do does did
has have had about over under more most less very just also only there their they them he she his her we you your
i me my our what which who whom whose when where why how all any each both few other some own same too up down out
off again further once here per via vs if""".split())
PROFANITY = re.compile(r"\b(?:f[u*]ck(?:s|ed|er|ers|ing)?|sh[i!*]t(?:s|ty|ting)?|bullsh[i!*]t|"
                       r"motherf[u*]cker(?:s)?|b[i!*]tch(?:es)?|asshole(?:s)?|c[u*]nt(?:s)?|"
                       r"n[i!*]gg(?:er|a)s?|f[a*]gg?ots?|r[e*]tard(?:s|ed)?)\b", re.I)
SKIP_NS = re.compile(r"/wiki/(File|Archivo|Ficheiro|Fichier|Datei|Talk|Portal|Category|Template|User|Wikipedia|Help|Special)[:%]", re.I)
WIKI_HOST = re.compile(r"^(?:[a-z\-]+\.)?(?:m\.)?wikipedia\.org$")
MENTION = re.compile(r"(?<![\w])@\w{1,15}")
CITE = re.compile(r"\[(\d+)\]\((https?://[^\s()]+(?:\([^\s()]*\)[^\s()]*)*)\)")
VERDICT = re.compile(
    r"\b(?:true|false|correct|incorrect|accurate|inaccurate|right|wrong|confirmed|debunked|"
    r"myth|misconception|untrue|indeed)\b|"
    r"\b(?:is|are|was|were)\s+not\b|\b(?:isn|aren|wasn|weren)['’]t\b|"
    r"\b(?:the|this)\s+(?:claim|statement|assertion)\b[^.!?]*\b(?:is|are|was|were)\b|"
    r"\bit\s+is\s+a\s+fact\b", re.I)


class FormError(ValueError):
    pass


def clean_claim(s):
    """Collapses whitespace and checks the claim before any paid call (blank or junk input is billed upstream)."""
    c = _txt(s)
    if not c:
        raise FormError("Enter one claim to check.")
    if len(c) < MIN_CLAIM:
        raise FormError(f"A claim is at least {MIN_CLAIM} characters.")
    if len(c) > MAX_CLAIM:
        raise FormError(f"A claim is at most {MAX_CLAIM} characters.")
    if len(key_terms(c)) < 2:
        raise FormError("Write the claim as a short sentence with at least two words that carry meaning.")
    return c


def cache_key(claim, wiki=False, x=False):
    """Normalized claim used for the CDN/browser cache and the in-memory cache."""
    k = re.sub(r"[^\w\s']", " ", claim.lower())
    return " ".join(k.split()) + ("|wiki" if wiki else "") + ("|x" if x else "")


def key_terms(text):
    words = re.findall(r"[a-z0-9][a-z0-9'\-]*", str(text).lower())
    out = []
    for w in words:
        w = w.strip("'-")
        if len(w) > 1 and w not in STOP and w not in out:
            out.append(w)
    return out


def ai_body(claim, tool="web"):
    """POST /desearch/ai/search body. One tool per call: web and wikipedia in one call returned only wikipedia links."""
    return {"prompt": claim, "tools": [tool], "streaming": False, "result_type": "LINKS_WITH_FINAL_SUMMARY", "count": 10,
            "system_message": "Provide a neutral summary of what the sources say, citing sources. "
                              "Do not judge whether the claim is true or false or give a verdict on the claim."}


def x_params(claim):
    """GET /twitter params. The full sentence is too narrow for X search, so the query is the first 4 key terms."""
    return {"query": " ".join(key_terms(claim)[:4]), "sort": "Top", "count": X_COUNT}


def _txt(s):
    t = str(s or "")
    while True:
        decoded = html.unescape(t)
        if decoded == t:
            break
        t = decoded
    return " ".join(re.sub(r"<[^>]*>", " ", t).split())


def clean_summary(text):
    t = _txt(text)
    t = re.sub(r"(?:\[source\]\s*){2,}", "[source] ", t, flags=re.I)
    t = re.sub(r"\s+([.,;:!?])", r"\1", t)
    t = re.sub(r"[,;:.]*\.[,;:.]*", ".", t)
    return t.strip()


def safe_url(value):
    u = str(value or "").strip()
    try:
        p = urllib.parse.urlsplit(u)
        return u if p.scheme.lower() in ("http", "https") and p.hostname else ""
    except ValueError:
        return ""


def raw_sources(resp):
    out = []
    if isinstance(resp, dict):
        for k, v in resp.items():
            if isinstance(v, list):
                out += [x for x in v if isinstance(x, dict) and (x.get("link") or x.get("url"))]
    return out


def source_type(url):
    host = urllib.parse.urlsplit(url).hostname or ""
    return "wikipedia" if WIKI_HOST.match(host) else "web"


def skip_reason(url):
    """Wikipedia file, talk and portal pages and non-English Wikipedia pages are dropped."""
    host = urllib.parse.urlsplit(url).hostname or ""
    if WIKI_HOST.match(host):
        if SKIP_NS.search(url) or "title=Portal:" in url:
            return "wiki non-article page"
        lang = host.split(".")[0]
        if lang not in ("en", "simple", "wikipedia", "m"):
            return "wiki non-English page"
    return None


def clean_sources(items, claim):
    """Normalize, dedupe by URL, drop non-article wiki pages. Returns (sources, stats)."""
    terms, seen, out, skipped, dup = key_terms(claim), set(), [], collections.Counter(), 0
    for it in items:
        url = safe_url(it.get("link") or it.get("url"))
        if not url:
            skipped["invalid URL"] += 1
            continue
        u = url.replace("://en.m.", "://en.").replace("://simple.m.", "://simple.").rstrip("/")
        if u in seen:
            dup += 1
            continue
        seen.add(u)
        why = skip_reason(url)
        if why:
            skipped[why] += 1
            continue
        hl = [_txt(h) for h in (it.get("highlights") or []) if _txt(h)] if isinstance(it.get("highlights"), list) else []
        snippet = _txt(it.get("snippet"))
        title = _txt(it.get("title"))
        found = set(key_terms(" ".join([title, snippet] + hl)))
        share = sum(w in found for w in terms) / len(terms) if terms else 0.0
        out.append({"rank": len(out) + 1, "title": title, "url": url, "domain": urllib.parse.urlsplit(url).hostname or "",
                    "type": source_type(url), "snippet": snippet, "quote": next((h for h in hl if len(h) > 40), "")[:400],
                    "term_share": round(share, 2)})
    return out, {"returned": len(items), "kept": len(out), "duplicates": dup, "skipped": dict(skipped)}


def is_verdict(text):
    """Conservatively hide judgment language, matching whole words in sentence text only."""
    return bool(VERDICT.search(_txt(CITE.sub("", text))))


def summary_sentences(text):
    """Shield citation URLs from punctuation splitting and bind trailing citations to their sentence."""
    citations = []

    def shield(match):
        citations.append(match.group())
        return f"\x00{len(citations) - 1}\x00"

    masked = CITE.sub(shield, text)
    ends = re.finditer(r'''[.!?]["'’”\])]*(?:\s*\x00\d+\x00)*(?=\s+|$)''', masked)
    start = 0
    for end in ends:
        part = masked[start:end.end()].strip()
        if part:
            yield re.sub(r"\x00(\d+)\x00", lambda m: citations[int(m[1])], part)
        start = end.end()
    if masked[start:].strip():
        yield re.sub(r"\x00(\d+)\x00", lambda m: citations[int(m[1])], masked[start:].strip())


def check_citations(completion, sources):
    """Hide verdicts separately, then keep sentences citing only returned sources."""
    norm = lambda u: urllib.parse.unquote(u).rstrip("/")
    urls = {norm(s["url"]) for s in sources}
    text = _txt(completion)
    keep, hidden, verdict_hidden, cited = [], 0, 0, []
    for p in summary_sentences(text):
        if is_verdict(p):
            verdict_hidden += 1
            continue
        cs = CITE.findall(p)
        ok = bool(cs) and all(norm(u) in urls for _, u in cs)
        if ok:
            keep.append({"text": clean_summary(CITE.sub("", p)), "cites": list(dict.fromkeys(u for _, u in cs))})
            cited += [u for _, u in cs if u not in cited]
        elif cs or len(p) > 3:
            # a trailing citation-only fragment belongs to the previous kept sentence
            if cs and not CITE.sub("", p).strip(" .") and keep and all(norm(u) in urls for _, u in cs):
                keep[-1]["cites"] = list(dict.fromkeys(keep[-1]["cites"] + [u for _, u in cs]))
                cited += [u for _, u in cs if u not in cited]
                continue
            hidden += 1
    return {"lines": keep, "hidden": hidden, "verdict_hidden": verdict_hidden, "cited_urls": cited}


def strength(sources):
    strong = [s for s in sources if s["term_share"] >= STRONG_SHARE]
    return {"strong": len(strong), "no_strong_sources": len(strong) < MIN_STRONG}


def clean_posts(body, query_terms=None, limit=X_COUNT):
    """Keep posts with at least two claim terms (all if fewer), no profanity or account mentions.
    Clean display text, author always 'a user', no profile links. Returns (posts, dropped)."""
    posts = body if isinstance(body, list) else (body.get("data") or body.get("tweets") or []) if isinstance(body, dict) else []
    out, dropped = [], 0
    qt = set(key_terms(" ".join(query_terms or [])))
    for p in posts[:limit]:
        if not isinstance(p, dict):
            continue
        t = _txt(p.get("text"))
        if not qt or len(qt.intersection(key_terms(t))) < min(2, len(qt)) or PROFANITY.search(t) or MENTION.search(t):
            dropped += 1
            continue
        pid = str(p.get("id") or "")
        out.append({"text": t, "author": "a user", "created_at": _txt(p.get("created_at")),
                    "likes": p.get("like_count"), "reposts": p.get("retweet_count"),
                    "url": f"https://x.com/i/status/{pid}" if pid.isdigit() else ""})
    return out, dropped


def build_result(claim, ai, x=None, wiki=None):
    """ai/x/wiki are dicts {status, body, cost, latency_s} from the client. Returns the JSON the page renders."""
    items = raw_sources(ai["body"]) + (raw_sources(wiki["body"]) if wiki else [])
    sources, stats = clean_sources(items, claim)
    comp = ai["body"].get("completion") if isinstance(ai["body"], dict) else ""
    summ = check_citations(comp or "", sources)
    calls = [c for c in (ai, x, wiki) if c]
    xq = x_params(claim)["query"]
    result = {"claim": _txt(claim), "sources": sources, "stats": stats, **strength(sources), "summary": summ,
            "x_enabled": x is not None,
            "cost_usd": round(sum(c.get("cost", 0) for c in calls), 6),
            "latency_s": round(max(c.get("latency_s", 0) for c in calls), 2), "calls": len(calls)}
    if x:
        posts, dropped = clean_posts(x["body"], key_terms(claim)) if x.get("status") == 200 else ([], 0)
        body = x.get("body")
        raw = body if isinstance(body, list) else (body.get("data") or body.get("tweets") or []) if isinstance(body, dict) else []
        result.update(posts=posts, x_returned=len(raw), x_dropped=dropped, x_query=xq)
    return result


class RateLimiter:
    """Sliding-window per-IP and global limits, in memory. On serverless hosts this is per warm instance only."""

    def __init__(self, per_ip=5, window=600, per_ip_day=15, global_window=30, clock=time.time):
        self.per_ip, self.window, self.per_ip_day, self.global_window, self.clock = per_ip, window, per_ip_day, global_window, clock
        self.hits, self.lock = collections.defaultdict(list), threading.Lock()

    def allow(self, ip):
        now = self.clock()
        with self.lock:
            h = self.hits[ip] = [t for t in self.hits[ip] if now - t < 86400]
            recent = [t for t in h if now - t < self.window]
            total = sum(1 for hs in self.hits.values() for t in hs if now - t < self.window)
            if len(recent) >= self.per_ip or len(h) >= self.per_ip_day or total >= self.global_window:
                return False
            h.append(now)
            return True


class DailyCap:
    """Stops paid calls once today's header cost reaches `cap_usd`. Day boundary is UTC. Per process / instance."""

    def __init__(self, cap_usd=1.0, clock=time.time):
        self.cap, self.clock, self.day, self.spent, self.lock = cap_usd, clock, None, 0.0, threading.Lock()

    def _roll(self):
        d = time.strftime("%Y-%m-%d", time.gmtime(self.clock()))
        if d != self.day:
            self.day, self.spent = d, 0.0

    def ok(self):
        with self.lock:
            self._roll()
            return self.spent < self.cap

    def add(self, usd):
        with self.lock:
            self._roll()
            self.spent += float(usd or 0)


class TTLCache:
    def __init__(self, ttl=21600, clock=time.monotonic, max_items=500):
        self.ttl, self.clock, self.max, self.d = ttl, clock, max_items, collections.OrderedDict()

    def get(self, k):
        v = self.d.get(k)
        if v and self.clock() - v[0] < self.ttl:
            return v[1]
        self.d.pop(k, None)
        return None

    def put(self, k, val):
        self.d[k] = (self.clock(), val)
        self.d.move_to_end(k)
        while len(self.d) > self.max:
            self.d.popitem(last=False)


def to_json(payload):
    return json.dumps(payload, indent=1, ensure_ascii=False)


def render_text(res):
    p = [f"Claim: {res['claim']}", f"{len(res['sources'])} sources returned."]
    if len(res["sources"]) < 2:
        p.append("Few sources returned. Read them before you share anything.")
    p += [f"  - {ln['text']}" for ln in res["summary"]["lines"]]
    if res["summary"]["hidden"]:
        p.append(f"  ({res['summary']['hidden']} uncited summary sentence(s) hidden)")
    if res["summary"].get("verdict_hidden"):
        p.append(f"{res['summary']['verdict_hidden']} summary sentence(s) that judged the claim were hidden.")
    for s in res["sources"]:
        p.append(f"{s['rank']:>2}. {s['title']}\n    {s['domain']}\n    {s['url']}\n    {s['snippet']}")
    if res.get("x_enabled"):
        p.append(f"X posts: {len(res['posts'])} kept of {res['x_returned']} for query '{res['x_query']}'.")
    p.append(f"Cost ${res['cost_usd']} ({res['calls']} calls)")
    return "\n".join(p)


def render_html(res):
    """Server-side HTML for a result (used by the CLI --html export and samples/page.html)."""
    e = lambda s: html.escape(str(s if s is not None else ""), quote=True)
    p = [f"<!doctype html><meta charset=utf-8><title>AI Fact Checker: {e(res['claim'])}</title>",
         "<style>body{font:15px system-ui;max-width:900px;margin:2em auto}td,th{border-bottom:1px solid #ddd;padding:.4em;vertical-align:top}"
         ".s{color:#555}</style>",
         f"<h1>AI Fact Checker</h1><p><b>Claim:</b> {e(res['claim'])}</p>"]
    p.append(f"<p>{len(res['sources'])} sources returned.</p>")
    if len(res["sources"]) < 2:
        p.append("<p>Few sources returned. Read them before you share anything.</p>")
    if res["summary"]["lines"]:
        p.append("<h2>Draft summary (cited lines only)</h2><ul>")
        for ln in res["summary"]["lines"]:
            cites = list(dict.fromkeys(ln["cites"]))
            p.append(f"<li>{e(ln['text'])} " + " ".join(f"<a href='{e(safe_url(u))}'>[source{(' ' + str(i + 1)) if len(cites) > 1 else ''}]</a>"
                      for i, u in enumerate(cites)) + "</li>")
        p.append("</ul>")
    if res["summary"]["hidden"]:
        p.append(f"<p class=s>{e(res['summary']['hidden'])} summary sentence(s) cited no returned source and were hidden.</p>")
    if res["summary"].get("verdict_hidden"):
        p.append(f"<p class=s>{e(res['summary']['verdict_hidden'])} summary sentence(s) that judged the claim were hidden.</p>")
    p.append("<h2>Sources</h2><table><tr><th>#</th><th>Source</th><th>Domain</th><th>Snippet</th></tr>")
    for s in res["sources"]:
        p.append(f"<tr><td>{e(s['rank'])}</td><td><a href='{e(safe_url(s['url']))}'>{e(s['title'] or s['url'])}</a>"
                 f"</td><td>{e(s['domain'])}</td><td>{e(s['snippet'][:300])}</td></tr>")
    p.append("</table>")
    if res.get("x_enabled") and res.get("posts"):
        p.append(f"<h2>How it is discussed on X</h2><p class=s>Query: {e(res['x_query'])}</p><ul>")
        for x in res["posts"]:
            p.append(f"<li>{e(x['text'][:400])}<br><span class=s>a user, {e(x['created_at'])}</span> <a href='{e(safe_url(x['url']))}'>post</a></li>")
        p.append("</ul>")
    p.append(f"<p class=s>Read the sources to assess the claim. Cost ${e(res['cost_usd'])} for {e(res['calls'])} calls. "
             "Made by Desearch, <a href='https://desearch.ai'>desearch.ai</a></p>")
    return "".join(p)
