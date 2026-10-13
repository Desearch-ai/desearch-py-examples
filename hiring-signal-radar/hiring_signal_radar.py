#!/usr/bin/env python3
"""Hiring Signal Radar (made by Desearch, https://desearch.ai).

Collects public posts and job pages found by search for one role, extracts company, role,
location and date, scores each company and writes a ranked CSV plus an
"accounts worth researching" list.

  python hiring_signal_radar.py --role "data analyst"
  python hiring_signal_radar.py --from-raw output/raw-<date>-<role>.json      # offline, no API calls
"""
import argparse, csv, datetime as dt, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import urlparse

import requests

API = "https://api.desearch.ai"
TZ = dt.timezone(dt.timedelta(hours=4))  # Asia/Tbilisi, used for log timestamps
BILL = ["X-Desearch-Cost-Usd", "X-Desearch-Usage-Count", "X-Desearch-Service", "X-Desearch-Currency"]
DEFAULT_X = ['"we\'re hiring" "{role}"', '"we are hiring" "{role}"', '"is hiring" "{role}"']
DEFAULT_BOARDS = ["boards.greenhouse.io", "job-boards.greenhouse.io", "jobs.lever.co", "jobs.ashbyhq.com"]
JOB_URL = {
    "greenhouse.io": re.compile(r"greenhouse\.io/([^/?#]+)/jobs/(\d+)"),
    "jobs.lever.co": re.compile(r"jobs\.lever\.co/([^/?#]+)/([0-9a-f]{8}-[0-9a-f-]{27})"),
    "jobs.ashbyhq.com": re.compile(r"jobs\.ashbyhq\.com/([^/?#]+)/([0-9a-f]{8}-[0-9a-f-]{27})"),
}

# ---------------------------------------------------------------- API calls
class Client:
    def __init__(self, key):
        self.key, self.calls = key, []

    def get(self, phase, path, params, timeout=120):
        t0 = time.time()
        try:
            r = requests.get(API + path, params=params, headers={"Authorization": self.key}, timeout=timeout)
            status, headers, text = r.status_code, r.headers, r.text
        except requests.RequestException as e:
            status, headers, text = 0, {}, str(e)
        try:
            body = json.loads(text)
        except ValueError:
            body = text
        rec = {"ts": dt.datetime.now(TZ).isoformat(timespec="seconds"), "phase": phase, "path": path, "params": params,
               "status": status, "latency_s": round(time.time() - t0, 2),
               "cost_usd": headers.get(BILL[0]), "usage": headers.get(BILL[1]), "service": headers.get(BILL[2]),
               "currency": headers.get(BILL[3])}
        if isinstance(body, list):
            rec["items"] = len(body)
        elif isinstance(body, dict) and isinstance(body.get("data"), list):
            rec["items"] = len(body["data"])
        elif isinstance(body, str) and status == 200:
            rec["items"] = 1 if body.strip() else 0
        else:
            rec["items"] = 0
        self.calls.append(rec)
        print(f"  {rec['ts'][11:19]} {phase:8} {status} {rec['latency_s']:>6}s items={rec['items']} usage={rec['usage']} cost={rec['cost_usd']}", flush=True)
        return status, body


