import datetime
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import content_ideas as ci  # noqa: E402

AI = {
    "search": [
        {"title": "Welcome to Reddit", "link": "https://www.reddit.com/r/selfpublish/comments/188ttau/how_to_start_a_newsletter/",
         "snippet": "Log in or sign up to personalize your feed, join conversations, vote, and explore communities."},
        {"title": "Ask HN: Cheap way to run a small newsletter? | Hacker News", "link": "https://news.ycombinator.com/item?id=41631227",
         "snippet": "What cheaper alternatives are out there for less than 2,000 subscribers?"},
        {"title": "r/selfpublish on Reddit: Newsletter questions", "link": "https://www.reddit.com/r/selfpublish/comments/16lrvn6/newsletter_questions/",
         "snippet": "r/selfpublish on Reddit: Newsletter questions"},
    ],
    "completion": "People ask how to start.",
    "cost_usd": 0.004,
}
X = [
    {"id": "1", "text": "Starting a newsletter. How do I go from 0 subs to any number? Help, " + "@" + "someone", "created_at": "Mon Feb 10 19:27:01 +0000 2025"},
    {"id": "2", "text": "Why do cats sleep so much? Unrelated question here.", "created_at": "Tue Jan 20 20:50:46 +0000 2026"},
]


def test_build_ai_args_reddit_and_no_domain_filters():
    a = ci.build_ai_args("  starting   a newsletter ", "reddit")
    assert a == {"prompt": "questions beginners ask about starting a newsletter", "tools": ["reddit"],
                 "result_type": "LINKS_WITH_FINAL_SUMMARY"}
    assert "exclude_domains" not in a and "include_domains" not in a


def test_build_ai_args_rejects_bad_input():
    with pytest.raises(ValueError):
        ci.build_ai_args("   ", "reddit")
    with pytest.raises(ValueError):
        ci.build_ai_args("x", "web")


def test_build_x_args_keeps_or_terms_in_parentheses():
    a = ci.build_x_args("starting a newsletter OR substack")
    assert a["query"].startswith("(starting a newsletter OR substack) (")
    assert '("how do i" OR "how do you" OR "any tips")' in a["query"]
    assert a["count"] == 20 and "start_date" not in a


def test_build_x_args_count_bounds():
    assert ci.build_x_args("newsletter", count=500)["count"] == 100
    assert ci.build_x_args("newsletter", count=0)["count"] == 1


def test_parse_content_json_and_text():
    assert ci.parse_content([{"type": "text", "text": json.dumps(AI)}])["cost_usd"] == 0.004
    assert ci.parse_content([{"type": "text", "text": "oops"}]) == {"text": "oops"}


def test_clean_title_uses_link_slug_for_login_page():
    assert ci.clean_title("Welcome to Reddit", AI["search"][0]["link"]) == "How to start a newsletter"
    assert ci.clean_title("Ask HN: Cheap way? | Hacker News") == "Cheap way?"


def test_ai_items_and_x_items_hide_handles_in_links():
    items = ci.ai_items(AI, "reddit")
    assert len(items) == 3 and items[0]["title"] == "How to start a newsletter"
    xs = ci.x_items(X)
    assert xs[0]["link"] == "https://x.com/i/status/1"


def test_find_questions_on_topic_one_per_item_and_mixes_sources():
    items = ci.ai_items(AI, "reddit") + ci.x_items(X)
    qs = ci.find_questions(items, 10, "starting a newsletter")
    texts = [q["question"] for q in qs]
    assert "How to start a newsletter?" in texts
    assert any(q["source"] == "x" for q in qs)
    assert not any("cats" in t for t in texts)
    assert all("@" not in t for t in texts)


def test_suggest_format():
    assert ci.suggest_format("What are the best tools for a newsletter?") == "carousel"
    assert ci.suggest_format("How do I write an intro?") == "short video"
    assert ci.suggest_format("Do newsletters work?") == "thread"


def test_plan_table_has_header_and_rows():
    t = ci.plan_table([{"question": "How do I start?", "link": "https://x.com/i/status/1", "date": ""}])
    assert t.splitlines()[0].startswith("| # | Question")
    assert "not shown" in t


def test_main_needs_key_file(tmp_path):
    with pytest.raises(SystemExit):
        ci.main(["newsletter", "--key-file", str(tmp_path / "missing")])


def test_main_ignores_env_key(monkeypatch, tmp_path):
    monkeypatch.setenv("DESEARCH_API_KEY", "env-key-should-not-be-used")
    with pytest.raises(SystemExit):
        ci.main(["newsletter", "--key-file", str(tmp_path / "missing")])


def test_main_from_raw_runs_offline(tmp_path, capsys):
    raw = tmp_path / "raw.json"
    raw.write_text(json.dumps([
        {"tool": "ai-search", "args": ci.build_ai_args("starting a newsletter", "reddit"), "response": AI},
        {"tool": "x-search", "args": ci.build_x_args("starting a newsletter"), "response": X},
    ]))
    ci.main(["starting a newsletter", "--from-raw", str(raw)])
    out = capsys.readouterr().out
    assert "How to start a newsletter?" in out and "$0.0040" in out


def test_short_date():
    assert ci.short_date("Mon Feb 10 19:27:01 +0000 2025") == "2025-02-10"
    assert ci.short_date("") == ""
