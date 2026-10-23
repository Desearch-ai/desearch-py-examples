"""Turn a Desearch topic search into an RSS 2.0 feed (Python 3.10+)."""
import argparse
from datetime import date, datetime, time as day_time, timedelta, timezone
from email.utils import format_datetime
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

API_URL = "https://api.desearch.ai/search"
CACHE_DIR = Path(__file__).parent / ".cache"
CACHE_TTL = 6 * 60 * 60


def validate_topic(topic):
    topic = topic.strip()
    if not topic or len(topic) > 200:
        raise ValueError("Topic must contain 1 to 200 characters")
    return topic


def build_request_body(topic, days=7, count=20, today=None):
    topic = validate_topic(topic)
    if days < 1:
        raise ValueError("days must be positive")
    if count not in (10, 15, 20):
        raise ValueError("count must be 10, 15, or 20")
    today = today or date.today()
    return {"query": topic, "mode": "balanced", "count": count,
            "start_date": (today - timedelta(days=days)).isoformat(),
            "end_date": today.isoformat(), "highlights": True}


def fetch_results(topic, api_key, days=7, count=20, today=None,
                  cache_dir=CACHE_DIR, no_cache=False, timeout=30):
    if not api_key or not api_key.strip():
        raise ValueError("Missing DESEARCH_API_KEY environment variable")
    body = build_request_body(topic, days, count, today)
    started = time.perf_counter()
    key = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    path = Path(cache_dir) / (key + ".json")
    if not no_cache:
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if 0 <= time.time() - cached["saved_at"] < CACHE_TTL:
                return cached["results"], {"cost_usd": 0, "latency_s": time.perf_counter() - started,
                                           "cache_hit": True}
        except (OSError, ValueError, KeyError, TypeError):
            pass
    request = urllib.request.Request(API_URL, data=json.dumps(body).encode(), method="POST",
        headers={"Authorization": api_key, "User-Agent": "desearch-topic-to-rss/0.1",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Desearch API HTTP error {exc.code}") from None
    except urllib.error.URLError:
        raise RuntimeError("Unable to connect to Desearch API") from None
    results = payload["results"]
    meta = {name: payload.get(name) for name in ("cost_usd", "usage_count", "service", "currency")}
    meta.update(latency_s=time.perf_counter() - started, cache_hit=False)
    if not no_cache:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             delete=False) as handle:
                temporary = Path(handle.name)
                json.dump({"saved_at": time.time(), "results": results}, handle)
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return results, meta


def normalized_url(url):
    parts = urllib.parse.urlsplit(url)
    host = parts.netloc.lower()
    query = urllib.parse.urlencode([(k, v) for k, v in urllib.parse.parse_qsl(
        parts.query, keep_blank_values=True) if not k.lower().startswith("utm_")])
    return urllib.parse.urlunsplit((parts.scheme.lower(), host, parts.path.rstrip("/"), query, ""))


def normalize(results):
    items, urls, titles = [], set(), set()
    for result in results:
        try:
            published = date.fromisoformat(result["published_date"])
        except (ValueError, TypeError, KeyError):
            continue
        url = normalized_url(result.get("url", ""))
        title = re.split(r"\s+[|]\s*|\s+-\s+", result.get("title", "").strip().lower())[0].strip()
        if not url or url in urls or title in titles:
            continue
        urls.add(url)
        titles.add(title)
        items.append(dict(result, url=url, published_date=published.isoformat()))
    return sorted(items, key=lambda item: item["published_date"], reverse=True)


def clean(text):
    return "".join(c for c in str(text) if ord(c) >= 32 and
                   (ord(c) <= 0xD7FF or 0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF))


def build_rss(topic, items, now=None, self_url=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    root = ET.Element("rss", version="2.0")
    channel = ET.SubElement(root, "channel")
    def add(parent, tag, text, **attrs):
        ET.SubElement(parent, tag, attrs).text = clean(text)
    add(channel, "title", f"Desearch: {topic}")
    add(channel, "link", "https://desearch.ai")
    add(channel, "description", f"The newest dated pages for {topic}, via the Desearch API")
    add(channel, "lastBuildDate", format_datetime(now))
    if self_url:
        ET.register_namespace("atom", "http://www.w3.org/2005/Atom")
        ET.SubElement(channel, "{http://www.w3.org/2005/Atom}link",
                      href=clean(self_url), rel="self", type="application/rss+xml")
    for item in items:
        entry = ET.SubElement(channel, "item")
        add(entry, "title", item.get("title", ""))
        add(entry, "link", item["url"])
        add(entry, "guid", item["url"], isPermaLink="true")
        published = datetime.combine(date.fromisoformat(item["published_date"]), day_time(), timezone.utc)
        add(entry, "pubDate", format_datetime(published))
        highlights = item.get("highlights") or []
        add(entry, "description", clean(highlights[0])[:500] if highlights else "")
    ET.indent(root)
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode")


def report(meta):
    print(f"cost_usd={meta['cost_usd']} latency_s={meta['latency_s']:.3f} cache_hit={meta['cache_hit']}", file=sys.stderr)


def make_handler(days=7, count=20, cache_dir=CACHE_DIR, no_cache=False):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path != "/feed":
                self.send_error(404)
                return
            try:
                topic = validate_topic(urllib.parse.parse_qs(parsed.query).get("topic", [""])[0])
            except ValueError as exc:
                self.send_error(400, str(exc))
                return
            try:
                results, meta = fetch_results(topic, os.environ.get("DESEARCH_API_KEY"),
                    days=days, count=count, cache_dir=cache_dir, no_cache=no_cache)
                xml = build_rss(topic, normalize(results)).encode("utf-8")
                report(meta)
            except (ValueError, RuntimeError, OSError, KeyError) as exc:
                self.send_error(502, str(exc))
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/rss+xml; charset=utf-8")
            self.send_header("Content-Length", str(len(xml)))
            self.end_headers()
            self.wfile.write(xml)
        def log_message(self, format, *args):
            pass
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("topic", nargs="?")
    parser.add_argument("-o", "--output")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--count", type=int, choices=(10, 15, 20), default=20)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        api_key = os.environ.get("DESEARCH_API_KEY")
        if not api_key:
            raise ValueError("Missing DESEARCH_API_KEY environment variable")
        if args.days < 1:
            raise ValueError("days must be positive")
        if args.serve:
            server = ThreadingHTTPServer(("127.0.0.1", args.port),
                make_handler(args.days, args.count, no_cache=args.no_cache))
            print(f"Serving http://127.0.0.1:{args.port}/feed?topic=bittensor", file=sys.stderr)
            try:
                server.serve_forever()
            finally:
                server.server_close()
        else:
            results, meta = fetch_results(args.topic or "", api_key, args.days, args.count, no_cache=args.no_cache)
            xml = build_rss(args.topic.strip(), normalize(results))
            if args.output:
                Path(args.output).write_text(xml + "\n", encoding="utf-8")
            else:
                print(xml)
            report(meta)
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