def collect(args, key):
    c = Client(key)
    today = dt.date.fromisoformat(args.today) if args.today else dt.datetime.now(dt.timezone.utc).date()
    fresh_start = today - dt.timedelta(days=args.fresh_days)
    windows = [("recent", fresh_start, None), ("older", today - dt.timedelta(days=args.days), fresh_start - dt.timedelta(days=1))]
    raw = {"meta": {"role": args.role, "today": str(today), "days": args.days, "fresh_days": args.fresh_days,
                    "collected_at": dt.datetime.now(TZ).isoformat(timespec="seconds")},
           "x": [], "web": [], "pages": []}
    xq = [q.format(role=args.role) for q in (args.x_query or DEFAULT_X)]
    if args.x_keyword:
        xq.append(f'hiring "{args.role}" ({args.x_keyword})')
    print(f"X search: {len(xq)} queries x {len(windows)} windows, sort={args.sort}, count={args.x_count}")
    for q in xq:
        for wname, s, e in windows:
            p = {"query": q, "sort": args.sort, "count": args.x_count, "start_date": str(s)}
            if e:
                p["end_date"] = str(e)
            st, body = c.get("x", "/twitter", p)
            raw["x"].append({"query": q, "window": wname, "params": p, "status": st, "posts": body if isinstance(body, list) else [], "error": None if isinstance(body, list) else body})
    wq = [f"{args.role} site:{b}" for b in args.boards]
    if args.web_keyword:
        wq += [f"{args.role} {args.web_keyword} site:{b}" for b in args.boards]
    print(f"Web search: {len(wq)} queries, start={args.web_start}")
    for q in wq:
        for s in args.web_start:
            st, body = c.get("web", "/web", {"query": q, "start": s})
            if st >= 500:
                st, body = c.get("web", "/web", {"query": q, "start": s})
            res = body.get("data", []) if isinstance(body, dict) else []
            raw["web"].append({"query": q, "start": s, "status": st, "results": res})
    pages, seen = [], set()
    for rank in range(1, 101):  # round-robin by rank, so --max-pages takes the top results of every query
        for w in raw["web"]:
            if rank > len(w["results"]):
                continue
            r = w["results"][rank - 1]
            jid = job_id(r.get("link", ""))
            if jid and jid not in seen:
                seen.add(jid)
                pages.append({"url": r["link"], "title": r.get("title", ""), "query": w["query"], "rank": rank, "job_id": jid})
    pages = pages[: args.max_pages]
    print(f"Extract: {len(pages)} job pages, js=false, format=text (retry once), html only for the date")

    def read(pg):
        tries = []
        text = None
        for attempt in (1, 2):
            st, body = c.get("extract", "/web/extract", {"url": pg["url"], "format": "text", "js": "false"})
            ok = st == 200 and isinstance(body, str) and len(body.strip()) > 0
            tries.append({"try": attempt, "format": "text", "status": st, "chars": len(body) if isinstance(body, str) else 0,
                          "detail": body.get("detail") if isinstance(body, dict) else None})
            if ok:
                text = body
                break
        meta = {}
        if text is not None and args.html_dates and not find_date(text):
            st, body = c.get("extract", "/web/extract", {"url": pg["url"], "format": "html", "js": "false"})
            tries.append({"try": len(tries) + 1, "format": "html", "status": st, "chars": len(body) if isinstance(body, str) else 0,
                          "detail": body.get("detail") if isinstance(body, dict) else None})
            if st == 200 and isinstance(body, str):
                meta = html_meta(body)
        return dict(pg, tries=tries, text=text, html_meta=meta)

    with ThreadPoolExecutor(args.workers) as ex:
        raw["pages"] = list(ex.map(read, pages))
    raw["calls"] = c.calls
    return raw

# ---------------------------------------------------------------- parsing
def job_id(url):
    for host, rx in JOB_URL.items():
        m = rx.search(url)
        if m:
            return f"{host}:{m.group(1).lower()}:{m.group(2)}"
    return None


def html_meta(h):
    out = {}
    m = re.search(r'"datePosted"\s*:\s*"([^"]+)"', h)
    if m:
        out["datePosted"] = m.group(1)
    m = re.search(r'<link rel="canonical" href="([^"]+)"', h)
    if m:
        out["canonical"] = m.group(1)
    m = re.search(r'"addressLocality"\s*:\s*"([^"]+)"', h)
    if m:
        out["locality"] = m.group(1)
    m = re.search(r"<title>(.*?)</title>", h, re.S)
    if m:
        out["title"] = unescape(m.group(1)).strip()[:200]
    out["html_chars"] = len(h)
    return out


DATE_RX = [
    re.compile(r"(?:posted|date posted|published|posting date)\s*(?:on)?\s*[:\-]?\s*(\d{4}-\d{2}-\d{2})", re.I),
    re.compile(r"(?:posted|date posted|published|posting date)\s*(?:on)?\s*[:\-]?\s*([A-Z][a-z]{2,8}\.? \d{1,2},? \d{4})", re.I),
    re.compile(r"(?:posted|date posted|published|posting date)\s*(?:on)?\s*[:\-]?\s*(\d{1,2} [A-Z][a-z]{2,8}\.? \d{4})", re.I),
    re.compile(r"posted\s+(\d+)\s+(day|days|week|weeks|month|months)\s+ago", re.I),
]


