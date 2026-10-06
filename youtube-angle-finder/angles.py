#!/usr/bin/env python3
"""YouTube Angle Finder: what YouTube already covers on a niche, and what looks thin.

Calls Desearch AI Search (POST https://api.desearch.ai/desearch/ai/search) and writes a
Markdown report: video titles, links, snippets, an "angles already covered / gaps that
look thin" brief with citations, and the cost from the X-Desearch-Cost-Usd header.

Path 1 (documented): tools=["youtube"], result_type LINKS_WITH_FINAL_SUMMARY, one call.
Path 2 (fallback, used when the API rejects the youtube tool with 422, as it did for me on
2026-10-04): tools=["web"] with "site:youtube.com <question>" to get video links, public
YouTube oEmbed for real titles and channel names, then one more AI Search call whose
system_message lists those verified titles so the brief is grounded in them.

Env vars (by name only):
  DESEARCH_API_KEY   required, your key from console.desearch.ai
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import requests

API_BASE = "https://api.desearch.ai"
AI_SEARCH = API_BASE + "/desearch/ai/search"
LINKS_WEB = API_BASE + "/desearch/ai/search/links/web"
OEMBED = "https://www.youtube.com/oembed"
COST_HEADERS = ["X-Desearch-Cost-Usd", "X-Desearch-Usage-Count", "X-Desearch-Service", "X-Desearch-Currency"]
EM_DASH = "\u2014"
BOILERPLATE = "Enjoy the videos and music you love"

BRIEF_FORMAT = (
    "Write exactly two sections in Markdown:\n"
    "## Angles already covered\n"
    "3 to 6 bullets. Each bullet names one angle that existing videos already take and cites the "
    "videos that take it as Markdown links with the exact video URL, e.g. [Video title](https://www.youtube.com/watch?v=ID).\n"
    "## Gaps that look thin\n"
    "3 to 5 bullets. Each names a question or sub-topic the videos cover weakly or not at all, and "
    "says in a few words why it looks thin (cite the closest video if any).\n"
    "Do not invent videos, view counts or dates. No intro, no outro."
)
SYSTEM_MESSAGE = ("You are a content strategist helping a YouTube creator pick a video angle. "
                  "Use only the YouTube search results provided. " + BRIEF_FORMAT)


def grounded_system_message(videos: list[dict]) -> str:
    listing = "\n".join(f"- {v['title']} (channel: {v.get('channel') or 'unknown'}) {v['link']}" for v in videos)
    return ("You are a content strategist helping a YouTube creator pick a video angle. "
            "The search result snippets for YouTube pages are generic, so base the brief ONLY on this "
            "verified list of videos (title, channel, URL) and ignore other results:\n"
            f"{listing}\n\n" + BRIEF_FORMAT)


def now_local() -> str:
    return dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")


def log(msg: str) -> None:
    print(f"[{now_local()}] {msg}", file=sys.stderr, flush=True)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def video_id(url: str) -> str | None:
    """YouTube video id for watch / youtu.be / shorts / embed / live URLs, else None."""
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return None
    host = p.netloc.lower().removeprefix("www.").removeprefix("m.")
    if host == "youtu.be":
        return p.path.strip("/").split("/")[0] or None
    if host.endswith("youtube.com"):
        if p.path == "/watch":
            return (parse_qs(p.query).get("v") or [None])[0]
        m = re.match(r"^/(shorts|embed|live)/([\w-]{6,})", p.path)
        if m:
            return m.group(2)
    return None


def canonical(url: str) -> str:
    vid = video_id(url)
    return f"https://www.youtube.com/watch?v={vid}" if vid else url


class Client:
    def __init__(self, key: str, raw_dir: str | None, tag: str):
        self.key, self.raw_dir, self.tag = key, raw_dir, tag
        self.calls: list[dict] = []

    def post(self, url: str, payload: dict, label: str) -> dict:
        log(f"POST {url} ({label}) tools={payload.get('tools')} result_type={payload.get('result_type')} "
            f"date_filter={payload.get('date_filter')}")
        t0 = time.perf_counter()
        r = requests.post(url, json=payload, timeout=180,
                          headers={"Authorization": self.key, "Content-Type": "application/json"})
        latency = time.perf_counter() - t0
        try:
            body = r.json()
        except ValueError:
            body = {"_non_json_body": r.text[:20000]}
        rec = {"when": now_local(), "label": label,
               "request": {"method": "POST", "url": url,
                           "headers": {"Authorization": "<redacted>", "Content-Type": "application/json"},
                           "body": payload},
               "status": r.status_code, "latency_s": round(latency, 2),
               "content_type": r.headers.get("Content-Type"),
               "cost_headers": {h: r.headers.get(h) for h in COST_HEADERS},
               "response": body}
        self.calls.append(rec)
        log(f"HTTP {r.status_code} in {rec['latency_s']} s, content-type {rec['content_type']}, "
            f"cost ${rec['cost_headers']['X-Desearch-Cost-Usd']}")
        if self.raw_dir:
            Path(self.raw_dir).mkdir(parents=True, exist_ok=True)
            n = len(self.calls)
            Path(self.raw_dir, f"{self.tag}-{n}-{label}.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False))
        return rec

    def total_cost(self) -> float:
        return round(sum(float(c["cost_headers"]["X-Desearch-Cost-Usd"] or 0) for c in self.calls), 6)


def youtube_tool_rejected(rec: dict) -> bool:
    if rec["status"] != 422:
        return False
    return "No supported tools" in json.dumps(rec["response"])


def videos_from(body: dict) -> list[dict]:
    """YouTube items from any documented key (youtube_search, youtube_search_results) or a
    generic result list (search, search_results), keeping only real video links."""
    if not isinstance(body, dict):
        return []
    items: list[dict] = []
    for key in ("youtube_search", "youtube_search_results", "search", "search_results"):
        if isinstance(body.get(key), list):
            items += [v for v in body[key] if isinstance(v, dict) and video_id(v.get("link", ""))]
    seen, out = set(), []
    for v in items:
        vid = video_id(v["link"])
        if vid in seen:
            continue
        seen.add(vid)
        title = re.sub(r"\s*-\s*YouTube\s*$", "", (v.get("title") or "").strip())
        out.append({"id": vid, "link": canonical(v["link"]), "api_link": v["link"],
                    "api_title": v.get("title"), "title": title, "snippet": re.sub(r"\s+", " ", v.get("snippet") or "").strip()})
    return out


def needs_title(t: str) -> bool:
    """Generic ("- YouTube"), empty or truncated ("...") titles get replaced by the oEmbed title."""
    return not t or t in ("- YouTube", "YouTube") or t.endswith(("...", "\u2026"))


def enrich_oembed(videos: list[dict]) -> None:
    """Public YouTube oEmbed (no key): real title + channel. Leaves fields if it fails."""
    for v in videos:
        try:
            r = requests.get(OEMBED, params={"url": v["link"], "format": "json"}, timeout=20)
        except requests.RequestException:
            v["oembed_status"] = "error"
            continue
        v["oembed_status"] = r.status_code
        if r.ok:
            d = r.json()
            if needs_title(v["title"]) and d.get("title"):
                v["title"] = d["title"]
                v["title_source"] = "oembed"
            v["channel"] = d.get("author_name")
    for v in videos:
        if not v["title"] or v["title"] in ("- YouTube", "YouTube"):
            v["title"] = f"(title unavailable, video {v['id']})"


def off_topic(body: dict) -> bool:
    """True when fewer than half of the returned links are YouTube videos."""
    items = [v for k in ("search", "search_results") for v in (body.get(k) or []) if isinstance(v, dict)]
    if not items:
        return True
    return sum(1 for v in items if video_id(v.get("link", ""))) * 2 < len(items)


def citation_check(completion: str, videos: list[dict]) -> dict:
    urls = re.findall(r"\]\((https?://[^)\s]+)\)", completion or "")
    ids = {v["id"] for v in videos}
    return {"linked": len(urls),
            "in_results": sum(1 for u in urls if video_id(u) in ids),
            "not_in_results": [u for u in urls if video_id(u) not in ids],
            "bare_numeric": re.findall(r"\[(\d+(?:\s*,\s*\d+)*)\](?!\()", completion or "")}


def run(question: str, mode: str, count: int, date_filter: str | None, client: Client, fallback: bool) -> dict:
    """Returns dict(path, videos, completion, warnings, error)."""
    res = {"question": question, "path": None, "videos": [], "completion": "", "warnings": [], "error": None}
    if mode == "links-web":
        rec = client.post(LINKS_WEB, {"prompt": question, "tools": ["youtube"], "count": count}, "links-web-youtube")
        res["path"] = "links/web tools=[youtube]"
        if rec["status"] != 200:
            res["error"] = rec["response"]
            return res
        res["videos"] = videos_from(rec["response"])
        enrich_oembed(res["videos"])
        return res

    rtype = "ONLY_LINKS" if mode == "links-only" else "LINKS_WITH_FINAL_SUMMARY"
    payload = {"prompt": question, "tools": ["youtube"], "result_type": rtype,
               "streaming": False,  # explicit: omitting it returned an event stream for me on 2026-10-03
               "count": count}
    if mode == "angles":
        payload["system_message"] = SYSTEM_MESSAGE
    if date_filter:
        payload["date_filter"] = date_filter
    rec = client.post(AI_SEARCH, payload, "youtube-tool")
    if rec["status"] == 200:
        res["path"] = "ai/search tools=[youtube]"
        body = rec["response"]
        res["videos"] = videos_from(body)
        res["completion"] = (body.get("completion") or "").strip()
        res["warnings"] = body.get("warnings") or []
        enrich_oembed(res["videos"])
        return res
    if not (fallback and youtube_tool_rejected(rec)):
        res["error"] = rec["response"]
        return res

    log("youtube tool rejected (422 'No supported tools'); falling back to web search with site:youtube.com")
    res["warnings"].append({"message": "Desearch rejected tools=[\"youtube\"] with 422; used tools=[\"web\"] "
                                       "with a site:youtube.com prompt instead."})
    site_q = f"site:youtube.com {question}"
    p1 = {"prompt": site_q, "tools": ["web"], "result_type": "ONLY_LINKS", "streaming": False, "count": count}
    if date_filter:
        p1["date_filter"] = date_filter
    rec1 = client.post(AI_SEARCH, p1, "fallback-web-links")
    if rec1["status"] == 200 and off_topic(rec1["response"]):
        # Seen live on 2026-10-04: the same prompt sometimes returns generic "technology" pages.
        log("result set has few YouTube videos (off-topic response); retrying once")
        res["warnings"].append({"message": "First links call came back off-topic (few YouTube links); retried once."})
        rec1 = client.post(AI_SEARCH, p1, "fallback-web-links-retry")
    res["path"] = "fallback: ai/search tools=[web] site:youtube.com"
    if rec1["status"] != 200:
        res["error"] = rec1["response"]
        return res
    res["warnings"] += rec1["response"].get("warnings") or []
    res["videos"] = videos_from(rec1["response"])
    enrich_oembed(res["videos"])
    if mode == "links-only" or not res["videos"]:
        return res
    p2 = dict(p1, result_type="LINKS_WITH_FINAL_SUMMARY", system_message=grounded_system_message(res["videos"]))
    rec2 = client.post(AI_SEARCH, p2, "fallback-web-summary")
    if rec2["status"] == 200 and off_topic(rec2["response"]):
        log("summary call searched off-topic pages; retrying once")
        res["warnings"].append({"message": "Summary call came back grounded in off-topic pages; retried once."})
        rec2 = client.post(AI_SEARCH, p2, "fallback-web-summary-retry")
    if rec2["status"] == 200 and off_topic(rec2["response"]):
        res["warnings"].append({"message": "Summary call still off-topic after retry; angles brief discarded."})
    elif rec2["status"] == 200:
        res["completion"] = (rec2["response"].get("completion") or "").strip()
        res["warnings"] += rec2["response"].get("warnings") or []
    else:
        res["error"] = rec2["response"]
    return res


def render(question: str, res: dict, mode: str, date_filter: str | None, client: Client) -> str:
    lat = ", ".join(f"{c['latency_s']} s" for c in client.calls)
    lines = [f"# YouTube angles: {question}", "",
             f"Generated {client.calls[-1]['when'] if client.calls else now_local()} with the Desearch API. Path: `{res['path']}`, mode `{mode}`"
             + (f", `date_filter: {date_filter}`" if date_filter else "") + ".",
             f"Desearch calls: {len(client.calls)} (HTTP {', '.join(str(c['status']) for c in client.calls)}; {lat}). "
             f"Cost: ${client.total_cost():.3f} (sum of X-Desearch-Cost-Usd).", ""]
    for w in res["warnings"]:
        lines.append(f"> Note: {w.get('message', w)}")
    if res["warnings"]:
        lines.append("")
    if res["error"] is not None:
        lines += ["## Error", "", "```json", json.dumps(res["error"], indent=2)[:3000], "```", ""]
    if res["completion"]:
        cc = citation_check(res["completion"], res["videos"])
        lines += [res["completion"], "",
                  f"_Citation check: {cc['linked']} linked citations, {cc['in_results']} point to a video in the list below"
                  + (f", {len(cc['not_in_results'])} do not" if cc["not_in_results"] else "")
                  + (f", {len(cc['bare_numeric'])} bare numeric citations without a URL" if cc["bare_numeric"] else "")
                  + "._", ""]
    elif mode == "angles" and res["error"] is None:
        lines += ["_No angles brief returned._", ""]
    lines += [f"## Videos found ({len(res['videos'])})", ""]
    for i, v in enumerate(res["videos"], 1):
        ch = f" ({v['channel']})" if v.get("channel") else ""
        lines.append(f"{i}. [{v['title'].replace(EM_DASH, '-')}]({v['link']}){ch}")
        snip_t = re.sub(r"\s*-\s*YouTube\s*$", "", v["snippet"])
        if v["snippet"] and not v["snippet"].startswith(BOILERPLATE) and snip_t != v["title"]:
            lines.append(f"   {v['snippet'][:300]}")
    lines += ["", "_Channel names come from public YouTube oEmbed, which also replaces generic or truncated Desearch titles. "
                  "Desearch returned no publish date or view count, so none are shown._", ""]
    return "\n".join(lines)


def replay(prefix: str, out_dir: str) -> int:
    """Re-render a saved run without calling Desearch (oEmbed titles come from the saved videos file)."""
    import glob
    calls = [json.loads(Path(f).read_text()) for f in sorted(glob.glob(prefix + "-[0-9]-*.json"))]
    saved = json.loads(Path(prefix + "-videos.json").read_text())
    for v in saved["videos"]:
        if v.get("api_title") is None:
            v["title"] = re.sub(r"\s*-\s*YouTube\s*$", "", v["title"])
    enrich_oembed([v for v in saved["videos"] if needs_title(v["title"])])  # free public call, not Desearch
    tag = Path(prefix).name
    mode = "links-web" if "-links-web-" in tag else "links-only" if "-links-only-" in tag else "angles"
    client = Client("", None, tag)
    client.calls = calls
    df = calls[0]["request"]["body"].get("date_filter") if calls else None
    question = saved.get("question") or (calls[0]["request"]["body"]["prompt"].removeprefix("site:youtube.com ") if calls else tag)
    md = render(question, saved, mode, df, client)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    Path(out_dir, tag + "-replay.md").write_text(md)
    print(md)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("question", nargs="+", help="niche or product question")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--links-only", action="store_true",
                   help="video list only, no angles brief (result_type ONLY_LINKS); same price per call as the full brief")
    g.add_argument("--links-web", action="store_true",
                   help="try the documented /desearch/ai/search/links/web path with tools=[youtube]")
    ap.add_argument("--no-fallback", action="store_true", help="do not fall back to site:youtube.com web search")
    ap.add_argument("--date-filter", default=None,
                    help="e.g. PAST_WEEK. Passed through to POST /desearch/ai/search; not a reliable freshness filter in the 2026-10-04 test")
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--out-dir", default="angles-out")
    ap.add_argument("--raw-dir", default=None, help="also save redacted request/response JSON here")
    ap.add_argument("--replay", default=None, metavar="RAW_PREFIX",
                    help="re-render from saved raw JSON (path prefix up to the run tag), no API calls")
    a = ap.parse_args()
    if a.replay:
        return replay(a.replay, a.out_dir)

    key = os.environ.get("DESEARCH_API_KEY")
    if not key:
        print("Set DESEARCH_API_KEY (your key from console.desearch.ai).", file=sys.stderr)
        return 2
    question = " ".join(a.question)
    mode = "links-web" if a.links_web else "links-only" if a.links_only else "angles"
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    tag = f"{stamp}-{mode}-{slug(question)}" + (f"-{a.date_filter.lower()}" if a.date_filter else "")
    client = Client(key, a.raw_dir, tag)
    try:
        res = run(question, mode, a.count, a.date_filter, client, not a.no_fallback)
    except requests.RequestException as e:
        log(f"Request failed: {type(e).__name__}")  # never log the exception repr (it can carry headers)
        return 1
    md = render(question, res, mode, a.date_filter, client)
    if a.raw_dir:
        Path(a.raw_dir, f"{tag}-videos.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))
    Path(a.out_dir).mkdir(parents=True, exist_ok=True)
    out = Path(a.out_dir, tag + ".md")
    out.write_text(md)
    print(md)
    log(f"wrote {out}; Desearch calls {len(client.calls)}; total cost ${client.total_cost():.3f}")
    return 0 if res["error"] is None else 1


if __name__ == "__main__":
    sys.exit(main())
