import hashlib
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pricing_snapshot as ps  # noqa: E402

PAGE = open(os.path.join(os.path.dirname(__file__), "fixture_page.txt")).read()


def test_build_args_js_false_only():
    assert ps.build_args("https://linear.app/pricing") == {"url": "https://linear.app/pricing", "format": "text", "js": False}


def test_build_args_never_sends_exclude_domains():
    assert "exclude_domains" not in ps.build_args("https://a.com")


def test_build_args_rejects_non_url():
    with pytest.raises(ValueError):
        ps.build_args("linear.app")


def test_parse_plans_from_saved_page():
    plans = ps.parse_plans(PAGE)
    assert [(p["plan"], p["price"]) for p in plans] == [
        ("Free", "$0"), ("Basic", "$10 per user/month"), ("Business", "$16 per user/month"), ("Enterprise", "Custom")]
    assert plans[1]["billing"] == "Billed yearly"


def test_price_without_name_is_marked():
    plans = ps.parse_plans("All features included.\n$8 per seat\nPro\n$12")
    assert plans[0]["plan"] == ps.NO_NAME and plans[1]["plan"] == "Pro"


def test_page_text_handles_errors_and_json_strings():
    assert ps.page_text([{"type": "text", "text": "Extract error: HTTP 404"}]) == ""
    assert ps.page_text([{"type": "text", "text": json.dumps("Free\n$0")}]) == "Free\n$0"
    assert ps.page_text([{"type": "text", "text": "plain"}]) == "plain"


def test_compare():
    old = {"u": [{"plan": "Basic", "price": "$8"}, {"plan": "Old", "price": "$1"}], "v": [{"plan": "A", "price": "$1"}]}
    new = {"u": [{"plan": "Basic", "price": "$10"}, {"plan": "New", "price": "$2"}], "v": []}
    ch = ps.compare(old, new)
    assert "u | Basic | price | $8 | $10" in ch and "u | New | added | - | $2" in ch
    assert "u | Old | removed | $1 | -" in ch and any("v | could not check" in c for c in ch)
    assert ps.compare(old, old) == []


def test_format_table_marks_empty_pages():
    t = ps.format_table({"https://a.com": []}, "2026-10-05")
    assert "No prices in page text" in t


def test_read_key_from_file_not_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DESEARCH_API_KEY", "env-key-must-not-be-used")
    f = tmp_path / "k"
    f.write_text("file-key\n")
    assert ps.read_key(str(f)) == "file-key"
    assert ps.key_fingerprint("file-key") == hashlib.sha256(b"file-key").hexdigest()[-4:]


def test_main_exits_without_key_file(tmp_path):
    with pytest.raises(SystemExit):
        ps.main(["https://a.com", "--key-file", str(tmp_path / "missing")])


@pytest.mark.skipif(not os.path.exists("/home/box/.keti/desearch-api-key"), reason="builder box only")
def test_builder_key_fingerprint():
    assert ps.key_fingerprint(ps.read_key("/home/box/.keti/desearch-api-key")) == "560b"
