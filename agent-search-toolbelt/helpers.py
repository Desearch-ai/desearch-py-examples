"""Helpers for toolbelt.py: key loading, result parsing, cost fields and the Markdown answer."""
import datetime as dt, json, os, pathlib, re

# Published rates (desearch.ai/pricing, checked 2026-10-09): Extract $0.50 per 1,000 pages,
# X Search $0.15 per 1,000 posts with a 10-post minimum per request. The same values came back in the
# REST X-Desearch-Cost-Usd header for the same calls. Used only for MCP tools whose result has no cost field.
REST_RATES = {"extract": 0.0005, "x-search": 0.00015}  # per page / per post
X_MIN_POSTS = 10
STOP = set("a an and are as at be by can do does for from has have how i in is it its of on or "
           "the this to was what when where which who why will with week this changed new latest".split())


def api_key():
    key = os.environ.get("DESEARCH_API_KEY")
    if not key:
        path = os.environ.get("DESEARCH_API_KEY_FILE")
        key = pathlib.Path(path).read_text().strip() if path else None
    if not key:
        raise SystemExit("Set DESEARCH_API_KEY (or DESEARCH_API_KEY_FILE) to your key from console.desearch.ai")
    return key


def parse_result(res):
    """MCP tool result -> Python data. Text content is JSON in most tools; extract returns a JSON string."""
    texts = [c.text for c in (getattr(res, "content", None) or []) if getattr(c, "type", "") == "text"]
    if not texts:
        return None
    raw = "\n".join(texts)
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def is_error(res):
    return bool(getattr(res, "is_error", None) or getattr(res, "isError", None))


def save_raw(folder, n, tool, args, res):
    p = pathlib.Path(folder)
    p.mkdir(parents=True, exist_ok=True)
    body = res.model_dump(mode="json") if hasattr(res, "model_dump") else str(res)
    (p / f"{n:02d}-{tool}.json").write_text(json.dumps({"tool": tool, "args": args, "result": body}, indent=1, ensure_ascii=False))


def count_items(data):
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for k in ("search_results", "data", "search", "tweets"):
            if isinstance(data.get(k), list):
                return len(data[k])
    if isinstance(data, str):
        return 1 if data.strip() else 0
    return 0


def cost_fields(tool, data, meta=None):
    """Cost the tool itself reported (result body or _meta), plus a labelled estimate when it reported none."""
    for src, d in (("result", data), ("_meta", meta)):
        if isinstance(d, dict) and d.get("cost_usd") is not None:
            return {"cost_usd": float(d["cost_usd"]), "usage_count": d.get("usage_count"), "cost_source": src}
    est = None
    if tool == "extract" and page_text(data):
        est = REST_RATES["extract"]
    elif tool == "x-search" and isinstance(data, list):
        est = round(REST_RATES["x-search"] * max(len(data), X_MIN_POSTS), 6)
    return {"cost_usd": None, "cost_source": "not returned", "est_cost_usd": est}


def link_results(data):
    items = (data.get("search_results") or data.get("data") or []) if isinstance(data, dict) else []
    return [{"title": i.get("title", ""), "link": i.get("link") or i.get("url"), "snippet": i.get("snippet", "")}
            for i in items if isinstance(i, dict) and (i.get("link") or i.get("url"))]


def page_text(data):
    if isinstance(data, str):
        return data.strip()
    if isinstance(data, dict):
        return str(data.get("content") or data.get("text") or "").strip()
    return ""


def keywords(q):
    return [w for w in re.findall(r"[a-z0-9][a-z0-9.+#-]*", q.lower()) if w not in STOP and len(w) > 1]


def x_query(q):
    return " ".join(keywords(q)[:4]) or q


def date_window(days, today=None):
    today = today or dt.datetime.now(dt.timezone.utc).date()
    return {"start_date": (today - dt.timedelta(days=days)).isoformat(),
            "end_date": (today + dt.timedelta(days=1)).isoformat()}


def excerpt(text, q, n=2, width=300, scan=80):
    """Pick the n sentences (from the first `scan`) that mention the most question keywords, in page order."""
    pats = [re.compile(r"\b" + re.escape(k)) for k in keywords(q)]
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text)) if 40 <= len(s.strip()) <= 600][:scan]
    scored = sorted(enumerate(sents), key=lambda p: (-sum(bool(r.search(p[1].lower())) for r in pats), p[0]))
    best = sorted(scored[:n], key=lambda p: p[0])
    return " ".join(s if len(s) <= width else s[:width].rsplit(" ", 1)[0] + "..." for _, s in best)


def clean(text):
    """Collapse whitespace; show long dashes in quoted third-party text as a plain hyphen."""
    return re.sub(r"\s+", " ", text.replace("\u2014", " - ").replace("\u2013", "-")).strip()


def x_posts(data):
    out = []
    for p in data if isinstance(data, list) else []:
        if isinstance(p, dict) and p.get("url"):
            out.append({"url": p["url"], "text": clean(p.get("text", ""))[:160],
                        "created_at": p.get("created_at", ""), "likes": p.get("like_count", 0)})
    return out


def render_answer(q, results, pages, posts, calls):
    lines = [f"# {q}", "", "## What the pages say", ""]
    for i, p in enumerate(pages, 1):
        lines.append(f"{i}. {clean(p['excerpt'])} ([{clean(p['title']) or p['link']}]({p['link']}))")
    if not pages:
        lines.append("No page text came back for the top links.")
    lines += ["", "## Other links found", ""]
    read = {p["link"] for p in pages}
    lines += [f"- [{clean(r['title']) or r['link']}]({r['link']})" for r in results if r["link"] not in read] or ["- none"]
    lines += ["", "## On X", ""]
    lines += [f"- {p['created_at']}: {p['text']} ({p['url']})" for p in posts] or ["- no posts returned"]
    return "\n".join(lines) + "\n" + run_footer(calls)


def run_footer(calls):
    reported = [c["cost_usd"] for c in calls if c.get("cost_usd") is not None]
    est = [c["est_cost_usd"] for c in calls if c.get("est_cost_usd") is not None]
    return "\n".join(["", "## Run", "",
                      f"- {len(calls)} tool calls, {sum(c['latency_s'] for c in calls):.1f} s total",
                      f"- cost reported by the tools: ${sum(reported):.4f} ({len(reported)} of {len(calls)} calls report cost)",
                      f"- estimate for calls without a cost field: ${sum(est):.4f} (published rates, see README)",
                      "- tool calls: " + ", ".join(f"{c['tool']} {c['latency_s']}s" for c in calls), ""])
