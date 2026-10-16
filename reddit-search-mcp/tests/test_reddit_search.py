import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import reddit_search as rs  # noqa: E402

SAMPLE = {
    "search": [
        {"title": "r/houseplants on Reddit: Winter tips!", "link": "https://www.reddit.com/r/houseplants/comments/r0daw7/winter_tips/"},
        {"title": "Welcome to Reddit", "link": "https://www.reddit.com/r/houseplants/comments/x/y/"},
        {"title": "Not reddit", "link": "https://example.com/post"},
    ],
    "completion": "People suggest grow lights.",
    "cost_usd": 0.004,
}


def test_build_args_uses_reddit_only():
    a = rs.build_args("  houseplants in winter ")
    assert a == {"prompt": "houseplants in winter", "tools": ["reddit"], "result_type": "LINKS_WITH_FINAL_SUMMARY"}


def test_build_args_sends_only_expected_fields():
    a = rs.build_args("x", "ONLY_LINKS")
    assert a == {"prompt": "x", "tools": ["reddit"], "result_type": "ONLY_LINKS"}


def test_build_args_rejects_empty():
    with pytest.raises(ValueError):
        rs.build_args("   ")


def test_parse_result_reads_json_text():
    assert rs.parse_result([{"type": "text", "text": json.dumps(SAMPLE)}])["cost_usd"] == 0.004


def test_parse_result_keeps_plain_text():
    assert rs.parse_result([{"type": "text", "text": "oops"}]) == {"text": "oops"}


def test_reddit_links_filters_and_relabels_login_titles():
    links = rs.reddit_links(SAMPLE)
    assert len(links) == 2
    assert links[1]["title"] == "(title hidden by Reddit login page)"


def test_main_needs_key(monkeypatch):
    monkeypatch.delenv("DESEARCH_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        rs.main(["houseplants"])