def find_date(text):
    for rx in DATE_RX:
        m = rx.search(text or "")
        if m:
            return m.group(0)
    return None


def parse_date(s, today):
    if not s:
        return None
    m = re.search(r"posted\s+(\d+)\s+(day|week|month)", s, re.I)
    if m:
        n = int(m.group(1)) * {"day": 1, "week": 7, "month": 30}[m.group(2).lower()]
        return today - dt.timedelta(days=n)
    m = re.search(r"\d{4}-\d{2}-\d{2}", s)
    if m:
        return dt.date.fromisoformat(m.group(0))
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y"):
        m = re.search(r"[A-Z][a-z]{2,8}\.? \d{1,2},? \d{4}|\d{1,2} [A-Z][a-z]{2,8}\.? \d{4}", s)
        if m:
            try:
                return dt.datetime.strptime(m.group(0).replace(".", ""), fmt).date()
            except ValueError:
                continue
    return None


AGENCY_RX = re.compile(r"\bjobs?\b|jobs|career(?!s at)|recruit|talent|staffing|vacanc|opportunit|internship|scholarship|"
                       r"lowker|employment|hiring|hire|headhunt|placement|job ?board|aggregator", re.I)
AGENCY_CAT = re.compile(r"recruit|employment|staffing|talent|professional services|education", re.I)
ORG_RX = re.compile(r"\b(ltd|limited|inc|llc|pvt|plc|gmbh|corp|group|labs?|network|scientific|digital|technolog|"
                    r"solutions|systems|foundation|university|institute|party|protocol|capital|finance|dao|exchange|"
                    r"careers|team|official|hq|agency|studio|analytics|data|research|bank|health|media)\b|\.ai\b|\.xyz\b", re.I)
CAREERS_RX = re.compile(r"join (?:our|the) team|our team|work with us|careers at|jobs at|@\w+\. join", re.I)


def classify_poster(u, text):
    """company | agency (recruiter, agency, job board, job-sharing account) | individual. Heuristic."""
    name, handle, desc = u.get("name") or "", u.get("username") or "", u.get("description") or ""
    prof = u.get("professional") or {}
    ptype = prof.get("professional_type")
    cats = " ".join(c.get("name", "") for c in prof.get("category") or [])
    ident = f"{name} {handle}"
    if re.search(r"careers|jobs", name, re.I) and CAREERS_RX.search(desc):
        return "company"  # an employer's own careers account
    if AGENCY_RX.search(ident) or AGENCY_RX.search(desc[:120]) or (ptype == "Business" and AGENCY_CAT.search(cats)):
        return "agency"
    if re.search(r"\b(our|my) client\b|client hiring|a (growing|leading|fast[- ]growing) [\w\- ]*compan", text, re.I):
        return "agency"
    if ptype == "Business" or ORG_RX.search(name) or (name.replace(".", "").strip().lower() == handle.lower() and len(name) > 2):
        return "company"
    return "individual"


ROLE_WORDS = r"(?:(?:(?i:senior|sr\.?|junior|jr\.?|lead|associate|principal|staff|graduate|entry[- ]level|remote|" \
             r"financial|finance|business|marketing|product|research|commercial|technical|growth|bi|crm|hr|healthcare|" \
             r"blockchain|crypto|web3|on-?chain|quantitative)|[A-Z][\w&\-]+)\s+){0,3}"


def role_title(text, role):
    m = re.search(r"(" + ROLE_WORDS + r"(?i:" + re.escape(role) + r"s?(?:\s+intern(?:ship)?)?))", text)
    return re.sub(r"\s+", " ", m.group(1)).strip(" -|:") if m else None


