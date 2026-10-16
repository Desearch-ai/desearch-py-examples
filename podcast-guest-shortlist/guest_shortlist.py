"""Podcast Guest Shortlist: people who post about a topic, plus past podcast pages.

Made by Desearch (https://desearch.ai).

Live:     python guest_shortlist.py config.json
Offline:  python guest_shortlist.py --from-raw evidence/raw-YYYY-MM-DD.json
"""
import argparse, csv, datetime as dt, io, json, os, re, sys

BASE = "https://api.desearch.ai"
NAME_STOP = {"with", "from", "that", "this", "your", "home", "user", "podcast"}


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


def window(cfg):
    end = dt.date.fromisoformat(cfg["today"]) if cfg.get("today") else dt.date.today()
    start = end - dt.timedelta(days=int(cfg.get("days", 30)))
    return start, end


def topic_query(terms):
    parts = ['"%s"' % term if " " in term else term for term in terms]
    return "(" + " OR ".join(parts) + ")"


def search_params(cfg, start, end):
    return {
        "query": topic_query(cfg["topic_terms"]),
        "sort": "Latest",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "min_likes": int(cfg.get("min_likes", 20)),
        "count": int(cfg.get("count", 50)),
    }


def user_params(cfg, account):
    return {"user": account, "query": topic_query(cfg["topic_terms"]), "count": int(cfg.get("per_user", 10))}


def contains_term(text, terms):
    low = (text or "").lower()
    return any(term.lower() in low for term in terms)


def name_tokens(name):
    words = re.findall(r"[A-Za-z]{4,}", name or "")
    return [word.lower() for word in words if word.lower() not in NAME_STOP]


def brandish(person, words):
    blob = "%s %s" % (person.get("name") or "", person.get("description") or "")
    blob = blob.lower()
    return any(word.lower() in blob for word in (words or []))


def excerpt(text, words=24):
    text = re.sub(r"@\w+", "", text or "")
    text = re.sub(r"\s+", " ", text).replace("\u2014", ", ").strip()
    return " ".join(text.split(" ")[:words])


def as_list(body):
    if isinstance(body, list):
        return [item for item in body if isinstance(item, dict)]
    if isinstance(body, dict):
        for key in ("data", "results", "organic_results"):
            if isinstance(body.get(key), list):
                return [item for item in body[key] if isinstance(item, dict)]
    return []


def _json(response):
    try:
        return response.json()
    except ValueError:
        return {"_text": getattr(response, "text", "")[:500]}


def pick_people(posts, cfg, start):
    start_dt = dt.datetime.combine(start, dt.time.min, tzinfo=dt.timezone.utc)
    grouped, kept = {}, 0
    for post in posts:
        when = parse_time(post.get("created_at"))
        text = post.get("text") or ""
        if not when or when < start_dt or not contains_term(text, cfg["topic_terms"]):
            continue
        user = post.get("user") or {}
        account = (user.get("username") or "").strip().lstrip("@")
        if not account:
            continue
        kept += 1
        person = grouped.get(account)
        if person is None:
            person = {
                "account": account,
                "name": user.get("name") or "",
                "description": user.get("description") or "",
                "posts": [],
                "likes": 0,
            }
            grouped[account] = person
        if user.get("name"):
            person["name"] = user["name"]
        if user.get("description"):
            person["description"] = user["description"]
        person["posts"].append(post)
        person["likes"] += int(post.get("like_count") or 0)
    ranked = sorted(grouped.values(), key=lambda person: (len(person["posts"]), person["likes"]), reverse=True)
    ranked = ranked[:int(cfg.get("max_people", 15))]
    for person in ranked:
        person["brand"] = brandish(person, cfg.get("brand_words"))
        person["tokens"] = name_tokens(person["name"])
    return kept, ranked


def page_matches(item, tokens):
    blob = " ".join(item.get(key) or "" for key in ("title", "snippet", "link")).lower()
    if "podcast" not in blob or not tokens:
        return False
    return any(token in blob for token in tokens)


def podcast_status(calls, tokens):
    if not calls:
        return "none found"
    pages = as_list(calls[0].get("body"))
    if any(page_matches(item, tokens) for item in pages):
        return "found"
    if len(calls) > 1 and any(page_matches(item, tokens) for item in as_list(calls[1].get("body"))):
        return "found after adding the topic"
    return "none found"


def on_topic_posts(body, terms, start):
    start_dt = dt.datetime.combine(start, dt.time.min, tzinfo=dt.timezone.utc)
    rows = []
    for post in as_list(body):
        text = post.get("text") or ""
        if not contains_term(text, terms):
            continue
        when = parse_time(post.get("created_at"))
        rows.append({"time": when, "text": text, "in_window": bool(when and when >= start_dt)})
    rows.sort(key=lambda row: row["time"] or dt.datetime.min.replace(tzinfo=dt.timezone.utc), reverse=True)
    return rows


