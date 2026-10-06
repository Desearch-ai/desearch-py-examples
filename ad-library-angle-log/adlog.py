#!/usr/bin/env python3
"""Ad Library Angle Log: what a store is running in public Meta Ad Library records, and what changed.

Calls Desearch Facebook search (POST https://api.desearch.ai/desearch/facebook/search), which searches
public Meta Ad Library records by keyword. For each store it saves a JSON snapshot, writes a Markdown
angle log (hooks and angles grouped by ad copy, offers, CTAs in the copy, landing page notes, days since
the ad started), and diffs two snapshots (new ads, disappeared ads, unchanged ads).

Landing pages are fetched with Desearch Extract (GET /web/extract) only when the ad record itself
contains a URL. Nothing is guessed.

Env vars (by name only):
  DESEARCH_API_KEY   required for `run`, your key from console.desearch.ai
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import requests

API_BASE = "https://api.desearch.ai"
FB_SEARCH = API_BASE + "/desearch/facebook/search"
EXTRACT = API_BASE + "/web/extract"
COST_HEADERS = ["X-Desearch-Cost-Usd", "X-Desearch-Usage-Count", "X-Desearch-Service", "X-Desearch-Currency"]
TIMEOUT = 120
# POST /desearch/facebook/search returned at most 30 ads on 2026-10-05 (count=31 and count=50 both returned 30).
# cursor is ignored, so there is no paging. Clamp so --count does not ask for ads the endpoint will not return.
OBSERVED_MAX = 30

# Rule-based angle tags. Keywords cover English plus the French, Spanish, Italian, Dutch and German copy seen in my runs.
ANGLES = {
    "offer / discount": r"\d+\s?%|\bcode\b|\bsale\b|\boff\b|promo|soldes|rebaja|descuento|discount|free (shipping|delivery)|livraison offerte|env[ií]o gratis|rabatt|korting|bespaar|spare|saldi|sconto",
    "new arrival / launch": r"\bnew\b|just landed|just dropped|\bdrop\b|nouveau|nouvelle|nouveaux|nuevo|nueva|nuevos|ya est[aá]n aqu[ií]|launch|collection|\bneue?[nrs]?\b|nieuwe?",
    "motivation / identity": r"motivation|\btrain|\bPRs?\b|no excuses|we do gym|\bready\b|entrenar|entra[iî]n|grind|discipline",
    "comfort / product benefit": r"comfort|soft|squat.?proof|\bfit\b|breathable|lightweight|move comfortably|confort|c[oó]mod",
    "community / engagement": r"community|comment|\bjoin\b|tag a|communaut|comunidad",
    "seasonal": r"summer|winter|autumn|\bfall\b|season|holiday|black friday|back to|[eé]t[eé]\b|verano|invierno|hiver|rentr[eé]e|sommers?\b|zomer",
    "social proof": r"best.?sellers?|favou?rites?|loved by|reviews?|rated|top must-haves|bestseller|beliebteste|five-star|5-star",
}
OFFER_PATTERNS = [
    r"(?:extra\s*)?-?\d+\s?%\s*(?:off)?[^.\n]{0,60}",
    r"\bcode\s+[A-Z0-9]{3,}",
    r"free (?:shipping|delivery|returns)[^.\n]{0,30}",
    r"(?:up to|jusqu'[aà]|hasta)\s+-?\d+\s?%[^.\n]{0,30}",
    r"[$€£]\s?\d[\d,.]*\d|[$€£]\s?\d",
]
CTA_PATTERNS = [
    r"shop (?:now|the [\w\s]{2,30}|best sellers|our [\w\s']{2,30})", r"explore [\w\s]{2,30}", r"discover [\w\s]{2,30}",
    r"join (?:the )?[\w\s]{2,30}", r"drop a comment[\w\s]*", r"learn more", r"order now", r"get yours", r"sign up",
    r"d[eé]couvr\w*", r"compra\w*", r"descubr\w*", r"scopri\w*", r"entdecke\w*",
]
URL_RE = re.compile(r"(https?://[^\s<>\"')]+|\b(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|co|shop|store|net|org|io|eu|uk|fr|es|de|sa|pk)(?:/[^\s<>\"')]*)?)", re.I)


# ----------------------------------------------------------------------------------------- utils
def now_local() -> dt.datetime:
    return dt.datetime.now().astimezone()


def log(msg: str) -> None:
    print(f"[{now_local().strftime('%Y-%m-%d %H:%M:%S %z')}] {msg}", file=sys.stderr, flush=True)


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "store"


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())


def api_key() -> str:
    k = os.environ.get("DESEARCH_API_KEY", "").strip()
    if not k:
        sys.exit("DESEARCH_API_KEY is not set. Export your key from console.desearch.ai first.")
    return k


def cost_meta(headers) -> dict:
    out = {}
    for h in COST_HEADERS:
        v = headers.get(h)
        if v is None:
            continue
        if h == "X-Desearch-Cost-Usd":
            out["cost_usd"] = round(float(v), 6)
            out["cost_usd_raw_header"] = v
        elif h == "X-Desearch-Usage-Count":
            out["usage_count"] = int(float(v))
        else:
            out[h.replace("X-Desearch-", "").lower()] = v
    return out


def save_raw(raw_dir: Path | None, name: str, rec: dict, key: str) -> None:
    if not raw_dir:
        return
    raw_dir.mkdir(parents=True, exist_ok=True)
    s = json.dumps(rec, indent=2, ensure_ascii=False)
    if key and key in s:  # belt and braces: never write the key
        s = s.replace(key, "<redacted>")
    (raw_dir / name).write_text(s)


def call(method: str, url: str, key: str, *, body: dict | None = None, params: dict | None = None,
         raw_dir: Path | None = None, raw_name: str = "call.json") -> dict:
    """One Desearch request. Returns a call record (status, latency, cost meta, parsed body)."""
    t0 = time.perf_counter()
    try:
        if method == "POST":
            r = requests.post(url, headers={"Authorization": key, "Content-Type": "application/json"}, json=body, timeout=TIMEOUT)
        else:
            r = requests.get(url, headers={"Authorization": key}, params=params, timeout=TIMEOUT)
    except requests.RequestException as e:  # never log str(e) blindly; report type only
        log(f"{method} {url} failed: {type(e).__name__}")
        return {"status": None, "error": type(e).__name__, "latency_s": round(time.perf_counter() - t0, 2), "cost": {}, "body": None}
    el = round(time.perf_counter() - t0, 2)
    ctype = r.headers.get("content-type", "")
    try:
        parsed = r.json() if "json" in ctype else r.text
    except ValueError:
        parsed = r.text
    rec = {
        "when": now_local().strftime("%Y-%m-%d %H:%M:%S %z"),
        "request": {"method": method, "url": url, "headers": {"Authorization": "<redacted>"},
                    **({"body": body} if body is not None else {}), **({"params": params} if params else {})},
        "status": r.status_code, "latency_s": el, "response_headers": dict(r.headers), "response": parsed,
    }
    save_raw(raw_dir, raw_name, rec, key)
    cm = cost_meta(r.headers)
    n = len(parsed) if isinstance(parsed, list) else ("text" if isinstance(parsed, str) else "object")
    log(f"{method} {url.replace(API_BASE, '')} -> HTTP {r.status_code} in {el}s, items={n}, "
        f"cost=${cm.get('cost_usd', 0):.5f}, units={cm.get('usage_count', '-')}")
    return {"status": r.status_code, "latency_s": el, "cost": cm, "body": parsed, "when": rec["when"]}


# ------------------------------------------------------------------------------- normalization
def parse_create_time(v) -> tuple[str | None, str]:
    """Desearch createTime -> (YYYY-MM-DD, kind). In my responses it is an int epoch (seconds) at 07:00 UTC,
    which matched the public Ad Library start_date for every ad I cross-checked. The schema says string."""
    if v is None or v == "":
        return None, "missing"
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
        return dt.datetime.fromtimestamp(int(v), dt.timezone.utc).strftime("%Y-%m-%d"), "epoch"
    try:
        return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")).strftime("%Y-%m-%d"), "iso"
    except ValueError:
        return None, "unparsed"


def tag_angles(text: str) -> list[str]:
    return [a for a, pat in ANGLES.items() if re.search(pat, text or "", re.I)]


def find_all(patterns: list[str], text: str) -> list[str]:
    out = []
    for p in patterns:
        for m in re.finditer(p, text or "", re.I):
            s = m.group(0).strip(" .,!")
            if s and not any(s.lower() in o.lower() for o in out):
                out = [o for o in out if o.lower() not in s.lower()] + [s]
    return out


def hook_of(text: str) -> str:
    first = re.split(r"\n+|(?<=[.!?])\s", (text or "").strip(), maxsplit=1)[0].strip()
    return (first[:117] + "...") if len(first) > 120 else first


def normalize_ad(raw: dict, store: str, snap_date: dt.date) -> dict:
    author = raw.get("author") or {}
    text = raw.get("text") or ""
    start, kind = parse_create_time(raw.get("createTime"))
    urls = [u for u in URL_RE.findall(text) if not re.search(r"facebook\.com|fbcdn\.net|instagram\.com", u, re.I)]
    media = raw.get("media") or []
    return {
        "ad_id": str(raw.get("id")),
        "library_url": raw.get("url"),
        "advertiser": author.get("name"),
        "advertiser_page_id": author.get("id"),
        "advertiser_category": author.get("category"),
        "advertiser_is_store": bool(norm(store) and norm(store) in norm(author.get("name") or "")),
        "text": text,
        "copy_key": hashlib.sha1(re.sub(r"\s+", " ", text.strip().lower()).encode()).hexdigest()[:12],
        "hook": hook_of(text),
        "create_time_raw": raw.get("createTime"),
        "create_time_kind": kind,
        "start_date": start,
        "days_since_start": (snap_date - dt.date.fromisoformat(start)).days if start else None,
        "media_count": len(media),
        "media_types": sorted({m.get("type") or "unknown" for m in media}),
        "stats": raw.get("stats") or {},
        "hashtags": raw.get("hashtags") or [],
        "landing_urls_in_record": urls,
        "landing_url_kind": ("full URL" if any(u.lower().startswith("http") for u in urls) else "bare domain in text") if urls else None,
        "angles": tag_angles(text),
        "offers": find_all(OFFER_PATTERNS, text),
        "ctas_in_copy": find_all(CTA_PATTERNS, text),
    }


# ----------------------------------------------------------------------------------------- run
def search_store(store: str, count: int, key: str, raw_dir: Path | None, probe: bool) -> dict:
    calls = []
    s = slug(store)
    if probe and count > 1:
        # Probe first. Empty results cost $0, and count=1 skips a full search when the keyword matches nothing.
        c = call("POST", FB_SEARCH, key, body={"query": store, "count": 1}, raw_dir=raw_dir, raw_name=f"{s}-probe-count1.json")
        calls.append({"purpose": "probe", "requested": 1, **{k: c[k] for k in ("status", "latency_s", "cost")},
                      "returned": len(c["body"]) if isinstance(c["body"], list) else None})
        if c["status"] != 200 or not isinstance(c["body"], list) or not c["body"]:
            return {"calls": calls, "raw_ads": [], "note": "probe returned no ads, full search skipped"}
    c = call("POST", FB_SEARCH, key, body={"query": store, "count": count}, raw_dir=raw_dir, raw_name=f"{s}-search-count{count}.json")
    ads = c["body"] if isinstance(c["body"], list) else []
    calls.append({"purpose": "search", "requested": count, **{k: c[k] for k in ("status", "latency_s", "cost")},
                  "returned": len(ads) if isinstance(c["body"], list) else None,
                  "error_body": None if isinstance(c["body"], list) else c["body"]})
    return {"calls": calls, "raw_ads": ads, "note": None}


def extract_landing(url: str, key: str, raw_dir: Path | None, idx: int) -> dict:
    u = url if url.startswith("http") else "https://" + url
    c = call("GET", EXTRACT, key, params={"url": u, "format": "text"}, raw_dir=raw_dir, raw_name=f"extract-{idx:02d}.json")
    # Only a 200 body is page text. An empty page is HTTP 404 "No content found" and is not billed.
    if c["status"] == 200:
        text = c["body"] if isinstance(c["body"], str) else json.dumps(c["body"])[:2000]
    else:
        text = ""
    return {"url": u, "status": c["status"], "cost": c["cost"], "chars": len(text or ""),
            "offers_on_page": find_all(OFFER_PATTERNS, text or "")[:8], "excerpt": (text or "")[:400]}


def cmd_run(a) -> int:
    key = api_key()
    started = now_local()
    run_id = started.strftime("%Y%m%d-%H%M%S") + (f"-{slug(a.label)}" if a.label else "")
    run_dir = Path(a.out_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = run_dir / "raw" if a.save_raw else None
    snap = {"run_id": run_id, "started_at": started.strftime("%Y-%m-%d %H:%M:%S %z"), "endpoint": FB_SEARCH,
            "count": a.count, "probe_first": not a.no_probe, "stores": {}}
    total_cost = 0.0
    ext_idx = 0
    for store in a.store:
        log(f"store '{store}': searching Ad Library records (count={a.count})")
        res = search_store(store, a.count, key, raw_dir, probe=not a.no_probe)
        ads, seen, dupes = [], set(), 0
        for r in res["raw_ads"]:
            ad = normalize_ad(r, store, started.date())
            if ad["ad_id"] in seen:
                dupes += 1
                continue
            seen.add(ad["ad_id"])
            ads.append(ad)
        landings, done_urls = [], set()
        if a.extract:
            for ad in sorted(ads, key=lambda x: not x["advertiser_is_store"]):  # store's own ads first
                for u in ad["landing_urls_in_record"]:
                    if ext_idx >= a.extract or u.lower().rstrip("/") in done_urls:
                        continue
                    done_urls.add(u.lower().rstrip("/"))
                    ext_idx += 1
                    lp = extract_landing(u, key, raw_dir, ext_idx)
                    if lp["status"] == 200 and lp["chars"] == 0:
                        # One live call returned HTTP 200 with an empty body. Retry once. Empty pages are normally HTTP 404.
                        log(f"extract returned HTTP 200 with an empty body for {u}; retrying once")
                        ext_idx += 1
                        retry = extract_landing(u, key, raw_dir, ext_idx)
                        retry["cost"] = {"cost_usd": lp["cost"].get("cost_usd", 0) + retry["cost"].get("cost_usd", 0)}
                        retry["retried_after_empty_200"] = True
                        lp = retry
                    landings.append({"ad_id": ad["ad_id"], "advertiser_is_store": ad["advertiser_is_store"], **lp})
        cost = sum(c["cost"].get("cost_usd", 0) for c in res["calls"]) + sum(l["cost"].get("cost_usd", 0) for l in landings)
        total_cost += cost
        snap["stores"][store] = {"calls": res["calls"], "note": res["note"], "duplicate_ids_dropped": dupes,
                                 "ads": ads, "landing_pages": landings, "cost_usd": round(cost, 6)}
        md = render_store(store, snap)
        (run_dir / f"{slug(store)}-angle-log.md").write_text(md)
        log(f"store '{store}': {len(ads)} unique ads, cost ${cost:.5f}, wrote {run_dir / (slug(store) + '-angle-log.md')}")
    snap["finished_at"] = now_local().strftime("%Y-%m-%d %H:%M:%S %z")
    snap["total_cost_usd"] = round(total_cost, 6)
    (run_dir / "snapshot.json").write_text(json.dumps(snap, indent=2, ensure_ascii=False))
    log(f"snapshot: {run_dir / 'snapshot.json'}  total cost ${total_cost:.5f}")
    if a.diff_against:
        prev = latest_snapshot(Path(a.out_dir), exclude=run_dir) if a.diff_against == "latest" else Path(a.diff_against)
        if prev:
            write_diff(prev, run_dir / "snapshot.json", run_dir)
        else:
            log("no previous snapshot to diff against")
    print((run_dir / f"{slug(a.store[0])}-angle-log.md").read_text())
    return 0


def latest_snapshot(out_dir: Path, exclude: Path) -> Path | None:
    snaps = sorted(p for p in out_dir.glob("*/snapshot.json") if p.parent != exclude)
    return snaps[-1] if snaps else None


# -------------------------------------------------------------------------------------- render
def render_store(store: str, snap: dict) -> str:
    st = snap["stores"][store]
    ads = st["ads"]
    mine = [x for x in ads if x["advertiser_is_store"]]
    others = [x for x in ads if not x["advertiser_is_store"]]
    calls = st["calls"]
    billed = sum(c["cost"].get("usage_count", 0) for c in calls)
    L = [f"# Ad angle log: {store}", "",
         f"Made by Desearch (https://desearch.ai). Run `{snap['run_id']}`, started {snap['started_at']}.", ""]
    L.append("Desearch calls: " + "; ".join(
        f"{c['purpose']} count={c['requested']} -> HTTP {c['status']}, {c['returned']} ads, "
        f"{c['cost'].get('usage_count', '-')} units, ${c['cost'].get('cost_usd', 0):.5f}, {c['latency_s']} s" for c in calls))
    if st["landing_pages"]:
        L.append(f"Extract calls: {len(st['landing_pages'])}.")
    L.append(f"Cost for this store: ${st['cost_usd']:.5f} (sum of X-Desearch-Cost-Usd). Billed units: {billed}.")
    L.append("")
    if st["note"]:
        L += [f"**No ads returned.** {st['note']}.", ""]
    if not ads:
        L += ["No Ad Library records matched this keyword. Check the spelling, or try the brand's page name as it appears on Facebook.", ""]
        return "\n".join(L)
    groups = defaultdict(list)
    for x in mine:
        groups[x["copy_key"]].append(x)
    with_url = sum(1 for x in ads if x["landing_urls_in_record"])
    mine_url = sum(1 for x in mine if x["landing_urls_in_record"])
    with_media = sum(1 for x in ads if x["media_count"])
    with_stats = sum(1 for x in ads if x["stats"])
    L += ["## At a glance", "",
          f"- Ads returned: {len(ads)} ({len(mine)} from an advertiser named like \"{store}\", {len(others)} from other advertisers that mention it)",
          f"- Distinct ad copies from the store: {len(groups)} (Ad Library lists each version of a creative as its own ad)",
          f"- Records with a landing URL or domain in the data: {with_url} of {len(ads)} ({mine_url} of {len(mine)} store ads)",
          f"- Records with media: {with_media} of {len(ads)}; records with engagement stats: {with_stats} of {len(ads)}", ""]
    ang = Counter(a for x in mine for a in x["angles"])
    if ang:
        L += ["## Angles in the store's ads", "", "| Angle | Ads | Distinct copies |", "|---|---|---|"]
        for a_, n in ang.most_common():
            nc = len({x["copy_key"] for x in mine if a_ in x["angles"]})
            L.append(f"| {a_} | {n} | {nc} |")
        untagged = [x for x in mine if not x["angles"]]
        if untagged:
            L.append(f"| (no rule matched) | {len(untagged)} | {len({x['copy_key'] for x in untagged})} |")
        L.append("")
    L += ["## Ad copies, longest running first", "",
          "Days since start = snapshot date minus the Ad Library start date (`createTime`). The record has no end date or active flag, so this is days live only while the ad is still running.", ""]
    order = sorted(groups.values(), key=lambda g: -max(x["days_since_start"] or -1 for x in g))
    for i, g in enumerate(order, 1):
        g = sorted(g, key=lambda x: x["start_date"] or "")
        starts = sorted({x["start_date"] for x in g if x["start_date"]})
        days = [x["days_since_start"] for x in g if x["days_since_start"] is not None]
        L.append(f"### {i}. {g[0]['hook'] or '(no text)'}")
        L.append("")
        L.append(f"- Versions: {len(g)} ad id{'s' if len(g) != 1 else ''}; started {starts[0] if starts else '?'}"
                 + (f" to {starts[-1]}" if len(starts) > 1 else "")
                 + (f"; {max(days)} days since the earliest start" if days else ""))
        L.append(f"- Angles: {', '.join(g[0]['angles']) or 'none matched'}")
        if g[0]["offers"]:
            L.append(f"- Offer in copy: {'; '.join(g[0]['offers'])}")
        if g[0]["ctas_in_copy"]:
            L.append(f"- CTA in copy: {'; '.join(g[0]['ctas_in_copy'])}")
        L.append("- Ads: " + ", ".join(f"[{x['ad_id']}]({x['library_url']}) ({x['start_date']})" for x in g[:8])
                 + (f" and {len(g) - 8} more" if len(g) > 8 else ""))
        L.append("")
        L.append("> " + g[0]["text"].replace("\n", "\n> "))
        L.append("")
    first_form = {}
    for x in mine:
        for o in x["offers"]:
            first_form.setdefault(o.lower(), o)
    offers = Counter(first_form[o.lower()] for x in mine for o in x["offers"])
    ctas = Counter(c.lower() for x in mine for c in x["ctas_in_copy"])
    L += ["## Offers seen in ad copy", ""] + ([f"- {o} ({n} ads)" for o, n in offers.most_common()] or ["- none found in the copy"]) + [""]
    L += ["## CTAs seen in ad copy", "",
          "The Desearch record has no CTA button field, so these are phrases found in the ad text only.", ""]
    L += [f"- {c} ({n} ads)" for c, n in ctas.most_common()] or ["- none found in the copy"]
    L.append("")
    L += ["## Landing pages", ""]
    if st["landing_pages"]:
        for lp in st["landing_pages"]:
            who = "store ad" if lp.get("advertiser_is_store") else "other advertiser"
            L.append(f"- {lp['url']} (from {who} {lp['ad_id']}{', retried after an empty 200' if lp.get('retried_after_empty_200') else ''}): HTTP {lp['status']}, {lp['chars']} chars, "
                     f"offers on page: {'; '.join(lp['offers_on_page']) or 'none matched'}, cost ${lp['cost'].get('cost_usd', 0):.5f}")
    elif with_url:
        L.append(f"- {with_url} records contain a URL in the text; run with `--extract N` to fetch them with Desearch Extract.")
    else:
        L.append(f"- None of the {len(ads)} records contained a landing page URL (no URL field in the record, none in the ad text), so no page was fetched.")
    if mine and not mine_url:
        L.append(f"- None of the store's {len(mine)} ads carried a landing URL in the Desearch record, so their landing pages are unknown here.")
    L.append("")
    if others:
        L += ["## Other advertisers using the keyword", ""]
        for x in others:
            L.append(f"- {x['advertiser']} ([{x['ad_id']}]({x['library_url']}), started {x['start_date']}): {x['hook']}")
        L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------------------- diff
def diff_snapshots(a: dict, b: dict) -> dict:
    out = {"from_run": a["run_id"], "to_run": b["run_id"], "from_started": a["started_at"], "to_started": b["started_at"], "stores": {}}
    for store in sorted(set(a["stores"]) | set(b["stores"])):
        A = {x["ad_id"]: x for x in a["stores"].get(store, {}).get("ads", [])}
        B = {x["ad_id"]: x for x in b["stores"].get(store, {}).get("ads", [])}
        changed = [i for i in set(A) & set(B) if (A[i]["text"], A[i]["start_date"]) != (B[i]["text"], B[i]["start_date"])]
        ca, cb = {x["copy_key"] for x in A.values()}, {x["copy_key"] for x in B.values()}
        out["stores"][store] = {
            "count_from": len(A), "count_to": len(B),
            "new": sorted(set(B) - set(A)), "disappeared": sorted(set(A) - set(B)),
            "unchanged": sorted(i for i in set(A) & set(B) if i not in changed), "changed": sorted(changed),
            "new_copies": sorted(cb - ca), "gone_copies": sorted(ca - cb),
            "ads": {i: {k: (B.get(i) or A.get(i))[k] for k in ("advertiser", "start_date", "hook", "library_url", "copy_key")} for i in set(A) | set(B)},
        }
    return out


def render_diff(d: dict) -> str:
    L = ["# Ad Library diff", "", "Made by Desearch (https://desearch.ai).", "",
         f"From run `{d['from_run']}` ({d['from_started']}) to run `{d['to_run']}` ({d['to_started']}).", "",
         "\"Disappeared\" means the ad id was not in the second run's results. Desearch returns the first N matching records, "
         "so an ad can drop out of the window without having stopped. Compare runs made with the same `--count`.", ""]
    for store, s in d["stores"].items():
        L += [f"## {store}", "", f"- Ads in run 1: {s['count_from']}, in run 2: {s['count_to']}",
              f"- New: {len(s['new'])}, disappeared: {len(s['disappeared'])}, unchanged: {len(s['unchanged'])}, same id with changed text or start date: {len(s['changed'])}",
              f"- Distinct ad copies new: {len(s['new_copies'])}, gone: {len(s['gone_copies'])}", ""]
        for label, ids in (("New ads", s["new"]), ("Disappeared ads", s["disappeared"]), ("Changed ads", s["changed"])):
            L.append(f"### {label}")
            L.append("")
            if not ids:
                L.append("- none")
            for i in ids:
                x = s["ads"][i]
                L.append(f"- [{i}]({x['library_url']}) {x['advertiser']}, started {x['start_date']}: {x['hook']}")
            L.append("")
        L.append(f"### Unchanged ads ({len(s['unchanged'])})")
        L.append("")
        L.append(", ".join(s["unchanged"]) or "- none")
        L.append("")
    return "\n".join(L)


def write_diff(pa: Path, pb: Path, out_dir: Path) -> None:
    d = diff_snapshots(json.loads(pa.read_text()), json.loads(pb.read_text()))
    (out_dir / "diff.json").write_text(json.dumps(d, indent=2, ensure_ascii=False))
    (out_dir / "diff.md").write_text(render_diff(d))
    for store, s in d["stores"].items():
        log(f"diff {store}: new {len(s['new'])}, disappeared {len(s['disappeared'])}, unchanged {len(s['unchanged'])}, changed {len(s['changed'])}")
    log(f"diff written: {out_dir / 'diff.md'}")


def cmd_diff(a) -> int:
    out = Path(a.out) if a.out else Path(a.snapshot_b).parent
    out.mkdir(parents=True, exist_ok=True)
    write_diff(Path(a.snapshot_a), Path(a.snapshot_b), out)
    print((out / "diff.md").read_text())
    return 0


def cmd_render(a) -> int:
    snap = json.loads(Path(a.snapshot).read_text())
    for store in snap["stores"]:
        print(render_store(store, snap))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="search Ad Library records for each store, save a snapshot and angle logs")
    r.add_argument("--store", action="append", required=True, help="store / brand keyword (repeatable)")
    r.add_argument("--count", type=int, default=30, help="ads to request per store, 1-100 (default 30). POST /desearch/facebook/search returns at most 30 and bills per ad returned, so higher values are clamped unless --no-clamp")
    r.add_argument("--no-clamp", action="store_true", help="send --count above 30 as is. POST /desearch/facebook/search still returns at most 30 ads and bills only the ads returned")
    r.add_argument("--no-probe", action="store_true", help="skip the count=1 existence check before the full search")
    r.add_argument("--extract", type=int, default=0, metavar="N", help="fetch up to N landing URLs found in ad records with Desearch Extract")
    r.add_argument("--out-dir", default="runs", help="where run folders go (default runs/)")
    r.add_argument("--label", default="", help="suffix for the run folder name")
    r.add_argument("--save-raw", action="store_true", help="save each request/response as JSON (key redacted)")
    r.add_argument("--diff-against", metavar="SNAPSHOT|latest", help="also write diff.md against a previous snapshot")
    r.set_defaults(fn=cmd_run)
    d = sub.add_parser("diff", help="diff two snapshot.json files")
    d.add_argument("snapshot_a")
    d.add_argument("snapshot_b")
    d.add_argument("--out", help="folder for diff.md / diff.json (default: folder of snapshot_b)")
    d.set_defaults(fn=cmd_diff)
    rd = sub.add_parser("render", help="re-render angle logs from a snapshot without calling Desearch")
    rd.add_argument("snapshot")
    rd.set_defaults(fn=cmd_render)
    a = p.parse_args()
    if a.cmd == "run":
        if not 1 <= a.count <= 100:
            p.error("--count must be 1-100 (API limit)")
        if a.count > OBSERVED_MAX and not a.no_clamp:
            log(f"--count {a.count} clamped to {OBSERVED_MAX}: POST /desearch/facebook/search returned at most {OBSERVED_MAX} ads on 2026-10-05 (count=31 and count=50 both returned 30) and cursor is ignored, so there is no paging (use --no-clamp to send it anyway)")
            a.count = OBSERVED_MAX
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
