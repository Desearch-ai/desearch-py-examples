"""Brand Mentions Finder: third-party pages and public X posts for one brand.

Made by Desearch (https://desearch.ai).

Live:     python brand_mentions.py config.json
Offline:  python brand_mentions.py --from-raw evidence/raw-YYYY-MM-DD.json
"""
import argparse, csv, datetime as dt, json, os, re, sys
from urllib.parse import urlparse

BASE = "https://api.desearch.ai"
POSITIVE = ("love", "worth", "best", "replaced", "favorite", "favourite", "recommend", "great", "useful")
NEGATIVE = ("uninstall", "hate", "worst", "disappointing", "removed", "not a fan", "regret", "annoying", "slow")


def api_key():
    """DESEARCH_API_KEY, else the file named by DESEARCH_API_KEY_FILE. Never printed or saved."""
    key = os.environ.get("DESEARCH_API_KEY", "").strip()
    path = os.environ.get("DESEARCH_API_KEY_FILE")
    if not key and path:
        with open(os.path.expanduser(path)) as f:
            key = f.read().strip()
    if not key:
        sys.exit("Set DESEARCH_API_KEY (or DESEARCH_API_KEY_FILE) to your key from console.desearch.ai")
    return key


def redact(text, key):
    if key and key in text:
        return text.replace(key, "<redacted>")
    return text


def write_text(path, text, key):
    with open(path, "w") as f:
        f.write(redact(text, key))


def parse_time(value):
    if not value:
        return None
    s = str(value).strip().replace("Z", "+0000")
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            found = dt.datetime.strptime(s, fmt)
            if found.tzinfo is None:
                found = found.replace(tzinfo=dt.timezone.utc)
            return found.astimezone(dt.timezone.utc)
        except ValueError:
            continue
    return None


def window(cfg):
    end = dt.date.fromisoformat(cfg["today"]) if cfg.get("today") else dt.date.today()
    start = end - dt.timedelta(days=int(cfg.get("days", 30)))
    return start, end


def term_query(terms):
    parts = []
    for term in terms:
        parts.append('"%s"' % term if " " in term else term)
    return "(" + " OR ".join(parts) + ")"


def x_query(cfg):
    group = term_query(cfg["brand_terms"])
    account = (cfg.get("own_account") or "").strip().lstrip("@")
    if account:
        group += " -from:%s" % account
    return group


def ai_payload(cfg, start, end):
    brand = cfg["brand"]
    what = (cfg.get("what_it_is") or "").strip()
    prompt = "Third-party reviews, articles and posts that mention %s" % brand
    if what:
        prompt += ", %s" % what
    prompt += ", from the past month"
    return {
        "prompt": prompt,
        "tools": ["web", "twitter"],
        "result_type": "ONLY_LINKS",
        "streaming": False,
        "start_date": "%sT00:00:00Z" % start.isoformat(),
        "end_date": "%sT23:59:59Z" % end.isoformat(),
    }


def x_params(cfg, start, end):
    return {
        "query": x_query(cfg),
        "sort": "Latest",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "min_likes": int(cfg.get("min_likes", 5)),
        "count": int(cfg.get("x_count", 20)),
    }


def host_of(url):
    return urlparse(url or "").netloc.lower().removeprefix("www.")


def on_own_domain(url, domains):
    host = host_of(url)
    if not host:
        return False
    for domain in domains or []:
        d = domain.lower().strip().removeprefix("www.")
        if d and (host == d or host.endswith("." + d)):
            return True
    return False


def public_post_link(url, post_id=""):
    if post_id:
        return "https://x.com/i/status/%s" % post_id
    match = re.search(r"/status/(\d+)", url or "")
    if match:
        return "https://x.com/i/status/%s" % match.group(1)
    return ""


def snippet(text, words=25):
    text = re.sub(r"@\w+", "", text or "")
    text = re.sub(r"\s+", " ", text).replace("\u2014", ", ").strip()
    return " ".join(text.split(" ")[:words])


def tone_of(text):
    low = (text or "").lower()
    if any(word in low for word in NEGATIVE):
        return "negative"
    if any(word in low for word in POSITIVE):
        return "positive"
    return "neutral"


def contains_term(text, terms):
    low = (text or "").lower()
    return any(term.lower() in low for term in terms)


def other_meaning(text, cfg):
    words = [w.lower() for w in cfg.get("other_meaning_words") or []]
    if not words:
        return False
    low = (text or "").lower()
    if not any(word in low for word in words):
        return False
    product = [w.lower() for w in cfg.get("product_words") or []]
    return not any(word in low for word in product)


def as_list(body, keys):
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in keys:
            if isinstance(body.get(key), list):
                return body[key]
    return []


def run_live(cfg, session=None):
    key = api_key()
    if session is None:
        import requests
        session = requests.Session()
    session.headers["Authorization"] = key
    start, end = window(cfg)
    payload = ai_payload(cfg, start, end)
    params = x_params(cfg, start, end)
    ai = session.post(BASE + "/desearch/ai/search", json=payload, timeout=120)
    xres = session.get(BASE + "/twitter", params=params, timeout=90)
    raw = {
        "run_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "cfg": cfg,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "ai": {"status": ai.status_code, "body": _json(ai), "payload": payload},
        "x": {"status": xres.status_code, "body": _json(xres), "params": params},
    }
    return raw, key