COMPANY_PATTERNS = [
    re.compile(r"(?i:company|organisation|organization|employer)\s*[:\-–]\s*@?([A-Z][\w&.'\-]*(?: [A-Z&][\w&.'\-]*){0,3})"),
    re.compile(r"(@\w{2,30}|[A-Z][\w&.'\-]*(?: [A-Z][\w&.'\-]*){0,3}) is (?:now |currently |actively )?hiring"),
    re.compile(r"(?i:we are hiring|we're hiring|we’re hiring) at @?([A-Z][\w&.'\-]*(?: [A-Z][\w&.'\-]*){0,3})"),
    re.compile(r"\bjoin @?([A-Z][\w&.'\-]*(?: [A-Z][\w&.'\-]*){0,2}) as\b"),
    re.compile(r"(?i:needed|wanted) at @?([A-Z][\w&.'\-]*(?: [A-Z][\w&.'\-]*){0,3})"),
]
STOP_COMPANY = {"we", "who", "it", "this", "our", "company", "the company", "a", "my", "hiring", "urgent", "now", "she", "he",
                "they", "team", "everyone", "remote", "job", "role", "location", "salary"}


def company_from_text(text):
    for rx in COMPANY_PATTERNS:
        m = rx.search(text)
        if m:
            c = m.group(1).strip(" .,-–|:'’").strip()
            c = re.split(r"\s+(?:is|are|has|in|for|and|to|with|now)\b", c)[0].strip()
            if c and c.lower() not in STOP_COMPANY and len(c) > 1:
                return c
    return None


def location_from_text(text):
    m = re.search(r"(?:📍\s*)?location\s*[:\-–]\s*([^\n|💰💵📧◽•✅]{2,60})", text, re.I) or re.search(r"📍\s*([^\n|💰💵◽•✅]{2,60})", text)
    if m:
        return m.group(1).strip(" .,-*")
    m = re.search(r"\b(?:hiring|based) in ([A-Z][\w\-]+(?:,? [A-Z][\w\-]+){0,2})", text)
    if m:
        return m.group(1)
    if re.search(r"\bremote\b", text, re.I):
        return "Remote"
    return None


def norm_company(c):
    c = (c or "").lower().lstrip("@")
    c = re.sub(r"\.(ai|com|io|xyz|co)\b", "", c)
    c = re.sub(r"\b(inc|ltd|limited|llc|pvt|plc|gmbh|corp|careers|jobs|technologies|technology|private|official|hq|team)\b", "", c)
    c = re.sub(r"\b\d{2,}\b", "", c)  # board slugs such as techstars57
    return re.sub(r"[^a-z0-9]", "", c)


def x_date(s):
    try:
        return parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None


def parse_x(raw, role, labels):
    today = dt.date.fromisoformat(raw["meta"]["today"])
    posts, checks = {}, []
    for blk in raw["x"]:
        ds = [x_date(p.get("created_at")) for p in blk["posts"]]
        ds_ok = [d for d in ds if d]
        s = dt.date.fromisoformat(blk["params"]["start_date"])
        e = dt.date.fromisoformat(blk["params"]["end_date"]) if blk["params"].get("end_date") else None
        out = sum(1 for d in ds_ok if d.date() < s or (e and d.date() > e))
        desc = all(ds_ok[i] >= ds_ok[i + 1] for i in range(len(ds_ok) - 1))
        checks.append({"query": blk["query"], "window": blk["window"], "start_date": str(s), "end_date": str(e or ""),
                       "status": blk["status"], "returned": len(blk["posts"]), "count": blk["params"]["count"],
                       "oldest": min(ds_ok).isoformat() if ds_ok else "", "newest": max(ds_ok).isoformat() if ds_ok else "",
                       "outside_window": out, "sorted_newest_first": desc})
        for p in blk["posts"]:
            if p["id"] in posts:
                posts[p["id"]]["queries"].append(blk["query"])
                continue
            u, text = p.get("user") or {}, unescape(p.get("text") or "")
            rt = role_title(text, role)
            ptype = labels.get((u.get("username") or "").lower()) or classify_poster(u, text)
            comp = (u.get("name") if ptype == "company" else None) or company_from_text(text)
            comp_src = "poster" if ptype == "company" else ("text" if comp else "")
            d = x_date(p.get("created_at"))
            posts[p["id"]] = {
                "source": "x", "id": p["id"], "date": d.date().isoformat() if d else "", "queries": [blk["query"]],
                "poster_type": ptype, "poster_type_heuristic": classify_poster(u, text),
                "company": re.sub(r"\s+", " ", comp or "").strip().lstrip("@"), "company_source": comp_src,
                "company_handle": u.get("username") if ptype == "company" else "",
                "role": rt or "", "role_match": bool(rt), "location": location_from_text(text) or "",
                "is_retweet": bool(p.get("is_retweet")), "likes": p.get("like_count") or 0,
                # individuals' handles never leave this function: their links use the handle-free status URL
                "url": p.get("url") if ptype == "company" else f"https://x.com/i/status/{p['id']}",
                "age_days": (today - d.date()).days if d else None,
            }
    return list(posts.values()), checks


