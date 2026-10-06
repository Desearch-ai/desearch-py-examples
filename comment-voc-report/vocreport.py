#!/usr/bin/env python3
"""Comment Voice-of-Customer Report. Made by Desearch (https://desearch.ai).

Pulls a public brand's latest posts on Instagram and/or TikTok through the Desearch API,
pulls the public comments on each post, sorts every comment into a bucket
(question, complaint, request, praise, other) and writes:
  - report.md   counts per bucket + the 5 most-liked comments per bucket with post links
  - comments.csv  every comment with its bucket
  - run.json    every API call with status, items and cost (from X-Desearch-Cost-Usd)
  - raw/        raw API responses (the API key is never written)

Env: DESEARCH_API_KEY (required). Optional LLM classifier: VOC_LLM_API_KEY, VOC_LLM_BASE_URL, VOC_LLM_MODEL.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import importlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from typing import Protocol

import requests

API_BASE = "https://api.desearch.ai"
BUCKETS = ["question", "complaint", "request", "praise", "other"]
PLATFORM_TITLES = {"instagram": "Instagram", "tiktok": "TikTok"}
BUCKET_TITLES = {
    "question": "Questions",
    "complaint": "Complaints",
    "request": "Feature / product requests",
    "praise": "Praise",
    "other": "Other",
}
# Instagram and TikTok both allow up to 3 pinned posts, and pinned posts come first in
# /profile/{username}/posts (seen 2026-10-06). We fetch a few extra and keep the newest N.
PINNED_SLACK = 3


# --------------------------------------------------------------------------- data model
@dataclass
class Post:
    platform: str
    id: str  # id used for the comments call (IG shortcode, TikTok video id)
    url: str
    created_utc: str
    caption: str
    comment_count: int | None
    like_count: int | None


@dataclass
class Comment:
    platform: str
    brand: str
    post_id: str
    post_url: str
    post_created_utc: str
    key: str  # comment id, or author_id|createTime when the API gives no id (TikTok)
    comment_id: str
    created_utc: str
    likes: int | None
    replies: int
    author: str
    text: str
    bucket: str = ""
    rule: str = ""


def to_utc_iso(v) -> str:
    """createTime comes as epoch seconds (TikTok comments, IG/TikTok posts) or an ISO string (IG comments)."""
    if v is None or v == "":
        return ""
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
        return dt.datetime.fromtimestamp(int(v), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return str(v)


# --------------------------------------------------------------------------- Desearch client
class Desearch:
    def __init__(self, api_key: str, raw_dir: str | None = None, retries: int = 1):
        self.key = api_key
        self.raw_dir = raw_dir
        self.retries = retries
        self.calls: list[dict] = []

    def get(self, path: str, params: dict, label: str):
        url = API_BASE + path
        attempt = 0
        while True:
            t = time.perf_counter()
            r = requests.get(url, headers={"Authorization": self.key}, params=params, timeout=120)
            elapsed = round(time.perf_counter() - t, 2)
            try:
                body = r.json()
            except ValueError:
                body = {"_raw_text": r.text[:5000]}
            call = {
                "when": dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z"),
                "path": path, "params": params, "status": r.status_code, "latency_s": elapsed,
                "items": len(body) if isinstance(body, list) else None,
                "cost_usd": float(r.headers.get("X-Desearch-Cost-Usd") or 0),
                "usage_count": int(r.headers.get("X-Desearch-Usage-Count") or 0),
                "service": r.headers.get("X-Desearch-Service"),
                "attempt": attempt + 1,
            }
            self.calls.append(call)
            if self.raw_dir:
                os.makedirs(self.raw_dir, exist_ok=True)
                fn = os.path.join(self.raw_dir, f"{len(self.calls):03d}-{label}.json")
                rec = {"request": {"method": "GET", "url": url, "params": params,
                                   "headers": {"Authorization": "<redacted>"}},
                       "call": call, "response_headers": {k: v for k, v in r.headers.items() if k.lower().startswith("x-desearch")},
                       "response": body}
                s = json.dumps(rec, indent=2, ensure_ascii=False)
                assert self.key not in s
                with open(fn, "w") as f:
                    f.write(s)
            # 503 "Service request failed" happened once on 2026-10-06 and was not billed; retry once.
            if r.status_code in (429, 500, 502, 503, 504) and attempt < self.retries:
                attempt += 1
                time.sleep(5)
                continue
            return r.status_code, body

    @property
    def spend(self) -> float:
        return round(sum(c["cost_usd"] for c in self.calls), 6)


def drop_pinned(posts_in_api_order: list) -> list:
    """Pinned posts (up to 3) come first in profile posts even when they are old (seen on both platforms
    2026-10-06). A post among the first 3 that is older than any post after it is treated as pinned and dropped."""
    keep = []
    for i, p in enumerate(posts_in_api_order):
        later = [q.created_utc for q in posts_in_api_order[i + 1:]]
        if i < PINNED_SLACK and later and p.created_utc < max(later):
            print(f"  - dropped pinned {p.platform} post {p.id} ({p.created_utc[:10]})", file=sys.stderr)
            continue
        keep.append(p)
    return keep


# --------------------------------------------------------------------------- platforms
class Platform:
    name = ""
    posts_path = ""
    comments_path = ""

    def parse_post(self, p: dict) -> Post: ...
    def parse_comment(self, c: dict, brand: str, post: Post) -> Comment: ...

    def latest_posts(self, api: Desearch, username: str, n: int) -> list[Post]:
        status, body = api.get(self.posts_path.format(username=username),
                               {"count": min(100, n + PINNED_SLACK)}, f"{self.name}-posts-{username}")
        if status != 200 or not isinstance(body, list):
            raise RuntimeError(f"{self.name}: profile posts for '{username}' returned HTTP {status}: {str(body)[:200]}")
        posts = drop_pinned([self.parse_post(p) for p in body])
        posts.sort(key=lambda p: p.created_utc, reverse=True)
        return posts[:n]

    def comments(self, api: Desearch, brand: str, post: Post, count: int) -> list[Comment]:
        status, body = api.get(self.comments_path.format(id=post.id), {"count": count},
                               f"{self.name}-comments-{post.id}")
        if status != 200 or not isinstance(body, list):
            print(f"  ! {self.name} comments {post.id}: HTTP {status}, skipped", file=sys.stderr)
            return []
        out, seen = [], set()
        for c in body:
            cm = self.parse_comment(c, brand, post)
            if cm.key in seen:
                continue
            seen.add(cm.key)
            out.append(cm)
        return out


class Instagram(Platform):
    name = "instagram"
    posts_path = "/desearch/instagram/profile/{username}/posts"
    comments_path = "/desearch/instagram/comments/{id}"

    def parse_post(self, p):
        st = p.get("stats") or {}
        return Post("instagram", p.get("shortcode") or p.get("id"), p.get("url") or f"https://www.instagram.com/p/{p.get('shortcode')}/",
                    to_utc_iso(p.get("createTime")), (p.get("caption") or "").strip(),
                    st.get("commentCount"), st.get("likeCount"))

    def parse_comment(self, c, brand, post):
        a = c.get("author") or {}
        cid = str(c.get("id") or "")
        created = to_utc_iso(c.get("createTime"))
        return Comment("instagram", brand, post.id, post.url, post.created_utc,
                       cid or f"{a.get('id')}|{created}", cid, created, c.get("likes"),
                       len(c.get("replies") or []), a.get("username") or "", (c.get("text") or "").strip())


class TikTok(Platform):
    name = "tiktok"
    posts_path = "/desearch/tiktok/profile/{username}/posts"
    comments_path = "/desearch/tiktok/comments/{id}"

    def parse_post(self, p):
        st = p.get("stats") or {}
        return Post("tiktok", str(p.get("id")), p.get("url") or "", to_utc_iso(p.get("createTime")),
                    (p.get("text") or "").strip(), st.get("commentCount"), st.get("digCount"))

    def parse_comment(self, c, brand, post):
        a = c.get("author") or {}
        cid = str(c.get("id") or "")
        created = to_utc_iso(c.get("createTime"))
        # TikTok comments came back without an `id` on 2026-10-06, so build a stable key.
        return Comment("tiktok", brand, post.id, post.url, post.created_utc,
                       cid or f"{a.get('id')}|{created}", cid, created, c.get("likes"),
                       len(c.get("replies") or []), a.get("username") or "", (c.get("text") or "").strip())


PLATFORMS = {"instagram": Instagram(), "tiktok": TikTok()}


# --------------------------------------------------------------------------- classifiers
class Classifier(Protocol):
    name: str

    def classify(self, comments: list[Comment]) -> list[tuple[str, str]]:
        """Return one (bucket, reason) per comment, bucket in BUCKETS."""


class KeywordClassifier:
    """Default: ordered keyword / regex rules. First match wins: request, complaint, question, praise, other.
    English first, plus a few common Spanish and Portuguese words (brand comment sections are multilingual)."""
    name = "keyword"

    RULES: list[tuple[str, list[str]]] = [
        ("request", [
            r"\bplease (add|make|bring|do|put|give|release|let|include|have|create)\b",
            r"\bpl(s|z)\b.*\b(add|make|bring)\b", r"\b(add|bring back|bring)\b.{0,40}\b(please|pls|plz)\b",
            r"\bwe need\b", r"\bi need\b.{0,30}\b(course|lesson|version|feature|option|mode)\b",
            r"\bcan you (add|make|bring|do)\b", r"\bcould you (add|make|bring)\b", r"\bwhen (will|are) you (add|bring|release|launch)",
            r"\byou should (add|make|do|bring)\b", r"\bi wish (you|there|it|they)\b", r"\bwould love (a|an|to see|if)\b",
            r"\b(feature|course|lesson) request\b", r"\bnext (course|language|lesson) should\b",
            r"\bagreguen\b", r"\bagregen\b", r"\bpongan\b", r"\bpor favor (agreg|pong|hag|saqu)", r"\bqueremos\b",
            r"\bcoloquem\b", r"\badicionem\b",
            r"^(please |pls |plz )?add\b", r"\b(now )?(it'?s )?time to add\b", r"\bimagine if .{0,40}\badd", r"\basking .{0,40}\bto add\b",
            r"\bhope you('ll| will) add\b", r"\bif you had\b", r"\bgive us\b", r"\bi (need|want) (the|a|an|one)\b",
            r"\bmake an? update\b", r"\bbring back\b", r"\brestore\b", r"\bверните\b", r"\bдобавьте\b",
        ]),
        ("complaint", [
            r"\b(doesn'?t|does not|isn'?t|won'?t|can'?t|cannot|didn'?t) work", r"\bnot working\b", r"\bbroken\b", r"\bbug(gy|s)?\b",
            r"\bcrash(es|ed|ing)?\b", r"\bglitch", r"\bscam\b", r"\brefund\b", r"\bworst\b", r"\bterrible\b", r"\bawful\b",
            r"\bhate (it|this|the|that|how|when)\b", r"\bdisappoint", r"\bannoying\b", r"\bridiculous\b", r"\btoo (many|much|expensive)\b",
            r"\bunsubscrib", r"\bcancel(l?ed|ling)? my\b", r"\bdeleted? (the|this|your) app\b", r"\buninstall", r"\bwaste of\b",
            r"\b(stop|quit) (sending|spamming|adding)\b", r"\bpaywall\b", r"\bads? (every|after|are)\b", r"\b(completely |totally |so )?wrong\b",
            r"\bhate (you|duo|u)\b", r"\bcringe\b", r"😡|🤮|👎", r"\blost my (\d+[- ]?day )?streak\b", r"\bstreak (is )?gone\b",
            r"\bwhy (did|would|do) you (remove|change|take|get rid)", r"\bno longer\b", r"\bnever (got|received|arrived)\b",
            r"\bpésim", r"\bodio\b", r"\bno sirve\b", r"\bhorrible\b", r"\bmalísim", r"\bp[eé]ssim",
        ]),
        ("question", [
            r"\?", r"^(how|when|where|why|who|which|is|are|can|could|do|does|did|will|would|should)\b", r"^what (is|are|if|do|does|did|was|happens)\b",
            r"\banyone know\b", r"\bwondering\b", r"^(cómo|qué|cuándo|dónde|por qué|quién)\b", r"^q(ue)? pasa si\b", r"¿",
        ]),
        ("praise", [
            r"\blove\b", r"\bloved\b", r"\bloving\b", r"\bamazing\b", r"\bawesome\b", r"\bbest\b", r"\bgreat\b", r"\bperfect\b",
            r"\bobsessed\b", r"\bfavou?rite\b", r"\bslay", r"\biconic\b", r"\blegend", r"\bgenius\b", r"\bcute\b", r"\bthank(s| you)\b",
            r"\bso good\b", r"\bbeautiful\b", r"\bgorgeous\b", r"\bqueen\b", r"\bking\b", r"\bfire\b", r"\bgoat(ed)?\b",
            r"❤|😍|🥰|💜|💚|🔥|👏|🙌|😻|💕|💖", r"\bme encanta", r"\bte amo\b", r"\bte quiero\b", r"\blo mejor\b", r"\bincre[ií]ble\b",
            r"\bamo\b", r"\bmelhor\b", r"\bperfeit", r"\bhermos",
        ]),
    ]

    def __init__(self):
        self.compiled = [(b, [re.compile(p, re.I) for p in pats]) for b, pats in self.RULES]

    def classify_text(self, text: str) -> tuple[str, str]:
        t = (text or "").strip()
        if not t:
            return "other", "empty"
        for bucket, pats in self.compiled:
            for p in pats:
                if p.search(t):
                    return bucket, f"{bucket}:{p.pattern}"
        return "other", "no rule matched"

    def classify(self, comments):
        return [self.classify_text(c.text) for c in comments]


class LLMClassifier:
    """Optional step behind the same interface: any /chat/completions endpoint
    with the usual messages JSON. Configure with VOC_LLM_BASE_URL, VOC_LLM_API_KEY, VOC_LLM_MODEL.
    Falls back to keyword rules per batch on error."""
    name = "llm"
    PROMPT = ("You label public social media comments left on a brand's posts. For each comment, choose exactly one label: "
              "question, complaint, request (a feature or product request), praise, other. "
              "Reply with only a JSON array of labels, same order and length as the input.")

    def __init__(self, base_url: str, api_key: str, model: str, batch: int = 25):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.batch = batch
        self.fallback = KeywordClassifier()

    def classify(self, comments):
        out = []
        for i in range(0, len(comments), self.batch):
            chunk = comments[i:i + self.batch]
            try:
                r = requests.post(f"{self.base_url}/chat/completions", timeout=120,
                                  headers={"Authorization": f"Bearer {self.api_key}"},
                                  json={"model": self.model, "temperature": 0, "messages": [
                                      {"role": "system", "content": self.PROMPT},
                                      {"role": "user", "content": json.dumps([c.text for c in chunk], ensure_ascii=False)}]})
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"]
                labels = json.loads(content[content.find("["): content.rfind("]") + 1])
                if len(labels) != len(chunk):
                    raise ValueError(f"got {len(labels)} labels for {len(chunk)} comments")
                for lab in labels:
                    lab = str(lab).strip().lower()
                    out.append((lab if lab in BUCKETS else "other", f"llm:{self.model}"))
            except Exception as e:  # keep the pipeline running
                print(f"  ! LLM batch failed ({e}); keyword rules used for this batch", file=sys.stderr)
                out.extend((b, "fallback-" + r_) for b, r_ in self.fallback.classify(chunk))
        return out


def make_classifier(spec: str) -> Classifier:
    if spec == "keyword":
        return KeywordClassifier()
    if spec == "llm":
        missing = [v for v in ("VOC_LLM_BASE_URL", "VOC_LLM_API_KEY", "VOC_LLM_MODEL") if not os.environ.get(v)]
        if missing:
            sys.exit(f"--classifier llm needs env vars: {', '.join(missing)}")
        return LLMClassifier(os.environ["VOC_LLM_BASE_URL"], os.environ["VOC_LLM_API_KEY"], os.environ["VOC_LLM_MODEL"])
    if ":" in spec:  # plug in your own: module.path:ClassName (needs a classify(comments) method)
        mod, cls = spec.split(":", 1)
        return getattr(importlib.import_module(mod), cls)()
    sys.exit(f"unknown classifier '{spec}' (use keyword, llm or module:Class)")


# --------------------------------------------------------------------------- output
def clean(text: str, limit: int = 220) -> str:
    t = re.sub(r"\s+", " ", text or "").replace("|", "/").replace("\u2014", "-")
    return t if len(t) <= limit else t[: limit - 3] + "..."


def top_by_likes(comments: list[Comment], n: int = 5) -> list[Comment]:
    return sorted(comments, key=lambda c: (c.likes or 0, c.created_utc), reverse=True)[:n]


def write_csv(path: str, comments: list[Comment]):
    cols = ["platform", "brand", "post_id", "post_url", "post_created_utc", "key", "comment_id", "created_utc",
            "likes", "replies", "author", "bucket", "rule", "text"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for c in comments:
            w.writerow({k: asdict(c)[k] for k in cols})


def fill_rate(comments, attr, positive=False):
    if not comments:
        return "n/a"
    vals = [getattr(c, attr) for c in comments]
    filled = [v for v in vals if v not in (None, "")]
    s = f"{len(filled)}/{len(vals)}"
    if positive:
        s += f" (non-zero {sum(1 for v in filled if v)}/{len(vals)})"
    return s


def render_report(meta: dict, posts: dict[str, list[Post]], comments: list[Comment], api: Desearch, classifier: str) -> str:
    L = []
    title = " + ".join(f"@{u} ({PLATFORM_TITLES[p]})" for p, u in meta["accounts"])
    L.append(f"# Comment Voice-of-Customer Report: {title}")
    L.append("")
    L.append("Made by Desearch ([desearch.ai](https://desearch.ai)). Public comments only, pulled with the Desearch API.")
    L.append("")
    L.append(f"- Run: {meta['run_local']} (Asia/Tbilisi)")
    L.append("- Accounts: " + ", ".join(f"{PLATFORM_TITLES[p]} @{u}" for p, u in meta["accounts"]))
    L.append(f"- Posts per platform: up to the newest {meta['posts']} (pinned posts dropped); comments requested per post: {meta['comments']}")
    L.append(f"- Classifier: {classifier}")
    L.append(f"- Desearch calls: {len(api.calls)}, cost ${api.spend:.5f} (sum of X-Desearch-Cost-Usd headers)")
    if meta.get("cost_note"):
        L.append(f"- {meta['cost_note']}")
    L.append("")
    L.append("## Counts per bucket")
    L.append("")
    plats = [p for p, _ in meta["accounts"]]
    L.append("| Bucket | " + " | ".join(PLATFORM_TITLES[p] for p in plats) + " | Total | Share |")
    L.append("|---|" + "---|" * len(plats) + "---|---|")
    total = len(comments) or 1
    for b in BUCKETS:
        row = [sum(1 for c in comments if c.bucket == b and c.platform == p) for p in plats]
        L.append(f"| {BUCKET_TITLES[b]} | " + " | ".join(map(str, row)) + f" | {sum(row)} | {100 * sum(row) / total:.0f}% |")
    L.append("| **All comments** | " + " | ".join(str(sum(1 for c in comments if c.platform == p)) for p in plats) + f" | {len(comments)} | 100% |")
    L.append("")
    for b in BUCKETS:
        items = [c for c in comments if c.bucket == b and c.text.strip()]
        L.append(f"## Top {min(5, len(items))} most-liked: {BUCKET_TITLES[b]}")
        L.append("")
        if not items:
            L.append("No comments in this bucket.")
            L.append("")
            continue
        L.append("| Likes | Platform | Comment | Posted (UTC) | Post |")
        L.append("|---|---|---|---|---|")
        for c in top_by_likes(items):
            L.append(f"| {c.likes if c.likes is not None else 'n/a'} | {PLATFORM_TITLES[c.platform]} | {clean(c.text)} | {c.created_utc[:16].replace('T', ' ')} | [post]({c.post_url}) |")
        L.append("")
    L.append("## Posts covered")
    L.append("")
    L.append("| Platform | Posted (UTC) | Comments shown on post | Comments pulled | Caption | Link |")
    L.append("|---|---|---|---|---|---|")
    for plat, plist in posts.items():
        for p in plist:
            n = sum(1 for c in comments if c.platform == plat and c.post_id == p.id)
            L.append(f"| {PLATFORM_TITLES[plat]} | {p.created_utc[:16].replace('T', ' ')} | {p.comment_count if p.comment_count is not None else 'n/a'} | {n} | {clean(p.caption, 60)} | [open]({p.url}) |")
    L.append("")
    L.append("## Data notes")
    L.append("")
    for plat in plats:
        cs = [c for c in comments if c.platform == plat]
        empty = sum(1 for c in cs if not c.text.strip())
        L.append(f"- {PLATFORM_TITLES[plat]}: `createTime` filled {fill_rate(cs, 'created_utc')}, `likes` filled {fill_rate(cs, 'likes', True)}, comment `id` filled {fill_rate(cs, 'comment_id')}, comments with empty `text` {empty} (kept in the CSV, left out of the top lists).")
    L.append("- \"Most-liked\" sorts by the `likes` field, newest first on ties. Comment text is shown as returned (whitespace collapsed, long comments cut).")
    L.append("- Buckets come from simple rules (or your own classifier). Treat them as a first sort, then read the comments.")
    L.append("")
    return "\n".join(L)


class _SavedCalls:
    """Stands in for Desearch when re-rendering a saved run: same calls list, same spend."""
    def __init__(self, calls):
        self.calls = calls

    @property
    def spend(self):
        return round(sum(c["cost_usd"] for c in self.calls), 6)


def reclassify(run_dir: str, classifier, out: str) -> str:
    run = json.load(open(os.path.join(run_dir, "run.json"), encoding="utf-8"))
    meta = run["meta"]
    meta["accounts"] = [tuple(x) for x in meta["accounts"]]
    posts = {k: [Post(**p) for p in v] for k, v in run["posts"].items()}
    comments = []
    with open(os.path.join(run_dir, "comments.csv"), encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            row["likes"] = int(row["likes"]) if row["likes"] not in ("", None) else None
            row["replies"] = int(row["replies"] or 0)
            comments.append(Comment(**row))
    # Apply today's pinned-post rule using the API order saved in raw/ (runs made before the rule existed).
    raw_dir = os.path.join(run_dir, "raw")
    dropped = []
    if os.path.isdir(raw_dir):
        for fn in sorted(os.listdir(raw_dir)):
            m = re.match(r"\d+-(instagram|tiktok)-posts-", fn)
            if not m:
                continue
            body = json.load(open(os.path.join(raw_dir, fn), encoding="utf-8"))["response"]
            P = PLATFORMS[m.group(1)]
            api_order = [P.parse_post(p) for p in body]
            kept = {p.id for p in drop_pinned(api_order)}
            dropped += [(m.group(1), p.id) for p in api_order if p.id not in kept]
    if dropped:
        cost_of_dropped, with_comments = 0.0, 0
        for plat, pid in dropped:
            posts[plat] = [p for p in posts.get(plat, []) if p.id != pid]
            n = sum(1 for c in comments if c.platform == plat and c.post_id == pid)
            comments = [c for c in comments if not (c.platform == plat and c.post_id == pid)]
            cost_of_dropped += sum(c["cost_usd"] for c in run["calls"] if c["path"].endswith("/" + pid) and c["status"] == 200)
            with_comments += 1 if n else 0
            print(f"  - left out {n} comments of pinned {plat} post {pid}", file=sys.stderr)
        meta["cost_note"] = (f"The cost above includes ${cost_of_dropped:.5f} for comments on {with_comments} pinned post(s) "
                             f"that this report leaves out (pinned-post rule added after the run).") if with_comments else None
    for c, (b, why) in zip(comments, classifier.classify(comments)):
        c.bucket, c.rule = b, why
    outdir = os.path.join(out, f"{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-reclassified-{os.path.basename(run_dir.rstrip('/'))}")
    os.makedirs(outdir, exist_ok=True)
    api = _SavedCalls(run["calls"])
    meta["reclassified_from"] = run_dir
    report = render_report(meta, posts, comments, api, getattr(classifier, "name", type(classifier).__name__))
    report = report.replace("## Counts per bucket", f"Comments pulled in the run above; buckets re-computed offline on {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} (Asia/Tbilisi) with `--from-run`, no new API calls.\n\n## Counts per bucket", 1)
    with open(os.path.join(outdir, "report.md"), "w", encoding="utf-8") as f:
        f.write(report)
    write_csv(os.path.join(outdir, "comments.csv"), comments)
    with open(os.path.join(outdir, "run.json"), "w", encoding="utf-8") as f:
        json.dump({**run, "meta": meta}, f, indent=2, ensure_ascii=False)
    counts = {b: sum(1 for c in comments if c.bucket == b) for b in BUCKETS}
    print(json.dumps({"out": outdir, "comments": len(comments), "buckets": counts, "new_api_calls": 0}), file=sys.stderr)
    return outdir


# --------------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description="Sort a public brand's Instagram / TikTok comments into questions, complaints, requests and praise.")
    ap.add_argument("--instagram", metavar="USERNAME", help="public Instagram username, without @")
    ap.add_argument("--tiktok", metavar="USERNAME", help="public TikTok username, without @")
    ap.add_argument("--posts", type=int, default=10, help="newest posts per platform (default 10)")
    ap.add_argument("--comments", type=int, default=30, help="comments requested per post, 1-100 (default 30)")
    ap.add_argument("--classifier", default="keyword", help="keyword (default), llm, or module:ClassName")
    ap.add_argument("--out", default="runs", help="output folder (a timestamped subfolder is created)")
    ap.add_argument("--max-spend", type=float, default=1.50, help="stop pulling comments once this many USD were spent (default 1.50)")
    ap.add_argument("--no-raw", action="store_true", help="do not save raw API responses")
    ap.add_argument("--from-run", metavar="DIR", help="re-classify a saved run (no API calls, no cost) and write a new report")
    a = ap.parse_args(argv)
    if a.from_run:
        return reclassify(a.from_run, make_classifier(a.classifier), a.out)
    if not (a.instagram or a.tiktok):
        ap.error("give --instagram and/or --tiktok")
    key = os.environ.get("DESEARCH_API_KEY")
    if not key:
        sys.exit("set DESEARCH_API_KEY (get a key at console.desearch.ai)")
    accounts = [(p, u.lstrip("@")) for p, u in (("instagram", a.instagram), ("tiktok", a.tiktok)) if u]
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = "-".join(dict.fromkeys(u for _, u in accounts))
    outdir = os.path.join(a.out, f"{stamp}-{re.sub(r'[^A-Za-z0-9_.-]', '', slug)}")
    os.makedirs(outdir, exist_ok=True)
    api = Desearch(key, None if a.no_raw else os.path.join(outdir, "raw"))
    classifier = make_classifier(a.classifier)

    posts: dict[str, list[Post]] = {}
    comments: list[Comment] = []
    for plat, user in accounts:
        P = PLATFORMS[plat]
        try:
            posts[plat] = P.latest_posts(api, user, a.posts)
        except RuntimeError as e:
            print(f"! {e}", file=sys.stderr)
            posts[plat] = []
        if not posts[plat]:
            print(f"! {plat} @{user}: no public posts found (check the username)", file=sys.stderr)
        print(f"{plat} @{user}: {len(posts[plat])} posts", file=sys.stderr)
        for p in posts[plat]:
            if api.spend >= a.max_spend:
                print(f"! spend cap ${a.max_spend} reached, stopping", file=sys.stderr)
                break
            got = P.comments(api, user, p, a.comments)
            print(f"  {p.created_utc[:10]} {p.id}: {len(got)} comments (post shows {p.comment_count})", file=sys.stderr)
            comments.extend(got)

    for c, (b, why) in zip(comments, classifier.classify(comments)):
        c.bucket, c.rule = b, why

    meta = {"title": " + ".join(f"@{u} ({p})" for p, u in accounts), "accounts": accounts, "posts": a.posts,
            "comments": a.comments, "run_local": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}
    report = render_report(meta, posts, comments, api, getattr(classifier, "name", type(classifier).__name__))
    with open(os.path.join(outdir, "report.md"), "w", encoding="utf-8") as f:
        f.write(report)
    write_csv(os.path.join(outdir, "comments.csv"), comments)
    with open(os.path.join(outdir, "run.json"), "w") as f:
        json.dump({"meta": meta, "spend_usd": api.spend, "calls": api.calls,
                   "posts": {k: [asdict(p) for p in v] for k, v in posts.items()}}, f, indent=2, ensure_ascii=False)
    counts = {b: sum(1 for c in comments if c.bucket == b) for b in BUCKETS}
    print(json.dumps({"out": outdir, "comments": len(comments), "buckets": counts, "calls": len(api.calls),
                      "spend_usd": api.spend}), file=sys.stderr)
    return outdir


if __name__ == "__main__":
    main()
