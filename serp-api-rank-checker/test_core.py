import json, pathlib, pytest
import core, rank_check


def it(url, title="t"):
    return {"link": url, "title": title}


def test_normalize():
    assert core.normalize_url("http://WWW.Ex.com/a/?utm_source=x#f") == "https://ex.com/a"
    assert core.normalize_url("https://ex.com") == "https://ex.com/"


def test_domain_match():
    assert core.matches_domain("https://docs.ex.com/x", "ex.com")
    assert core.matches_domain("https://www.ex.com", "www.ex.com")
    assert not core.matches_domain("https://notex.com", "ex.com")


def test_items_of():
    assert core.items_of({"data": [it("https://a.com"), 3]}) == [it("https://a.com")]
    assert core.items_of([1]) == [] and core.items_of({"detail": "x"}) == []


def test_merge_dedupes_and_ranks():
    rows, stats = core.merge_pages([(0, [it("https://a.com"), it("https://b.com")]),
                                    (10, [it("https://www.a.com/"), it("https://c.com")])])
    assert [r["rank"] for r in rows] == [1, 2, 3] and rows[2]["page_start"] == 10
    assert stats[1] == {"start": 10, "returned": 2, "new": 1, "dupes": 1}


def test_best_rank_and_summary():
    rows, _ = core.merge_pages([(0, [it("https://a.com"), it("https://blog.me.dev/p")])])
    s = core.keyword_summary("k", "me.dev", rows)
    assert s["best_rank"] == 2 and s["label"] == "2"
    assert core.keyword_summary("k", "zz.dev", rows)["label"] == "not in top 2"


def test_csv():
    rows, _ = core.merge_pages([(0, [it("https://a.com", 'x, "y"')])])
    out = core.to_csv([{"keyword": "k", "rows": rows}])
    assert out.splitlines()[1] == 'k,1,"x, ""y""",https://a.com,a.com,0'


def test_diff():
    d = {x["keyword"]: x["change"] for x in core.diff_runs({"a": 3, "b": None, "c": 2, "d": 1}, {"a": 1, "b": 4, "c": None, "d": 1})}
    assert d == {"a": "up 2", "b": "entered", "c": "dropped out", "d": "same"}


def test_overlap_and_keywords():
    a, _ = core.merge_pages([(0, [it("https://a.com"), it("https://b.com")])])
    b, _ = core.merge_pages([(0, [it("https://b.com"), it("https://c.com")])])
    assert core.url_overlap(a, b) == (1, 2)
    assert core.parse_keywords("x\n# c\n\nX\ny ") == ["x", "y"]


def test_client_refuses_key(tmp_path):
    c = rank_check.Client("SECRETKEY123", tmp_path)
    with pytest.raises(RuntimeError):
        c._save(tmp_path / "x.json", {"a": "SECRETKEY123"})
