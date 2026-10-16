"""X Keyword Monitor: public posts since the last check for a few keywords.

Made by Desearch (https://desearch.ai).

Live:     python keyword_monitor.py config.json
Offline:  python keyword_monitor.py --from-raw evidence/raw-YYYY-MM-DD.json
"""
import argparse, csv, datetime as dt, io, json, os, re, sys

BASE = "https://api.desearch.ai"


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
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d"):
        try:
            found = dt.datetime.strptime(s, fmt)
            if found.tzinfo is None:
                found = found.replace(tzinfo=dt.timezone.utc)
            return found.astimezone(dt.timezone.utc)
        except ValueError:
            continue
    return None


def keyword_query(keywords):
    parts = ['"%s"' % term if " " in term else term for term in keywords]
    return "(" + " OR ".join(parts) + ")"


def x_params(cfg, now):
    last = parse_time(cfg["last_check"])
    return {
        "query": keyword_query(cfg["keywords"]),
        "sort": "Latest",
        "start_date": last.date().isoformat(),
        "end_date": now.date().isoformat(),
        "min_likes": int(cfg.get("min_likes", 5)),
        "count": int(cfg.get("count", 20)),
    }


def public_post_link(url, post_id=""):
    if post_id:
        return "https://x.com/i/status/%s" % post_id
    match = re.search(r"/status/(\d+)", url or "")
    if match:
        return "https://x.com/i/status/%s" % match.group(1)
    return ""


def excerpt(text, words=20):
    text = re.sub(r"@\w+", "", text or "")
    text = re.sub(r"\s+", " ", text).replace("\u2014", ", ").strip()
    return " ".join(text.split(" ")[:words])


def link_only(text):
    stripped = re.sub(r"https?://\S+", " ", text or "")
    stripped = re.sub(r"www\.\S+", " ", stripped)
    return re.sub(r"[^\w]+", "", stripped) == ""


def matched_keyword(text, keywords):
    low = (text or "").lower()
    for term in keywords:
        if term.lower() in low:
            return term
    return ""


def as_posts(body):
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("data", "results", "tweets"):
            if isinstance(body.get(key), list):
                return body[key]
    return []


def run_live(cfg, session=None, now=None):
    key = api_key()
    if session is None:
        import requests
        session = requests.Session()
    session.headers["Authorization"] = key
    if now is None:
        now = parse_time(cfg["now"]) if cfg.get("now") else dt.datetime.now(dt.timezone.utc)
    params = x_params(cfg, now)
    res = session.get(BASE + "/twitter", params=params, timeout=90)
    try:
        body = res.json()
    except ValueError:
        body = {"_text": getattr(res, "text", "")[:500]}
    raw = {
        "run_at": now.isoformat(timespec="seconds"),
        "now": now.isoformat(timespec="seconds"),
        "last_check": cfg["last_check"],
        "cfg": cfg,
        "x": {"status": res.status_code, "body": body, "params": params},
    }
    return raw, key


def save_raw(raw, key):
    os.makedirs("evidence", exist_ok=True)
    path = "evidence/raw-%s.json" % raw["run_at"][:10]
    write_text(path, json.dumps(raw, indent=1), key)
    print("raw ->", path)


def collect(raw):
    last = parse_time(raw["last_check"])
    keywords = raw["cfg"]["keywords"]
    returned, seen = [], set()
    for post in as_posts(raw.get("x", {}).get("body")):
        post_id = str(post.get("id") or "")
        if post_id and post_id in seen:
            continue
        if post_id:
            seen.add(post_id)
        when = parse_time(post.get("created_at"))
        text = post.get("text") or ""
        returned.append({
            "id": post_id,
            "time_dt": when,
            "time": when.strftime("%Y-%m-%d %H:%M") if when else "",
            "text": text,
            "excerpt": excerpt(text),
            "likes": int(post.get("like_count") or 0),
            "link": public_post_link(post.get("url") or "", post_id),
            "author": "a user",
            "newer": bool(when and last and when > last),
        })
    new = [row for row in returned if row["newer"]]
    kept = []
    for row in new:
        if link_only(row["text"]):
            row["drop"] = "link only"
            continue
        term = matched_keyword(row["text"], keywords)
        if not term:
            row["drop"] = "no keyword"
            continue
        row["keyword"] = term
        kept.append(row)
    kept.sort(key=lambda row: row["time_dt"], reverse=True)
    return returned, new, kept


def summary_lines(kept, keywords):
    counts = ["%s (%d)" % (term, sum(1 for row in kept if row["keyword"] == term)) for term in keywords]
    lines = ["%d posts kept." % len(kept), "Keywords: %s." % ", ".join(counts)]
    if kept:
        lines.append("Newest %s UTC, oldest kept %s UTC." % (kept[0]["time"], kept[-1]["time"]))
    else:
        lines.append("No posts were newer than the last check.")
    return lines


def build(raw, outdir, key=""):
    os.makedirs(outdir, exist_ok=True)
    returned, new, kept = collect(raw)
    keywords = raw["cfg"]["keywords"]
    lines = [
        "# X keyword monitor",
        "",
        "Public posts Desearch returned for these keywords between %s and %s: %d returned, %d new, %d kept."
        % (raw["last_check"], raw["now"], len(returned), len(new), len(kept)),
        "",
        "Query: `%s`. Authors of X posts are shown as a user." % keyword_query(keywords),
        "",
        "| Time (UTC) | Keyword | Likes | Excerpt | Author |",
        "|---|---|---|---|---|",
    ]
    for row in kept:
        lines.append("| %s | %s | %d | %s | %s |" % (
            row["time"], row["keyword"], row["likes"], row["excerpt"].replace("|", "/"), row["author"]))
    lines += ["", "## Summary", ""]
    for line in summary_lines(kept, keywords):
        lines.append("- " + line)
    lines += ["", "Next LAST CHECK: %s" % raw["now"], ""]
    write_text(os.path.join(outdir, "monitor.md"), "\n".join(lines), key)
    fieldnames = ["time", "keyword", "likes", "excerpt", "author", "link"]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows([{name: row[name] for name in fieldnames} for row in kept])
    write_text(os.path.join(outdir, "posts.csv"), buf.getvalue(), key)
    return returned, new, kept


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
    returned, new, kept = build(raw, args.out, key)
    print("returned", len(returned), "new", len(new), "kept", len(kept))


if __name__ == "__main__":
    main()
