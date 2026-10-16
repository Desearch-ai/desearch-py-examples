"""Pure helpers for page2md.py (no network): HTML to Markdown, empty check, slugs, cost, redaction."""
import re
from urllib.parse import urljoin
from html.parser import HTMLParser

# Public Extract rate (desearch.ai/pricing, checked 2026-10-15): $0.50 per 1,000 pages.
# Shown for reference only; totals use the X-Desearch-Cost-Usd header.
EXTRACT_RATE = 0.0005

SKIP = {"script", "style", "noscript", "template", "svg", "head", "nav", "footer", "form", "iframe", "button"}
VOID = {"br", "img", "meta", "link", "input", "hr", "source", "wbr", "area", "col", "embed", "base", "track"}
SKIP_CLASS = {"related", "sphinxsidebar", "headerlink", "skip-link", "visually-hidden", "sr-only"}
BLOCK = {"p", "div", "section", "article", "main", "header", "aside", "table", "tr", "br", "hr", "figure", "blockquote", "dl", "dd", "dt"}


class _MD(HTMLParser):
    def __init__(self, base=""):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.out, self.skip, self.title, self.in_title = [], 0, "", False
        self.href, self.link_text, self.pre, self.lists, self.links = None, [], 0, [], []

    def _w(self, s):
        (self.link_text if self.href is not None else self.out).append(s)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self.in_title = True
        if self.skip:
            if tag not in VOID:
                self.skip += 1
            return
        if tag in SKIP or a.get("role") in ("navigation", "search") or a.get("aria-hidden") == "true" \
                or set((a.get("class") or "").split()) & SKIP_CLASS:
            if tag not in VOID:
                self.skip = 1
            return
        if re.fullmatch(r"h[1-6]", tag):
            self._w("\n\n" + "#" * int(tag[1]) + " ")
        elif tag in BLOCK:
            self._w("\n\n")
        elif tag in ("ul", "ol"):
            self.lists.append([tag, 0]); self._w("\n")
        elif tag == "li":
            lvl = max(len(self.lists) - 1, 0)
            mark = "-"
            if self.lists and self.lists[-1][0] == "ol":
                self.lists[-1][1] += 1; mark = f"{self.lists[-1][1]}."
            self._w("\n" + "  " * lvl + mark + " ")
        elif tag == "pre":
            self.pre += 1; self._w("\n\n```\n")
        elif tag == "code" and not self.pre:
            self._w("`")
        elif tag in ("strong", "b"):
            self._w("**")
        elif tag in ("em", "i"):
            self._w("*")
        elif tag in ("td", "th"):
            self._w(" | ")
        elif tag == "a" and a.get("href") and not a["href"].startswith(("#", "javascript:")):
            self.href, self.link_text = a["href"], []

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if self.skip:
            if tag not in VOID:
                self.skip -= 1
            return
        if tag == "a" and self.href is not None:
            text = re.sub(r"\s+", " ", "".join(self.link_text)).strip()
            text = re.sub(r"(^|\s)#{1,6}\s", r"\1", text).strip()
            href, self.href = (urljoin(self.base, self.href) if self.base else self.href), None
            if text:
                self.links.append(href)
                self._w(f"[{text}]({href})")
        elif re.fullmatch(r"h[1-6]", tag) or tag in BLOCK:
            self._w("\n\n")
        elif tag in ("ul", "ol"):
            if self.lists: self.lists.pop()
            self._w("\n")
        elif tag == "pre":
            self.pre = max(self.pre - 1, 0); self._w("\n```\n\n")
        elif tag == "code" and not self.pre:
            self._w("`")
        elif tag in ("strong", "b"):
            self._w("**")
        elif tag in ("em", "i"):
            self._w("*")

    def handle_data(self, data):
        if self.in_title:
            self.title += data
            return
        if self.skip:
            return
        self._w(data if self.pre else re.sub(r"\s+", " ", data))


def html_to_markdown(html_text, base=""):
    """Return (title, markdown, links). Drops scripts, styles, nav, footer and forms; resolves links against base."""
    p = _MD(base)
    p.feed(html_text or "")
    p.close()
    md = "".join(p.out)
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n[ ](?=\S)", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md).strip().replace("\u2014", " - ").replace("\u00b6", "")
    return re.sub(r"\s+", " ", p.title.replace("\u2014", "-")).strip(), md, list(dict.fromkeys(p.links))


def text_to_markdown(text):
    """For format=text bodies: keep paragraphs, collapse runs of blank lines."""
    return re.sub(r"\n{3,}", "\n\n", (text or "").replace("\r\n", "\n")).strip()


def word_count(md):
    return len(re.findall(r"[A-Za-z0-9\u00C0-\uFFFF]{2,}", re.sub(r"\]\([^)]*\)", "]", md or "")))


def is_empty(md, min_words=5):
    """A 200 whose body converts to fewer than min_words words counts as empty."""
    return word_count(md) < min_words


def slug(url, n=None):
    s = re.sub(r"^https?://(www\.)?", "", url).strip("/")
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()[:60] or "page"
    return f"{n:02d}-{s}" if n is not None else s


def cost_of(headers):
    """(usd, source). Header only; a missing header is reported as "missing", never guessed."""
    h = {k.lower(): v for k, v in (headers or {}).items()}
    if "x-desearch-cost-usd" in h:
        return float(h["x-desearch-cost-usd"]), "header"
    return 0.0, "missing"


def redact(s, key):
    return s.replace(key, "<redacted>") if key else s


def front_matter(url, title, fetched, status, attempts, words):
    t = title.replace('"', "'")
    return (f'---\nsource: {url}\ntitle: "{t}"\nfetched: {fetched}\nstatus: {status}\n'
            f"attempts: {attempts}\nwords: {words}\n---\n\n")


def summary_table(rows):
    out = ["| # | URL | Status | Attempts | Words | Empty | Latency s | Cost USD |", "|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        out.append(f"| {i} | {r['url']} | {r['status']} | {r['attempts']} | {r['words']} | "
                   f"{'yes' if r['empty'] else 'no'} | {r['latency_s']} | {r['cost_usd']:.4f} |")
    return "\n".join(out)


def valid_url(u):
    """Cheap local check before spending a call: http(s) scheme and a host."""
    return bool(re.match(r"^https?://[^\s/]+\.[^\s/]+", (u or "").strip()))
