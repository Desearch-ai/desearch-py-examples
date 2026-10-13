"""Offline tests: no network, no key."""
import json, os, types
import pytest
import ragcorpus as rc


def test_normalise_url_variants_collapse():
    a = rc.normalise_url("http://www.Example.com/guide/?utm_source=x&b=2&a=1#top")
    b = rc.normalise_url("https://example.com/guide?a=1&b=2")
    assert a == b == "https://example.com/guide?a=1&b=2"
    assert rc.normalise_url("https://example.com/") == "https://example.com/"
    assert rc.normalise_url("https://example.com/docs/index.html") == "https://example.com/docs"
    assert rc.normalise_url("https://m.example.com/a") == "https://example.com/a"
    assert rc.normalise_url("mailto:x@y.z") == ""
    assert rc.normalise_url("") == ""


def test_dedupe_within_and_across():
    l1 = [{"link": "https://a.com/x"}, {"link": "https://www.a.com/x/"}, {"link": "https://b.com/y"}]
    l2 = [{"link": "https://b.com/y?utm_medium=z"}, {"link": "https://c.com/z"}]
    uniq, st = rc.dedupe([(0, l1), (1, l2)])
    assert st == {"links_total": 5, "dup_within": 1, "dup_across": 1, "unique": 3, "dup_rate": 0.4}
    b = [u for u in uniq if u["domain"] == "b.com"][0]
    assert b["sq"] == 0 and b["rank"] == 3 and b["hits"] == [(0, 3), (1, 1)]


def test_select_round_robin_domain_cap_and_max():
    uniq = [{"url": f"https://d{i%2}.com/{i}", "norm": f"https://d{i%2}.com/{i}", "domain": f"d{i%2}.com",
             "title": "", "sq": i % 3, "rank": i, "hits": [(i % 3, i)]} for i in range(12)]
    sel, skip = rc.select_pages(uniq, max_pages=4, max_per_domain=2)
    assert len(sel) == 4
    assert max(sum(1 for s in sel if s["domain"] == d) for d in ("d0.com", "d1.com")) <= 2
    assert {s["sq"] for s in sel} == {0, 1, 2}
    assert {s["skip"] for s in skip} <= {"domain_cap", "max_pages"} and len(sel) + len(skip) == 12


HTML = """<html><head><title>Battery Guide</title></head><body>
<nav><a>Home</a><a>Shop</a></nav><div class="cookie-banner">We use cookies</div>
<article><h1>Home batteries</h1><p>Intro paragraph about home batteries that is long enough to keep.</p>
<h2>Sizing</h2><p>Size the battery to your evening load in kWh, then add margin for losses.</p>
<ul><li>Daily use in kWh</li><li>Backup hours wanted</li></ul>
<h3>Example</h3><p>A home using 10 kWh after sunset needs about 12 kWh of usable storage.</p>
<h2>Lifespan</h2><p>Most warranties cover ten years or a cycle count, whichever comes first.</p></article>
<footer>Copyright</footer></body></html>"""


def test_html_to_blocks_heading_paths_and_boilerplate():
    title, blocks = rc.html_to_blocks(HTML)
    assert title == "Battery Guide"
    texts = " ".join(b["text"] for b in blocks)
    assert "cookies" not in texts and "Copyright" not in texts and "Shop" not in texts
    paths = [b["heading_path"] for b in blocks]
    assert ["Home batteries", "Sizing", "Example"] in paths
    assert ["Home batteries", "Lifespan"] in paths
    assert any(b["kind"] == "li" for b in blocks)


def test_chunks_never_span_headings_and_respect_size():
    _, blocks = rc.html_to_blocks(HTML)
    chunks = rc.chunk_blocks(blocks, max_chars=1200, min_chars=10)
    for c in chunks:
        assert len(c["text"]) <= 1200
    assert len({tuple(c["heading_path"]) for c in chunks}) == len(chunks)
    long = [{"heading_path": ["A"], "text": ("Sentence number one is here. " * 200), "kind": "p"}]
    cs = rc.chunk_blocks(long, max_chars=500)
    assert len(cs) > 5 and all(len(c["text"]) <= 500 + 200 for c in cs)


def test_text_to_blocks_guesses_headings():
    t = "Sizing\n" + "A long paragraph about sizing. " * 6 + "\n\nShort\n"
    b = rc.text_to_blocks(t)
    assert b and b[0]["heading_path"] == ["Sizing"]


def test_is_empty_page():
    assert rc.is_empty_page(404, 5000)
    assert rc.is_empty_page(200, 50)
    assert not rc.is_empty_page(200, 500)