def run_live(cfg, session=None):
    key = api_key()
    if session is None:
        import requests
        session = requests.Session()
    session.headers["Authorization"] = key
    start, end = window(cfg)
    params = search_params(cfg, start, end)
    search = session.get(BASE + "/twitter", params=params, timeout=90)
    search_body = _json(search)
    kept, people = pick_people(as_list(search_body), cfg, start)
    user_calls, web_calls = [], []
    for person in people:
        if person["brand"]:
            continue
        uparams = user_params(cfg, person["account"])
        ures = session.get(BASE + "/twitter/post/user", params=uparams, timeout=90)
        user_calls.append({"account": person["account"], "params": uparams, "status": ures.status_code, "body": _json(ures)})
        first_query = "%s podcast" % (person["name"] or "a user")
        first = session.get(BASE + "/web", params={"query": first_query}, timeout=90)
        first_body = _json(first)
        web_calls.append({"account": person["account"], "query": first_query, "status": first.status_code, "body": first_body})
        if not any(page_matches(item, person["tokens"]) for item in as_list(first_body)):
            second_query = "%s %s podcast" % (person["name"] or "a user", cfg["topic_name"])
            second = session.get(BASE + "/web", params={"query": second_query}, timeout=90)
            web_calls.append({
                "account": person["account"], "query": second_query, "status": second.status_code, "body": _json(second),
            })
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    raw = {
        "run_at": now,
        "cfg": cfg,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "search_kept": kept,
        "search_params": params,
        "people": people,
        "user_calls": user_calls,
        "web_calls": web_calls,
    }
    return raw, key


def save_raw(raw, key):
    os.makedirs("evidence", exist_ok=True)
    path = "evidence/raw-%s.json" % raw["run_at"][:10]
    write_text(path, json.dumps(raw, indent=1, default=str), key)
    print("raw ->", path)


def public_table(raw):
    cfg = raw["cfg"]
    start = dt.date.fromisoformat(raw["start_date"])
    calls_by, web_by = {}, {}
    for call in raw.get("user_calls") or []:
        calls_by.setdefault(call["account"], call)
    for call in raw.get("web_calls") or []:
        web_by.setdefault(call["account"], []).append(call)
    rows, skipped = [], []
    for person in raw.get("people") or []:
        if person.get("brand"):
            skipped.append("brand-style account")
            continue
        posts = on_topic_posts((calls_by.get(person["account"]) or {}).get("body"), cfg["topic_terms"], start)
        newest = posts[0]["time"].date().isoformat() if posts and posts[0]["time"] else ""
        label = "one post only" if len(posts) <= 1 else "person"
        rows.append({
            "n": len(rows) + 1,
            "person": "a user",
            "on_topic": len(posts),
            "in_window": sum(1 for post in posts if post["in_window"]),
            "newest": newest,
            "podcast": podcast_status(web_by.get(person["account"]) or [], person.get("tokens") or []),
            "label": label,
            "pitch": excerpt(posts[0]["text"]) if posts else "",
        })
    return rows, skipped


def build(raw, outdir, key=""):
    os.makedirs(outdir, exist_ok=True)
    rows, skipped = public_table(raw)
    checked = len(raw.get("people") or [])
    lines = [
        "# Podcast guest shortlist: %s" % raw["cfg"].get("topic_name", ""),
        "",
        "Public posts and pages Desearch returned for this search on %s: %d posts, %d people checked."
        % (raw.get("end_date") or "", raw.get("search_kept") or 0, checked),
        "",
        "Each person is shown as a user. Personal post links are left out.",
        "",
        "| # | Person | On-topic posts | In window | Newest | Past podcast pages | Label | Pitch angle |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append("| %d | %s | %d | %d | %s | %s | %s | %s |" % (
            row["n"], row["person"], row["on_topic"], row["in_window"], row["newest"],
            row["podcast"], row["label"], row["pitch"].replace("|", "/")))
    lines += ["", "## Skipped", ""]
    if not skipped:
        lines.append("None.")
    for reason in skipped:
        lines.append("- %s" % reason)
    lines += [
        "",
        "The host reviews each row and reaches out personally. This list has no contact details and no outreach.",
        "",
    ]
    write_text(os.path.join(outdir, "shortlist.md"), "\n".join(lines), key)
    fieldnames = ["n", "person", "on_topic", "in_window", "newest", "podcast", "label", "pitch"]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    write_text(os.path.join(outdir, "guests.csv"), buf.getvalue(), key)
    return rows, skipped


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
    rows, skipped = build(raw, args.out, key)
    print("rows", len(rows), "skipped", len(skipped))


if __name__ == "__main__":
    main()
