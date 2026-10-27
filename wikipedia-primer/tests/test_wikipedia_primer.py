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


W = "https://en.wikipedia.org/wiki/"


@pytest.mark.parametrize("slug", [
    "Talk:Carbon_credit", "User:Someone", "User_talk:Someone", "File:Map.png", "File_talk:Map.png",
    "Category:Carbon_finance", "Template:Climate", "Help:Contents", "Portal:Climate", "Wikipedia:About",
    "Wikipedia_talk:About", "Draft:Carbon_x", "Special:Search", "Module:Citation", "MediaWiki:Edittools",
    "Book:Climate", "TimedText:Clip.webm", "Category%20talk:Carbon"])
def test_namespace_pages_dropped_by_url(slug):
    r = {"title": "Carbon credit - Wikipedia", "link": W + slug}
    assert wp.drop_reason(r).startswith("not an article")
    assert wp.clean_pages([r]) == []


def test_namespace_pages_dropped_by_title_prefix():
    r = {"title": "Portal talk:Climate change - Wikipedia", "link": W + "Climate_change"}
    assert wp.drop_reason(r).startswith("not an article")


def test_colon_in_article_title_is_kept():
    r = {"title": "Star Wars: Episode IV - Wikipedia", "link": W + "Star_Wars:_Episode_IV"}
    assert wp.drop_reason(r) is None


@pytest.mark.parametrize("link", [
    "https://www.example.com/wiki/Carbon_credit", "https://wikipedia.org.example.com/wiki/Carbon_credit",
    "https://en.wikipedia.org/w/index.php?title=Carbon_credit", "https://en.wikipedia.org/wiki/", ""])
def test_non_wikipedia_article_links_dropped(link):
    assert wp.drop_reason({"title": "Carbon credit", "link": link}) == "not a Wikipedia article link"


def test_title_link_mismatch_dropped():
    r = {"title": "Climate finance - Wikipedia", "link": W + "Carbon_finance"}
    assert wp.drop_reason(r) == "title does not match the page it links to"
    dropped = []
    assert wp.clean_pages([r], dropped) == [] and dropped[0]["reason"].startswith("title does not match")


@pytest.mark.parametrize("title,link", [
    ("Personal carbon credits - Wikipedia", W + "Personal_Carbon_Credits"),
    ("Gold Standard (carbon offset standard) - Wikipedia", W + "Gold_Standard_(carbon_offset_standard)"),
    ("Gold Standard (carbon offset standard)", W + "Gold_Standard_%28carbon_offset_standard%29"),
    ("Carbon emission trading - Wikipedia", W + "Carbon_emission_trading#History"),
    ("Cr\u00e9dit carbone - Wikip\u00e9dia", "https://fr.wikipedia.org/wiki/Cr%C3%A9dit_carbone"),
    ("Carbon credit | Wikipedia", "https://en.m.wikipedia.org/wiki/Carbon_credit"),
])
def test_matching_titles_kept(title, link):
    assert wp.drop_reason({"title": title, "link": link}) is None


def test_format_primer_lists_dropped_pages_in_notes():
    wiki = {"completion": "", "search": [
        {"title": "Carbon offsets and credits - Wikipedia", "link": W + "Carbon_offsets_and_credits"},
        {"title": "Climate finance - Wikipedia", "link": W + "Carbon_finance"},
        {"title": "Talk:Carbon offsets and credits - Wikipedia", "link": W + "Talk:Carbon_offset"}]}
    out = wp.format_primer("Carbon credits", wiki)
    assert "- Carbon offsets and credits: " in out and "- Climate finance:" not in out
    assert "Left out Climate finance: title does not match the page it links to." in out
    assert "Left out Talk:Carbon offsets and credits: not an article" in out


def test_summary_facts_cited_only_to_dropped_pages_are_left_out():
    wiki = {"completion": "Credits are traded [1](https://en.wikipedia.org/wiki/Carbon_offsets_and_credits). "
                          "The market was 402.58 billion [2](https://en.wikipedia.org/wiki/Talk:Carbon_offset). "
                          "Some are criticised [2](https://en.wikipedia.org/wiki/Talk:Carbon_offset)"
                          "[1](https://en.wikipedia.org/wiki/Carbon_offsets_and_credits).",
            "search": [
                {"title": "Carbon offsets and credits - Wikipedia", "link": W + "Carbon_offsets_and_credits", "snippet": ""},
                {"title": "Talk:Carbon offsets and credits - Wikipedia", "link": W + "Talk:Carbon_offset",
                 "snippet": "valued at 402.58 billion"}]}
    out = wp.format_primer("Carbon credits", wiki)
    assert "Talk:Carbon_offset)" not in out.split("### Notes")[0]
    assert "402.58" not in out
    assert "Some are criticised (https://en.wikipedia.org/wiki/Carbon_offsets_and_credits)." in out
    assert "Left out a fact cited only to a page that was left out." in out
