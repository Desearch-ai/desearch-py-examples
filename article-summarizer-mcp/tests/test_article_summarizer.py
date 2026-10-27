import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import article_summarizer as asum  # noqa: E402

URL = "https://www.example-news.com/technology/2026/oct/18/small-ai-models-for-phones"
ARTICLE = (
    "The bank is urging countries to build small AI models that run on a phone.\n\n"
    "Officials said small AI models could help farmers check soil data in their own language.\n\n"
    "The report said 40% of jobs could change, and that $120bn (£90bn) was raised last year.\n\n"
    "Phone networks are still weak in many rural areas, the report said.\n\n"
    "Small AI models need less data and less power than large models.\n\n"
    "The meetings were held in 2026 in Bangkok with ministers from many countries.\n\n"
    "A reader wrote to " + "@" + "someone" + " about small AI models and phones.\n\n"
) + ("Filler sentence about the meetings and the many speakers who came along. " * 25)


def mcp_text(s):
    """What the hosted MCP extract tool returns: the text as a JSON string."""
    return [{"type": "text", "text": json.dumps(s)}]


def test_extract_args_plain_text_no_js_no_domain_filters():
    a = asum.build_extract_args("  " + URL + " ")
    assert a == {"url": URL, "format": "text", "js": False}
    assert "exclude_domains" not in a


@pytest.mark.parametrize("bad", ["", "   ", "not a url", "ftp://example.com/x", "https://localhost"])
def test_check_url_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        asum.check_url(bad)


def test_parse_extract_json_string():
    assert asum.parse_extract(mcp_text("Hello\n\nWorld"))["text"] == "Hello\n\nWorld"


def test_parse_extract_error_reads_cost():
    err = 'Extract error: HTTP 404: {"detail":"No content found.","cost_usd":0.0,"usage_count":0}'
    r = asum.parse_extract([{"type": "text", "text": err}])
    assert "No content found" in r["error"] and r["cost_usd"] == 0.0 and "text" not in r


def test_near_empty_login_page():
    login = "See what\u2019s happening and join the conversation\n\nContinue with phone\n\nor Log in with username or email"
    assert asum.is_near_empty(login)
    out = asum.render(URL, login)
    assert "nearly empty" in out and "Key points" not in out


def test_key_sentences_are_quoted_unedited_and_in_order():
    pts = asum.key_sentences(ARTICLE, 5)
    assert len(pts) == 5
    assert pts[0] == "The bank is urging countries to build small AI models that run on a phone."
    for p in pts:
        assert p in ARTICLE
    idx = [ARTICLE.index(p) for p in pts]
    assert idx == sorted(idx)


def test_numbers_mentioned_skips_bare_years():
    rows = asum.numbers_mentioned(ARTICLE)
    figs = [f for r in rows for f in r["figures"]]
    assert "40%" in figs and "$120bn" in figs and "£90bn" in figs
    assert "2026" not in figs
    assert all(r["sentence"] in ARTICLE for r in rows)


def test_title_from_url_slug():
    assert asum.title_from_url(URL) == "small ai models for phones"
    assert asum.title_from_url("https://paulgraham.com/greatwork.html") == "greatwork"


def test_related_args_web_only_links():
    a = asum.build_related_args("small ai models")
    assert a == {"prompt": "news and articles about: small ai models", "tools": ["web"], "result_type": "ONLY_LINKS"}
    with pytest.raises(ValueError):
        asum.build_related_args("  ")


def test_related_links_skip_own_site_and_dupes():
    data = {"search": [{"title": "Own", "link": "https://example-news.com/a"},
                       {"title": "Other", "link": "https://other.org/b"},
                       {"title": "Other", "link": "https://other.org/b"},
                       {"title": "Third", "link": "https://third.net/c"}], "cost_usd": 0.004}
    assert [r["link"] for r in asum.related_links(data, URL)] == ["https://other.org/b", "https://third.net/c"]


def test_render_hides_handles_and_shows_sections():
    out = asum.render(URL, ARTICLE, 5, related=[{"title": "Other", "link": "https://other.org/b"}])
    assert "@someone" not in out
    assert "Key points" in out and "Numbers mentioned:" in out and "https://other.org/b" in out


def test_render_error():
    out = asum.render(URL, "", error="Extract error: HTTP 404")
    assert "could not read" in out and "Key points" not in out


def test_fetch_retries_once_on_no_content(monkeypatch):
    replies = [[{"type": "text", "text": 'Extract error: HTTP 404: {"detail":"No content found.","cost_usd":0.0}'}],
               mcp_text(ARTICLE)]
    seen = []

    async def fake(calls, key):
        seen.append(calls[0][0])
        return [replies.pop(0)]
    monkeypatch.setattr(asum, "call_tools", fake)
    calls, results = asum.fetch(URL, "k")
    assert seen == ["extract", "extract"]
    out, cost = asum.summarize(URL, calls, results)
    assert "Key points" in out and cost == 0.0


