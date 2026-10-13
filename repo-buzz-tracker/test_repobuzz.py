import json, pathlib
import pytest
import core, repobuzz

P = {"id": "1", "text": "HeyGen's Hyperframes on GitHub", "created_at": "Mon Oct 12 20:24:30 +0000 2026",
     "like_count": 5, "retweet_count": 1, "reply_count": 2, "user": {"username": "someone"}, "entities": {"urls": []}}


def test_parse_repo():
    assert core.parse_repo("https://github.com/heygen-com/hyperframes/") == ("heygen-com", "hyperframes")
    assert core.parse_repo("a/b.git") == ("a", "b")
    with pytest.raises(ValueError):
        core.parse_repo("nope")


def test_queries_parenthesised():
    assert core.url_query("o", "r") == '("github.com/o/r" OR "o/r")'
    assert core.name_query("text-to-cad") == '("text-to-cad" OR "text to cad")'
    assert core.name_query("hyperframes") == '("hyperframes")'


def test_classify():
    o, r = "heygen-com", "hyperframes"
    assert core.classify({**P, "entities": {"urls": [{"expanded_url": "https://github.com/heygen-com/hyperframes"}]}}, o, r) == "url"
    assert core.classify({**P, "text": "try heygen-com/hyperframes"}, o, r) == "owner/repo"
    assert core.classify(P, o, r) == "name+context"
    assert core.classify({**P, "text": "Widget + HyperFrames is good"}, o, r) == "name-only"
    assert core.classify({**P, "text": "https://t.co/x", "entities": {"urls": [{"expanded_url": "https://x.com/i/article/9"}]}}, o, r) == "x-article"
    assert core.classify({**P, "text": "unrelated"}, o, r) == "no-match"


def test_in_window_drops_edge_post():
    assert not core.in_window({**P, "created_at": "Mon Sep 28 23:19:01 +0000 2026"}, "2026-09-29")
    assert core.in_window({**P, "created_at": "Tue Sep 29 00:00:01 +0000 2026"}, "2026-09-29")


def test_author_label_hides_individuals():
    assert core.author_label(P, "heygen-com", "hyperframes") == "a developer"
    assert core.author_label({**P, "user": {"username": "HyperFrames_"}}, "heygen-com", "hyperframes") == "HyperFrames_"


def test_cost_header_wins_else_labelled():
    assert core.cost_of({"X-Desearch-Cost-Usd": "0.0075"}, 50) == (0.0075, "header")
    assert core.cost_of({}, 3) == (0.0015, "calculated")


def test_web_match_boundary():
    o, r = "heygen-com", "hyperframes"
    assert core.web_match({"link": "https://github.com/heygen-com/hyperframes/releases"}, o, r) == "repo-page"
    assert core.web_match({"link": "https://github.com/heygen-com/hyperframes-launches"}, o, r) != "repo-page"
    assert core.web_match({"link": "https://x.io", "title": "Sample studio video"}, o, r) == "no-match"


def test_public_outputs_have_no_handles_in_links():
    rs = core.rows([{**P, "_match": "name+context", "_found_by": {"name-latest"}}], [], "heygen-com")
    assert rs[0]["url"] == "https://x.com/i/status/1"
    md = core.buzz_md("heygen-com", "hyperframes", "2026-09-29", [{**P, "_match": "x"}], [{**P, "text": "@bob hi"}], {}, [], "now")
    assert "someone" not in md and "@bob" not in md and "\u2014" not in md


def test_client_refuses_to_write_key(tmp_path):
    c = repobuzz.Client("SECRETKEY123", tmp_path)
    with pytest.raises(RuntimeError):
        c._save(tmp_path / "x.json", {"a": "SECRETKEY123"})


def test_render_offline(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "snapshot.json").write_text(json.dumps({"repo": "heygen-com/hyperframes", "start_date": "2026-09-29", "generated": "t"}))
    (tmp_path / "raw/001-x-url-latest.json").write_text(json.dumps({"tag": "x-url-latest", "response": [P]}))
    repobuzz.render(tmp_path)
    assert "https://x.com/i/status/1" in (tmp_path / "mentions.csv").read_text()
    assert "Repo buzz" in (tmp_path / "buzz.md").read_text()


def test_mask_vendor_names_and_dashes(monkeypatch):
    assert core.VENDOR_NAMES == ["[tool]"]
    assert core.mask("SomeTool 5.5 + HyperFrames \u2014 nice") == "SomeTool 5.5 + HyperFrames ,  nice"
    monkeypatch.setattr(core, "VENDOR_NAMES", ["SomeTool"])
    assert core.mask("SomeTool 5.5 + HyperFrames \u2014 nice") == "[tool] + HyperFrames ,  nice"