def _json(response):
    try:
        return response.json()
    except ValueError:
        return {"_text": getattr(response, "text", "")[:500]}


def save_raw(raw, key):
    os.makedirs("evidence", exist_ok=True)
    path = "evidence/raw-%s.json" % raw["run_at"][:10]
    write_text(path, json.dumps(raw, indent=1), key)
    print("raw ->", path)


def _row(kind, where, link, text, when, author):
    return {
        "kind": kind,
        "where": where,
        "link": link,
        "snippet": snippet(text),
        "tone": tone_of(text),
        "date": when,
        "author": author,
        "text": text or "",
    }


def candidates(raw):
    rows = []
    for item in as_list(raw.get("ai", {}).get("body"), ("search", "search_results", "data")):
        link = item.get("link") or item.get("url") or ""
        text = " ".join(item.get(k) or "" for k in ("title", "snippet", "description"))
        host = host_of(link)
        if host in ("x.com", "twitter.com"):
            post_id = item.get("id") or ""
            rows.append(_row("x", "X", public_post_link(link, post_id), text, "", "a user"))
        else:
            rows.append(_row("web", host or "web", link, text, "", ""))
    for source in (raw.get("ai", {}).get("body"), raw.get("x", {}).get("body")):
        for post in as_list(source, ("tweets", "data", "results")):
            if not isinstance(post, dict) or "text" not in post and "id" not in post:
                continue
            if "text" not in post and "title" in post:
                continue
            user = post.get("user") or {}
            when = parse_time(post.get("created_at"))
            post_id = str(post.get("id") or "")
            rows.append(_row(
                "x", "X", public_post_link(post.get("url") or "", post_id),
                post.get("text") or "",
                when.date().isoformat() if when else "",
                "a user",
            ))
            rows[-1]["username"] = (user.get("username") or "").lstrip("@")
            rows[-1]["post_id"] = post_id
    for row in rows:
        row.setdefault("username", "")
        row.setdefault("post_id", "")
    return rows


def classify(raw):
    cfg = raw["cfg"]
    terms = cfg.get("brand_terms") or [cfg["brand"]]
    own = (cfg.get("own_account") or "").strip().lstrip("@").lower()
    domains = cfg.get("own_domains") or []
    kept, left = [], []
    seen = set()
    for row in candidates(raw):
        blob = " ".join([row["text"], row["snippet"], row["link"], row["where"]])
        key = row["post_id"] or row["link"] or row["snippet"]
        reason = ""
        if row["kind"] == "web" and on_own_domain(row["link"], domains):
            reason = "own domain"
        elif row["kind"] == "x" and own and row["username"].lower() == own:
            reason = "own account"
        elif key and key in seen:
            reason = "duplicate"
        elif not contains_term(blob, terms):
            reason = "other meaning"
        elif other_meaning(blob, cfg):
            reason = "other meaning"
        if reason:
            left.append({"link": row["link"], "where": row["where"], "reason": reason, "snippet": row["snippet"]})
            continue
        if key:
            seen.add(key)
        public = {k: row[k] for k in ("kind", "where", "link", "snippet", "tone", "date", "author")}
        kept.append(public)
    return kept, left


def build(raw, outdir, key=""):
    os.makedirs(outdir, exist_ok=True)
    kept, left = classify(raw)
    web_n = sum(1 for row in candidates(raw) if row["kind"] == "web")
    x_n = sum(1 for row in candidates(raw) if row["kind"] == "x")
    end = raw.get("end_date") or ""
    brand = raw["cfg"]["brand"]
    lines = [
        "# Brand mentions: %s" % brand,
        "",
        "Public pages and posts Desearch returned for %s on %s: %d web, %d X, %d kept." % (brand, end, web_n, x_n, len(kept)),
        "",
        "Authors of X posts are shown as a user.",
        "",
        "| Where | Link | Snippet | Tone | Date | Author |",
        "|---|---|---|---|---|---|",
    ]
    for row in kept:
        lines.append("| %s | %s | %s | %s | %s | %s |" % (
            row["where"], row["link"], row["snippet"].replace("|", "/"), row["tone"], row["date"], row["author"]))
    lines += ["", "## Left out", ""]
    if not left:
        lines.append("None.")
    for row in left:
        lines.append("- %s (%s): %s" % (row["where"], row["reason"], row["link"] or row["snippet"]))
    lines.append("")
    write_text(os.path.join(outdir, "mentions.md"), "\n".join(lines), key)
    fieldnames = ["where", "link", "snippet", "tone", "date", "author"]
    buf_rows = [{k: row[k] for k in fieldnames} for row in kept]
    import io
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(buf_rows)
    write_text(os.path.join(outdir, "mentions.csv"), buf.getvalue(), key)
    return kept, left


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("config", nargs="?", default="config.json")
    parser.add_argument("--from-raw")
    parser.add_argument("--out", default="output")
    args = parser.parse_args(argv)
    if args.from_raw:
        raw = json.load(open(args.from_raw))
        key = os.environ.get("DESEARCH_API_KEY", "").strip()
    else:
        raw, key = run_live(json.load(open(args.config)))
        save_raw(raw, key)
    kept, left = build(raw, args.out, key)
    print("kept", len(kept), "left out", len(left))


if __name__ == "__main__":
    main()