def test_fetch_related_adds_ai_search_and_cost(monkeypatch):
    replies = [mcp_text(ARTICLE),
               [{"type": "text", "text": json.dumps({"search": [{"title": "T", "link": "https://other.org/b"}], "cost_usd": 0.004})}]]

    async def fake(calls, key):
        return [replies.pop(0)]
    monkeypatch.setattr(asum, "call_tools", fake)
    calls, results = asum.fetch(URL, "k", related=True)
    assert [c[0] for c in calls] == ["extract", "ai-search"]
    out, cost = asum.summarize(URL, calls, results)
    assert cost == 0.004 and "https://other.org/b" in out


def test_main_from_raw_offline(tmp_path, capsys):
    raw = tmp_path / "raw.json"
    raw.write_text(json.dumps([{"tool": "extract", "args": asum.build_extract_args(URL), "content": mcp_text(ARTICLE)}]))
    asum.main([URL, "--from-raw", str(raw)])
    out = capsys.readouterr().out
    assert "(from saved run)" in out and "Key points" in out


def test_main_without_key_file_exits(tmp_path):
    with pytest.raises(SystemExit) as e:
        asum.main([URL, "--key-file", str(tmp_path / "missing")])
    assert "console.desearch.ai" in str(e.value)


def test_key_fingerprint_is_short_and_not_the_key():
    fp = asum.key_fingerprint("abc123secret")
    assert len(fp) == 4 and fp not in "abc123secret"


@pytest.mark.parametrize("marker", ["[1]", "[12]", "[4][5][6]", "[a]", "[note 3]", "[citation needed]"])
def test_footnote_markers_are_not_figures(marker):
    text = "The software collects public information from websites." + marker
    assert asum.sentences(text) == [text]
    assert asum.numbers_mentioned(text) == []
    real = "The software collected 40% of the public records." + marker
    assert asum.numbers_mentioned(real) == [{"figures": ["40%"], "sentence": real}]


@pytest.mark.parametrize("marker", ["[1]", "[4][5][6]", "[a]", "[note 3]", "[citation needed]"])
def test_sentence_split_after_attached_footnotes(marker):
    first = "The software collects public information from websites." + marker
    second = "Web scraping software can gather records automatically."
    assert asum.sentences(first + " " + second) == [first, second]


@pytest.mark.parametrize("hatnote", [
    "For broader coverage of this topic, see Data scraping.",
    '"Web scraper" redirects here. For websites that scrape content, see Scraper site.',
    "For other uses, see the topic index.",
    "For the related topic, see the index.",
    "For a related topic, see the index.",
    "For more information, see the topic index.",
    "This article is about the subject with 12 names. For other uses, see the topic index.",
    "Not to be confused with the other subject.",
    "Main article: The history of this subject.",
    "Main articles: The history of this subject.",
    "See also: The history of this subject.",
    "Further information: The history of this subject.",
])
def test_hatnote_lines_are_skipped(hatnote):
    opening = "The software collects public information from websites."
    text = "  " + hatnote + "  \n" + opening + "\n" + hatnote
    assert asum.sentences(text) == [opening]
    assert asum.key_sentences(text, 1) == [opening]
    assert asum.numbers_mentioned(text) == []


@pytest.mark.parametrize("line,figures", [
    ("For more than a decade, the city has spent $40 million a year on road repairs, according to the transport department.", ["$40 million"]),
    ("For the first time since 2015, inflation fell below 2% in March, the statistics office said.", ["2%"]),
    ("For a family of four, the new tariff adds about $30 to the monthly bill.", ["$30"]),
])
def test_news_for_prefix_is_kept(line, figures):
    opening = "The software collects public information from websites."
    text = opening + "\n" + line
    assert asum.sentences(text) == [opening, line]
    assert asum.numbers_mentioned(text) == [{"figures": figures, "sentence": line}]


@pytest.mark.parametrize("line", [
    "For more than a decade, the city has spent $40 million a year on road repairs, according to the transport department.",
    "For the first time since 2015, inflation fell below 2% in March, the statistics office said.",
    "For a family of four, the new tariff adds about $30 to the monthly bill.",
])
def test_news_for_prefix_alone_is_kept(line):
    assert asum.sentences(line) == [line]


def test_this_article_is_about_without_navigation_is_kept():
    line = "This article is about the history of the city's road budget and its effects."
    assert asum.sentences(line) == [line]


def test_long_paragraph_and_case_sensitive_hatnote_check():
    opening = "For the first time, revenue rose 12%."
    paragraph = opening + " " + "The company reported steady growth across its stores during the year. " * 4
    assert len(paragraph.split()) > 40
    assert asum.key_sentences(paragraph, 1) == [opening]
    assert asum.numbers_mentioned(paragraph) == [{"figures": ["12%"], "sentence": opening}]
    ordinary = "For broader coverage, see also " + "read " * 34 + "on."
    assert len(ordinary.split()) == 40
    assert asum.sentences(ordinary) == []
    ordinary = "For broader coverage, see also " + "read " * 35 + "on."
    assert asum.sentences(ordinary) == [ordinary]
    lower = "for other uses, consult the topic index."
    assert asum.sentences(lower) == [lower]
    embedded = "Readers can look elsewhere. For other uses, consult the topic index."
    assert len(asum.sentences(embedded)) == 1


def test_bare_year_with_footnote_still_skipped():
    text = "The software was released to the public in 2026.[12]"
    assert asum.numbers_mentioned(text) == []
