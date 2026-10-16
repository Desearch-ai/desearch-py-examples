import json, pathlib, core, page2md

HTML = """<html><head><title>Demo  Page</title><style>x{}</style><script>var a=1</script></head>
<body><nav><a href="/">Home</a></nav><h1>Hello</h1><p>Some <b>bold</b> text and a <a href="https://desearch.ai">link</a>.</p>
<ul><li>one</li><li>two</li></ul><ol><li>first</li><li>second</li></ol><pre>x = 1\n  y = 2</pre><footer>foot</footer></body></html>"""


def test_html_to_markdown_structure():
    t, md, links = core.html_to_markdown(HTML)
    assert t == "Demo Page"
    assert md.startswith("# Hello")
    assert "**bold**" in md and "[link](https://desearch.ai)" in md
    assert "- one" in md and "1. first" in md and "2. second" in md
    assert "```\nx = 1\n  y = 2\n```" in md
    assert "var a" not in md and "Home" not in md and "foot" not in md
    assert links == ["https://desearch.ai"]


def test_empty_detection():
    assert core.is_empty("")
    assert core.is_empty(core.html_to_markdown('<html><body><div id="root"></div><script>x()</script></body></html>')[1])
    assert not core.is_empty("This page has more than five real words in it.")


def test_slug_and_cost():
    assert core.slug("https://www.example.com/a/b?c=1", 3) == "03-example-com-a-b-c-1"
    assert core.cost_of({"X-Desearch-Cost-Usd": "0.0005"}) == (0.0005, "header")
    assert core.cost_of({}) == (0.0, "missing")


def test_redact():
    assert core.redact("Authorization: abc123", "abc123") == "Authorization: <redacted>"


def test_text_to_markdown():
    assert core.text_to_markdown("a\r\n\r\n\r\n\r\nb") == "a\n\nb"


class Fake:
    """Stands in for Client: returns queued (status, body) pairs, no network."""
    fmt = "html"

    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def extract(self, url, tag):
        st, body = self.replies.pop(0)
        self.calls.append(tag)
        return st, body, {"status": st, "latency_s": 1.0, "cost_usd": 0.0005 if st == 200 else 0.0, "ts": "t"}


def test_retry_once_on_empty_then_success():
    f = Fake([(200, "<html><body></body></html>"), (200, "<p>now there are plenty of words here</p>")])
    r = page2md.page_to_markdown(f, "https://x.test", "x")
    assert r["attempts"] == 2 and not r["empty"] and r["empty_first"]
    assert r["latency_s"] == 2.0 and r["cost_usd"] == 0.001


def test_retry_only_once():
    f = Fake([(200, ""), (200, ""), (200, "never used")])
    r = page2md.page_to_markdown(f, "https://x.test", "x")
    assert r["attempts"] == 2 and r["empty"] and len(f.replies) == 1


def test_no_retry_on_error_status():
    f = Fake([(404, '{"detail":"No content found."}'), (200, "unused")])
    r = page2md.page_to_markdown(f, "https://x.test", "x")
    assert r["attempts"] == 1 and r["status"] == 404 and not r["empty"] and r["error"]


def test_raw_save_redacts_key(tmp_path, monkeypatch):
    class R:
        status = 200
        headers = {"X-Desearch-Cost-Usd": "0.0005"}
        def read(self): return b"<p>echo SECRETKEY in body</p>"
    monkeypatch.setattr(page2md.urllib.request, "urlopen", lambda req, timeout: R())
    c = page2md.Client("SECRETKEY", tmp_path)
    c.extract("https://x", "t")
    saved = "".join(p.read_text() for p in (tmp_path / "raw").glob("*.json"))
    assert "SECRETKEY" not in saved and "<redacted>" in saved
    assert json.loads((tmp_path / "calls.jsonl").read_text())["cost_usd"] == 0.0005


def test_links_resolved_and_heading_in_link_flattened():
    _, md, links = core.html_to_markdown('<a href="/a"><h2>Title</h2> text here</a>', "https://site.test/x/")
    assert md == "[Title text here](https://site.test/a)" and links == ["https://site.test/a"]


def test_blank_or_bad_url_skipped_without_call():
    f = Fake([])
    for u in ["", "   ", "not-a-url"]:
        r = page2md.page_to_markdown(f, u, "x")
        assert r["status"] == "skipped" and r["cost_usd"] == 0.0
    assert f.calls == []
