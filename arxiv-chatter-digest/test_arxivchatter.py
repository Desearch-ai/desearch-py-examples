"""Offline tests: no network, no key."""
import json, pathlib
import pytest
import core, arxivchatter

ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>http://arxiv.org/abs/2609.31466v1</id><title>Scaffold: Support Graph
 Theory Based Sparsification</title><published>2026-09-25T16:17:09Z</published>
<summary>We introduce  Scaffold.</summary><author><name>A One</name></author><author><name>B Two</name></author></entry>
</feed>"""


def test_arxiv_id_forms():
    assert core.arxiv_id("https://arxiv.org/abs/2609.30079v1") == "2609.30079"
    assert core.arxiv_id("https://arxiv.org/html/2503.07959v1") == "2503.07959"
    assert core.arxiv_id("https://ar5iv.labs.arxiv.org/html/1901.00596") == "1901.00596"
    assert core.arxiv_id("https://arxiv.org/pdf/2610.13724") == "2610.13724"
    assert core.arxiv_id("https://arxiv.org/list/cs.LG/current") is None
    assert core.arxiv_id("https://arxiv.org/") is None


def test_collect_dedupes_link_forms():
    res = [("p1", [{"title": "[1901.00596] A Survey", "link": "https://arxiv.org/abs/1901.00596"},
                   {"title": "A Survey", "link": "https://ar5iv.labs.arxiv.org/html/1901.00596"},
                   {"title": "Machine Learning", "link": "https://arxiv.org/list/cs.LG/current"}]),
           ("p2", [{"title": "x", "link": "https://arxiv.org/abs/1901.00596"}])]
    papers, skipped = core.collect_papers(res)
    assert list(papers) == ["1901.00596"]
    assert papers["1901.00596"]["desearch_title"] == "A Survey"
    assert len(papers["1901.00596"]["links_seen"]) == 2 and papers["1901.00596"]["prompts"] == ["p1", "p2"]
    assert skipped == ["https://arxiv.org/list/cs.LG/current"]


def test_parse_atom_and_title_match():
    m = core.parse_arxiv_atom(ATOM)["2609.31466"]
    assert m["title"] == "Scaffold: Support Graph Theory Based Sparsification"
    assert m["published"] == "2026-09-25" and m["authors"] == ["A One", "B Two"]
    assert core.title_similarity("Scaffold: Support Graph Theory Based Sparsification", m["title"]) == 1.0
    assert core.title_similarity("1Introduction", m["title"]) < 0.5


def test_x_query_parenthesised_or():
    q = core.x_query("2609.31466", 'Scaffold: Support Graph Theory Based "Sparsification" for Graph Neural Networks')
    assert q.startswith('("2609.31466" OR "') and q.endswith('")')
    assert q.count('"') == 4
    assert core.short_title("Attention Graphons: A Graph Limit Perspective") == "Attention Graphons: A Graph Limit Perspective"
    assert core.short_title("Scaffold Support Graph Theory: A Long Subtitle Here") == "Scaffold Support Graph Theory"
    assert core.short_title("GNN: A Graph Limit Perspective on Graph Transformers") == "GNN: A Graph Limit Perspective on Graph Transformers"


def test_posts_are_handle_free_and_windowed():
    data = [{"id": "111", "url": "https://x.com/somebody/status/111", "created_at": "Tue Oct 06 06:08:54 +0000 2026",
             "text": "new paper by @someone https://x.com/someone/status/999 see https://x.com/someone", "like_count": 3},
            {"id": "111", "url": "https://x.com/somebody/status/111", "created_at": "Tue Oct 06 06:08:54 +0000 2026", "text": "dup"},
            {"id": "222", "url": "https://x.com/b/status/222", "created_at": "Thu Sep 17 14:01:10 +0000 2026", "text": "old"}]
    posts = core.x_posts(data, "2026-09-25")
    assert [p["id"] for p in posts] == ["111", "222"]
    assert posts[0]["url"] == "https://x.com/i/status/111"
    assert "someone" not in posts[0]["text"] and "x.com/i/status/999" in posts[0]["text"]
    assert posts[0]["in_window"] is True and posts[1]["in_window"] is False


def test_x_cost_rule():
    assert core.x_cost_calculated(0, 20) == 0.0015      # 10-post minimum
    assert core.x_cost_calculated(12, 20) == 0.0018
    assert core.x_cost_calculated(50, 20) == 0.003      # never above count


def test_abstract_from_page():
    t = "View PDF HTML (experimental)\n\nAbstract:We study things.\nNice.  Comments: 9 pages Subjects: cs.LG"
    assert core.abstract_from_page(t) == "We study things. Nice."
    assert core.abstract_from_page("") == ""


def _paper(pid, n, likes=0, pub="2026-10-01"):
    return {"arxiv_id": pid, "title": f"T {pid}", "abs_url": f"https://arxiv.org/abs/{pid}", "published": pub,
            "in_window": True, "title_match": 1.0, "mention_count": n, "out_of_window_posts": 0, "extract_status": "ok_try1",
            "authors": ["A", "B", "C", "D"], "abstract": "abc",
            "posts": [{"url": f"https://x.com/i/status/{i}", "created": pub, "likes": likes, "text": "t"} for i in range(n)]}


def test_rank_csv_digest():
    ps = core.rank([_paper("2610.00001", 0, pub="2026-10-05"), _paper("2610.00002", 2), _paper("2610.00003", 0, pub="2026-10-09")])
    assert [p["arxiv_id"] for p in ps] == ["2610.00002", "2610.00003", "2610.00001"]
    csv = core.papers_csv(ps, "2026-10-12T09:38+04:00")
    assert csv.splitlines()[0].startswith("rank,arxiv_id,title,abs_url,published")
    assert "https://x.com/i/status/0 https://x.com/i/status/1" in csv
    md = core.digest_md("topic", ps, ("2026-09-12", "2026-10-12"), "now")
    assert "Papers Desearch returned and public X posts that named them" in md
    assert "\u2014" not in md and "et al." in md and "## 3." in md


def test_key_guard():
    with pytest.raises(RuntimeError):
        core.assert_no_key("x sk-secret y", "sk-secret")
    assert core.assert_no_key("clean", "sk-secret") == "clean"


def test_api_key_file(tmp_path, monkeypatch):
    f = tmp_path / "k"
    f.write_text("abc\n")
    monkeypatch.setenv("DESEARCH_API_KEY_FILE", str(f))
    monkeypatch.setenv("DESEARCH_API_KEY", "ignored")
    assert arxivchatter.api_key() == "abc"


def test_render_from_snapshot(tmp_path):
    ps = [_paper("2610.00002", 1), _paper("2610.00001", 0)]
    (tmp_path / "snapshot.json").write_text(json.dumps({"topic": "t", "window": ["2026-09-12", "2026-10-12"], "fetched_at": "now",
                                                        "candidates": ps, "chosen": ["2610.00001", "2610.00002"]}))
    arxivchatter.render(str(tmp_path))
    assert (tmp_path / "papers.csv").read_text().splitlines()[1].startswith("1,2610.00002")