def company_from_page(pg):
    title, url = unescape(pg.get("title") or ""), pg["url"]
    slug = pg["job_id"].split(":")[1]
    m = re.search(r"Job Application for (.+?) at (.+)$", title) or None
    if m:
        return m.group(2).replace(" Careers", "").strip(), m.group(1).strip()
    m = re.search(r"^(.+?) @ (.+)$", title)
    if m:
        return m.group(2).strip(), m.group(1).strip()
    m = re.search(r"^(.+?) - (.+)$", title)
    if m and "lever.co" in url:
        a, b = m.group(1).strip(), m.group(2).strip()
        if norm_company(a) and norm_company(a)[:4] in slug.replace("-", "").lower():
            return a, b
        return b, a
    m = re.search(r"^(.+?) \| (.+?) Careers", title)
    if m:
        return m.group(2).strip(), m.group(1).strip()
    return slug.replace("-", " ").title(), title


def parse_pages(raw, role):
    today = dt.date.fromisoformat(raw["meta"]["today"])
    out = []
    for pg in raw["pages"]:
        comp, rtitle = company_from_page(pg)
        text = pg.get("text")
        meta = pg.get("html_meta") or {}
        first = pg["tries"][0]
        text_tries = [t for t in pg["tries"] if t["format"] == "text"]
        date_str = find_date(text) if text else None
        date_src = "text" if date_str else ""
        if not date_str and meta.get("datePosted"):
            date_str, date_src = meta["datePosted"], "html datePosted"
        d = parse_date(date_str, today)
        loc = ""
        if text:
            m = re.search(r"location\s*:\s*([^\n|]{2,60})", text, re.I)
            loc = m.group(1).strip() if m else ""
        if not loc and meta.get("locality"):
            loc = meta["locality"]
        if not loc and re.search(r"\bremote\b", rtitle, re.I):
            loc = "Remote"
        if text is None:
            state = "no text"
        elif meta.get("html_chars"):
            # html read: a closed posting redirects to the company's board (canonical ...?error=true, title "Jobs at ...")
            closed = "error=true" in (meta.get("canonical") or "") or (meta.get("title") or "").startswith("Jobs at")
            state = "closed" if closed else "open"
        else:
            # text only: the job text should name the role
            state = "open" if re.search(re.escape(role), text, re.I) else "closed"
        rt = role_title(rtitle, role) or role_title(text or "", role)
        out.append({
            "source": "web", "id": pg["job_id"], "url": pg["url"], "board": pg["job_id"].split(":")[0], "query": pg["query"],
            "rank": pg["rank"], "company": comp, "role": rt or rtitle[:80], "role_match": bool(rt), "location": loc,
            "date": d.isoformat() if d else "", "date_source": date_src, "age_days": (today - d).days if d else None,
            "page_state": state, "first_try": f"{first['status']}:{first['chars']}",
            "text_tries": len(text_tries), "text_ok_try": next((t["try"] for t in text_tries if t["status"] == 200 and t["chars"]), ""),
            "html_try": next((f"{t['status']}:{t['chars']}" for t in pg["tries"] if t["format"] == "html"), ""),
            "chars": len(text) if text else 0,
        })
    return out

# ---------------------------------------------------------------- scoring
def freshness(age, days, fresh):
    if age is None:
        return 0.25
    if age <= fresh:
        return 1.0
    if age <= days:
        return 0.5
    return 0.0


