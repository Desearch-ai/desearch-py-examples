import hashlib
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import wikipedia_primer as wp  # noqa: E402

FIX = json.load(open(os.path.join(os.path.dirname(__file__), "fixture.json"), encoding="utf-8"))


def test_build_args_uses_wikipedia_short_id():
    assert wp.build_args(" carbon credits ") == {
        "prompt": "carbon credits: what it is, how it works, key facts, criticism, and related topics",
        "tools": ["wikipedia"], "result_type": "LINKS_WITH_FINAL_SUMMARY"}


def test_args_never_send_exclude_domains():
    assert "exclude_domains" not in wp.build_args("x") and "exclude_domains" not in wp.web_args("x")


def test_build_args_rejects_empty():
    with pytest.raises(ValueError):
        wp.build_args("  ")


def test_clean_pages_drops_talk_and_marks_language():
    pages = wp.clean_pages(FIX["wiki"]["search"])
    titles = [p["title"] for p in pages]
    assert not any(t.startswith("Talk:") for t in titles)
    assert pages[-1]["note"] == "fr Wikipedia"


def test_link_citations_drops_numbers():
    t = wp.link_citations(FIX["wiki"]["completion"])
    assert "[1]" not in t and "[15]" not in t and "(https://en.wikipedia.org/wiki/Carbon_offsets_and_credits)" in t


def test_check_numbers_drops_unsupported_number():
    results = [{"link": "https://a", "snippet": "The market was 100 in 2020."}, {"link": "https://b", "snippet": "no numbers"}]
    text, notes = wp.check_numbers("It was 100 in 2020 [1](https://b). It is big [2](https://b).", results)
    assert "(https://a)" in text and "It is big (https://b)." in text and "Re-linked" in notes[0]
    text, notes = wp.check_numbers("It was 999 [1](https://b).", results)
    assert "999" not in text and "Left out" in notes[0]


def test_pick_web_skips_social():
    picks = wp.pick_web([{"title": "r", "link": "https://www.reddit.com/r/x"}, {"title": "a", "link": "https://a.org/x"}])
    assert picks == [{"title": "a", "link": "https://a.org/x"}]


def test_format_primer_sections():
    out = wp.format_primer("Carbon credits", FIX["wiki"], FIX["web"])
    assert out.startswith("## Carbon credits: a primer") and "### Wikipedia pages" in out and "### Web cross-check" in out
    assert "\u2014" not in out


def test_parse_json():
    assert wp.parse_json([{"type": "text", "text": json.dumps({"a": 1})}]) == {"a": 1}
    assert wp.parse_json([{"type": "text", "text": "oops"}]) is None


def test_read_key_from_file_not_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DESEARCH_API_KEY", "env-key-must-not-be-used")
    f = tmp_path / "k"
    f.write_text("file-key\n")
    assert wp.read_key(str(f)) == "file-key"
    assert wp.key_fingerprint("file-key") == hashlib.sha256(b"file-key").hexdigest()[-4:]


def test_main_exits_without_key_file(tmp_path):
    with pytest.raises(SystemExit):
        wp.main(["x", "--key-file", str(tmp_path / "missing")])


@pytest.mark.skipif(not os.path.exists("/home/box/.keti/desearch-api-key"), reason="builder box only")
def test_builder_key_fingerprint():
    assert wp.key_fingerprint(wp.read_key("/home/box/.keti/desearch-api-key")) == "560b"