class FakeResp:
    def __init__(self, status, body, ctype, cost, units):
        self.status_code, self._b = status, body
        self.headers = {"Content-Type": ctype, "X-Desearch-Cost-Usd": str(cost), "X-Desearch-Usage-Count": str(units),
                        "X-Desearch-Service": "test"}
        self.text = body if isinstance(body, str) else json.dumps(body)

    def json(self):
        return self._b if not isinstance(self._b, str) else json.loads(self._b)


class FakeSession:
    """links -> 3 results; extract -> page 1 OK, page 2 404 twice, page 3 empty then OK."""
    def __init__(self):
        self.n = {}

    def request(self, method, url, params=None, json=None, headers=None, timeout=None):
        assert headers["Authorization"] == "SECRETKEY123"
        if url.endswith(rc.LINKS_PATH):
            res = [{"link": f"https://site{i}.com/p", "title": f"T{i}"} for i in range(3)]
            return FakeResp(200, {"search_results": res}, "application/json", 0.004, 10)
        u = params["url"]
        self.n[u] = self.n.get(u, 0) + 1
        if "site1" in u:
            return FakeResp(404, {"detail": "No content found."}, "application/json", 0, 0)
        if "site2" in u and self.n[u] == 1:
            return FakeResp(200, "<html><body></body></html>", "text/plain", 0.0005, 1)
        return FakeResp(200, HTML.replace("Battery Guide", "Guide " + u), "text/plain", 0.0005, 1)


def make_args(**kw):
    d = dict(count=10, max_pages=150, max_per_domain=3, format="html", retry=True, chunk_chars=1200, workers=2,
             prefix_topic=True, save_pages=True, topic_filter=False)
    d.update(kw)
    return types.SimpleNamespace(**d)


def test_pipeline_offline(tmp_path):
    out = tmp_path / "run"; (out / "raw").mkdir(parents=True)
    client = rc.Client("SECRETKEY123", str(out), max_spend=1.0, session=FakeSession())
    cfg = {"topic": "home batteries", "sub_questions": ["q1", {"q": "q2", "count": 20}]}
    s = rc.run(cfg, make_args(), client, str(out))
    assert [l["requested"] for l in s["links"]] == [10, 20]
    assert s["dedupe"]["unique"] == 3 and s["dedupe"]["dup_across"] == 3
    # site0 and site2 serve the same body text: the second one is dropped as duplicate content
    assert (s["pages_kept"], s["pages_empty"], s["pages_duplicate_content"]) == (1, 1, 1)
    assert s["empty_try1"] == 2 and s["recovered_on_retry"] == 1
    rows = [json.loads(l) for l in open(out / "corpus.jsonl")]
    assert rows and all(r["source_url"] and r["title"] and "heading_path" in r for r in rows)
    srcs = (out / "sources.csv").read_text()
    assert "No content found." in srcs
    # the key never lands on disk
    for p in out.rglob("*"):
        if p.is_file():
            assert "SECRETKEY123" not in p.read_text()
    assert abs(s["cost"]["links_usd"] - 0.008) < 1e-9


def test_budget_guard(tmp_path):
    (tmp_path / "raw").mkdir()
    c = rc.Client("K", str(tmp_path), max_spend=0.0, session=FakeSession())
    with pytest.raises(rc.BudgetExceeded):
        c.request("x", "GET", "/web/extract", params={"url": "https://a.com"})


def test_safe_write_refuses_key(tmp_path):
    c = rc.Client("TOPSECRET", str(tmp_path), max_spend=1, session=FakeSession())
    with pytest.raises(RuntimeError):
        c._safe_write(str(tmp_path / "x.json"), "token TOPSECRET here")


def test_topic_filter_drops_generic_pages():
    st = rc.topic_stems("home solar batteries", "LFP vs NMC chemistry for home batteries")
    assert {"solar", "batte", "lfp", "nmc", "chemi"} <= st and "home" not in st
    assert rc.looks_on_topic({"title": "LFP vs NMC: which is safer", "url": "https://x.com/a"}, st)
    assert rc.looks_on_topic({"title": "Guide", "url": "https://x.com/solar-battery-guide"}, st)
    assert not rc.looks_on_topic({"title": "Renewable energy - Wikipedia", "url": "https://en.wikipedia.org/wiki/Renewable_energy"}, st)
    assert not rc.looks_on_topic({"title": "Homepage | ENERGY STAR", "url": "https://www.energystar.gov/"}, st)


def test_pipeline_topic_filter(tmp_path):
    out = tmp_path / "run"; (out / "raw").mkdir(parents=True)
    client = rc.Client("SECRETKEY123", str(out), max_spend=1.0, session=FakeSession())
    cfg = {"topic": "zebra", "sub_questions": ["stripes"]}          # no fake result mentions zebras
    s = rc.run(cfg, make_args(topic_filter=True), client, str(out))
    assert s["topic_filter_dropped"] == 3 and s["pages_selected"] == 0
    assert "skipped_topic_filter" in (out / "sources.csv").read_text()