def score(posts, pages, meta, exclude):
    days, fresh = meta["days"], meta["fresh_days"]
    comps = {}
    for s in posts + pages:
        if s["source"] == "web" and s["page_state"] != "open":
            continue
        if not s["company"]:
            continue
        k = norm_company(s["company"])
        if not k or k in exclude:
            continue
        c = comps.setdefault(k, {"company": s["company"], "signals": [], "names": set()})
        c["names"].add(s["company"])
        c["signals"].append(s)
    rows = []
    for k, c in comps.items():
        sig = c["signals"]
        roles = {re.sub(r"\W+", " ", (s["role"] or "").lower()).strip() for s in sig if s["role"]}
        src = {s["source"] for s in sig}
        rel = max(1.0 if s["role_match"] else 0.5 for s in sig)
        fr = max(freshness(s["age_days"], days, fresh) for s in sig)
        cluster = min(len(roles), 3)
        corr = 2 if src == {"x", "web"} else 0
        own = 1 if any(s["source"] == "x" and s["poster_type"] == "company" for s in sig) else 0
        total = round(3 * rel + 3 * fr + cluster + corr + own, 2)
        ages = [s["age_days"] for s in sig if s["age_days"] is not None]
        name = sorted(c["names"], key=lambda n: (-sum(1 for s in sig if s["company"] == n), len(n)))[0]
        rows.append({
            "company": name, "score": total, "signals": len(sig), "x_posts": sum(s["source"] == "x" for s in sig),
            "job_pages": sum(s["source"] == "web" for s in sig), "distinct_roles": len(roles),
            "roles": "; ".join(sorted(roles))[:200], "newest_age_days": min(ages) if ages else "",
            "locations": "; ".join(sorted({s["location"] for s in sig if s["location"]}))[:120],
            "own_account_post": bool(own), "corroborated_x_and_web": bool(corr),
            "sources": " ".join(sorted({s["url"] for s in sig}))[:900],
        })
    rows.sort(key=lambda r: (-r["score"], r["newest_age_days"] if r["newest_age_days"] != "" else 999, r["company"].lower()))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows

# ---------------------------------------------------------------- output
def redact(s, words):
    for w in words:
        s = re.sub(re.escape(w), "[redacted]", s, flags=re.I)
    return s


def write_outputs(raw, args):
    meta = raw["meta"]
    labels = load_labels(args.labels)
    if "records" in raw:  # slim raw: parsed records saved by an earlier run
        posts, pages, xchecks, webchecks = raw["records"]["posts"], raw["records"]["pages"], raw["records"]["x_checks"], raw["records"]["web_checks"]
    else:
        posts, xchecks = parse_x(raw, meta["role"], labels)
        pages = parse_pages(raw, meta["role"])
        webchecks = []
        for w in raw["web"]:
            site = re.search(r"site:(\S+)", w["query"])
            on = sum(1 for r in w["results"] if site and urlparse(r.get("link", "")).netloc.endswith(site.group(1)))
            webchecks.append({"query": w["query"], "start": w["start"], "status": w["status"], "results": len(w["results"]),
                              "on_site": on, "job_pages": sum(1 for r in w["results"] if job_id(r.get("link", "")))})
    exclude = {norm_company(x) for x in args.exclude}
    rows = score(posts, pages, meta, exclude)
    slug = re.sub(r"[^a-z0-9]+", "-", meta["role"].lower()).strip("-")
    date = meta["today"]
    os.makedirs(args.out, exist_ok=True)
    base = os.path.join(args.out, f"{date}-{slug}")
    pub_pages = [dict(p, company=redact(p["company"], args.redact), role=redact(p["role"], args.redact)) for p in pages
                 if norm_company(p["company"]) not in exclude]
    pub_posts = [p for p in posts if norm_company(p["company"]) not in exclude]
    write_csv(base + "-companies.csv", rows, ["rank", "company", "score", "signals", "x_posts", "job_pages", "distinct_roles", "roles",
                                               "newest_age_days", "locations", "own_account_post", "corroborated_x_and_web", "sources"])
    write_csv(base + "-x-posts.csv", pub_posts, ["id", "date", "age_days", "poster_type", "company", "company_source", "company_handle",
                                                 "role", "role_match", "location", "is_retweet", "likes", "url"])
    write_csv(base + "-job-pages.csv", pub_pages, ["id", "board", "rank", "company", "role", "role_match", "location", "date", "date_source",
                                                   "age_days", "page_state", "first_try", "text_tries", "text_ok_try", "html_try", "chars", "url"])
    write_csv(base + "-costs.csv", raw.get("calls", []), ["ts", "phase", "path", "status", "latency_s", "items", "usage", "cost_usd", "service"])
    stats = summary(pub_posts, pub_pages, xchecks, webchecks, raw.get("calls", []), rows)
    write_report(base + "-accounts.md", meta, rows, stats, args)
    chart(base + "-roles-per-company.png", rows[:15])
    # slim raw: parsed records only (no post text, no individual handles), enough for --from-raw
    if "records" not in raw:
        def scrub(c):  # drop URLs of excluded companies from the public call log
            u = c.get("params", {}).get("url", "")
            jid = job_id(u)
            if jid and norm_company(jid.split(":")[1]) in exclude:
                c = dict(c, params=dict(c["params"], url="[excluded]"))
            return c
        slim = {"meta": meta, "calls": [scrub(c) for c in raw.get("calls", [])],
                "records": {"posts": pub_posts, "pages": pub_pages, "x_checks": xchecks, "web_checks": webchecks}}
        json.dump(slim, open(os.path.join(args.out, f"raw-{date}-{slug}.json"), "w"), indent=1, ensure_ascii=False)
    print(json.dumps(stats, indent=1))
    print("wrote", base + "-*.csv/.md/.png")
    return stats


def summary(posts, pages, xchecks, webchecks, calls, rows):
    pt = {}
    for p in posts:
        pt[p["poster_type"]] = pt.get(p["poster_type"], 0) + 1
    states = {}
    for p in pages:
        states[p["page_state"]] = states.get(p["page_state"], 0) + 1
    first_empty = sum(1 for p in pages if not p["first_try"].startswith("200:") or p["first_try"] == "200:0")
    after_retry = sum(1 for p in pages if p["page_state"] == "no text")
    open_pages = [p for p in pages if p["page_state"] == "open"]
    cost = sum(float(c["cost_usd"] or 0) for c in calls)
    return {
        "x_posts_unique": len(posts), "x_returned_total": sum(c["returned"] for c in xchecks),
        "poster_types": pt, "x_with_company": sum(1 for p in posts if p["company"]),
        "x_role_match": sum(1 for p in posts if p["role_match"]),
        "x_outside_window": sum(c["outside_window"] for c in xchecks),
        "x_calls_sorted_newest_first": f"{sum(c['sorted_newest_first'] for c in xchecks)}/{len(xchecks)}",
        "web_results": sum(w["results"] for w in webchecks), "web_on_site": sum(w["on_site"] for w in webchecks),
        "job_pages_read": len(pages), "page_states": states, "extract_first_try_no_text": first_empty,
        "extract_no_text_after_retry": after_retry,
        "open_pages_with_date": f"{sum(1 for p in open_pages if p['date'])}/{len(open_pages)}",
        "open_pages_with_location": f"{sum(1 for p in open_pages if p['location'])}/{len(open_pages)}",
        "companies": len(rows), "calls": len(calls), "cost_usd": round(cost, 5),
    }


def write_csv(path, rows, cols):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def write_report(path, meta, rows, st, args):
    top = [r for r in rows if r["score"] >= args.min_score][: args.top]
    L = [f"# Accounts worth researching: {meta['role']}, {meta['today']}", "",
         "Made by [Desearch](https://desearch.ai). Built from public posts and job pages found by search.", "",
         f"Window: the last {meta['days']} days (fresh = the last {meta['fresh_days']} days). "
         f"Sample: {st['x_posts_unique']} unique X posts, {st['job_pages_read']} job pages read "
         f"({st['page_states'].get('open', 0)} open), {st['companies']} companies.", "",
         "Score = 3 x role match + 3 x freshness + distinct roles (max 3) + 2 if both an X post and a job page + 1 if the company posted from its own account.", "",
         "| # | Company | Score | X posts | Job pages | Newest (days) | Roles | Locations | Why |", "|---|---|---|---|---|---|---|---|---|"]
    for r in top:
        why = []
        if r["corroborated_x_and_web"]:
            why.append("X post and job page")
        if r["own_account_post"]:
            why.append("own account")
        if r["distinct_roles"] > 1:
            why.append(f"{r['distinct_roles']} roles")
        if r["newest_age_days"] != "" and r["newest_age_days"] <= meta["fresh_days"]:
            why.append("fresh")
        if r["newest_age_days"] == "":
            why.append("no date found")
        L.append(f"| {r['rank']} | {r['company']} | {r['score']} | {r['x_posts']} | {r['job_pages']} | {r['newest_age_days']} | "
                 f"{r['roles'][:60]} | {r['locations'][:40]} | {', '.join(why)} |")
    L += ["", "Sources per company: see the `sources` column in the companies CSV.", "",
          "A hiring post is a timing signal, not proof that a company will buy. Check each account before you reach out.", "",
          f"Calls: {st['calls']}, cost ${st['cost_usd']} (sum of the `X-Desearch-Cost-Usd` headers)."]
    open(path, "w").write("\n".join(L) + "\n")


def chart(path, rows):
    import warnings
    warnings.filterwarnings("ignore")  # missing glyphs for non-Latin company names
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    if not rows:
        return
    rows = rows[::-1]
    fig, ax = plt.subplots(figsize=(8, 0.4 * len(rows) + 1))
    ax.barh([r["company"][:28] for r in rows], [r["x_posts"] for r in rows], label="X posts", color="#3b82f6")
    ax.barh([r["company"][:28] for r in rows], [r["job_pages"] for r in rows], left=[r["x_posts"] for r in rows], label="job pages", color="#f59e0b")
    ax.set_xlabel("signals (top companies by score)")
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def load_labels(path):
    if not path or not os.path.exists(path):
        return {}
    with open(path) as f:
        return {r["username"].lower(): r["label"] for r in csv.DictReader(f) if r.get("label")}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--role", default="data analyst")
    ap.add_argument("--x-query", action="append", help='X query template, {role} is replaced (repeatable)')
    ap.add_argument("--x-keyword", default="", help='adds: hiring "<role>" (<keyword>)')
    ap.add_argument("--web-keyword", default="", help="adds: <role> <keyword> site:<board> per board")
    ap.add_argument("--boards", default=",".join(DEFAULT_BOARDS))
    ap.add_argument("--web-start", default="0")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--fresh-days", type=int, default=14)
    ap.add_argument("--today", default="", help="UTC date to count back from (default: today)")
    ap.add_argument("--sort", default="Latest", choices=["Latest", "Top"])
    ap.add_argument("--x-count", type=int, default=50)
    ap.add_argument("--max-pages", type=int, default=160)
    ap.add_argument("--no-html-dates", dest="html_dates", action="store_false", help="skip the html read used to find datePosted")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--min-score", type=float, default=6)
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--labels", default="", help="CSV username,label to override the poster heuristic")
    ap.add_argument("--exclude", default="", help="comma-separated companies to leave out of the outputs")
    ap.add_argument("--redact", default="", help="comma-separated words to replace with [redacted] in saved titles")
    ap.add_argument("--out", default="output")
    ap.add_argument("--full-raw", default="", help="also save the full raw responses here (keep it private)")
    ap.add_argument("--from-raw", default="", help="rebuild outputs from a saved raw file, no API calls")
    a = ap.parse_args()
    a.boards = [b for b in a.boards.split(",") if b]
    a.web_start = [int(x) for x in a.web_start.split(",")]
    a.exclude = [x for x in a.exclude.split(",") if x]
    a.redact = [x for x in a.redact.split(",") if x]
    if a.from_raw:
        raw = json.load(open(a.from_raw))
        write_outputs(raw, a)
        return
    key = os.environ.get("DESEARCH_API_KEY")
    if not key:
        sys.exit("set DESEARCH_API_KEY (create a key at console.desearch.ai)")
    raw = collect(a, key)
    if a.full_raw:
        json.dump(raw, open(a.full_raw, "w"), indent=1, ensure_ascii=False)
    write_outputs(raw, a)


if __name__ == "__main__":
    main()
