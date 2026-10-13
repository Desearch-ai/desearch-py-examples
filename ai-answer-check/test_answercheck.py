"""Offline tests for answercheck.py (no network, no key)."""
import json
import answercheck as A

BRANDS = {"Asana": {"aliases": []}, "Trello": {"aliases": []},
          "monday.com": {"aliases": ["monday work management"]},
          "ClickUp": {"aliases": []}, "Notion": {"aliases": [], "case_sensitive": True}}
P = A.brand_patterns(BRANDS)

SUMMARY = ("\n\nFor a small remote team, **ClickUp** is the strongest pick because it bundles tasks and docs "
           "[1](https://www.example-reviews.com/pm-tools/). Asana suits teams that want clear timelines "
           "[2](https://blog.example.org/asana-review) and Trello is simpler [3, 4]. "
           "Some people like the notion of one tool, see https://twitter.com/someone/status/1.")


def test_domain_normalises_www_and_twitter():
    assert A.domain("https://www.Example.com/x") == "example.com"
    assert A.domain("https://twitter.com/a/status/1") == "x.com"
    assert A.domain("not a url") == ""


def test_cited_urls_and_unlinked_citations():
    urls = A.cited_urls(SUMMARY)
    assert urls == ["https://www.example-reviews.com/pm-tools/", "https://blog.example.org/asana-review",
                    "https://twitter.com/someone/status/1"]
    assert A.unlinked_citations(SUMMARY) == 1


def test_mentions_order_and_position():
    r = A.analyse_run(SUMMARY, "Asana", P)
    assert r["brands_named"] == ["ClickUp", "Asana", "Trello"]
    assert r["brand_named"] is True and r["brand_position"] == 2
    assert r["others_named"] == ["ClickUp", "Trello"]
    assert r["brand_sentence"].startswith("Asana suits teams")
    assert r["cited_domains"] == ["blog.example.org", "example-reviews.com", "x.com"]


def test_case_sensitive_brand_ignores_common_word():
    r = A.analyse_run(SUMMARY, "Asana", P)
    assert "Notion" not in r["brands_named"]  # "the notion of" is not the product
    r2 = A.analyse_run("Notion works well for docs.", "Asana", P)
    assert r2["brands_named"] == ["Notion"] and r2["brand_named"] is False


def test_url_text_does_not_count_as_mention():
    r = A.analyse_run("Pick ClickUp [1](https://asana.com/compare/clickup).", "Asana", P)
    assert r["brand_named"] is False


def test_alias_and_dotted_name():
    r = A.analyse_run("monday.com and Monday Work Management are the same product.", "Asana", P)
    assert r["brands_named"] == ["monday.com"]


def _run(q, k, named, domains):
    return {"question": q, "run": k, "ok": True, "brands_named": named, "brand_named": "Asana" in named,
            "brand_position": named.index("Asana") + 1 if "Asana" in named else None,
            "cited_domains": domains, "source_domains": domains}


def test_share_table_and_consistency():
    runs = [_run("q1", 1, ["ClickUp", "Asana"], ["a.com"]), _run("q1", 2, ["Asana", "ClickUp"], ["a.com", "b.com"]),
            _run("q1", 3, ["ClickUp"], ["c.com"]), {"question": "q1", "run": 4, "ok": False}]
    rows = {r["brand"]: r for r in A.share_table(runs, ["Asana", "ClickUp", "Trello"])}
    assert rows["ClickUp"]["runs_named"] == 3 and rows["ClickUp"]["runs"] == 3 and rows["ClickUp"]["share"] == 1.0
    assert rows["Asana"]["runs_named"] == 2 and rows["Asana"]["mean_position"] == 1.5 and rows["Asana"]["first_named"] == 1
    assert rows["Trello"]["runs_named"] == 0 and rows["Trello"]["mean_position"] is None
    c = A.consistency(runs)[0]
    assert c["brand_named_runs"] == 2 and c["positions"] == [2, 1, None]
    assert c["same_brand_set_all_runs"] is False and c["distinct_brand_sets"] == 2
    assert c["domain_overlap"] == round((0.5 + 0 + 0) / 3, 2)
    assert A.top_domains(runs)[0] == ("a.com", 2)


def test_build_body_omits_empty_options():
    b = A.build_body("q", "", ["web"])
    assert b == {"prompt": "q", "tools": ["web"], "result_type": "LINKS_WITH_FINAL_SUMMARY", "streaming": False}
    b = A.build_body("q", "sys", ["web", "twitter"], count=20, date_filter="PAST_WEEK")
    assert b["system_message"] == "sys" and b["count"] == 20 and b["date_filter"] == "PAST_WEEK"


class FakeResp:
    def __init__(self, status, body, headers):
        self.status_code, self._body, self.headers = status, body, headers

    def json(self):
        if isinstance(self._body, str):
            raise ValueError
        return self._body

    @property
    def text(self):
        return self._body if isinstance(self._body, str) else json.dumps(self._body)


class FakeSession:
    def __init__(self, responses):
        self.responses, self.sent = list(responses), []

    def post(self, url, json=None, headers=None, timeout=None):
        self.sent.append({"url": url, "json": json, "headers": headers})
        return self.responses.pop(0)


HDR = {"X-Desearch-Cost-Usd": "0.004", "X-Desearch-Usage-Count": "10", "X-Desearch-Service": "AI Search"}


def test_client_retries_once_on_503_and_never_saves_key(tmp_path):
    body = {"completion": SUMMARY, "search": [{"title": "t", "link": "https://www.example-reviews.com/pm-tools/"}],
            "tweets": [{"id": "1", "url": "https://x.com/a/status/1", "text": "hi"}], "cost_usd": 0.004}
    s = FakeSession([FakeResp(503, {"detail": "Search unavailable"}, {}), FakeResp(200, body, HDR)])
    c = A.Client("dsr_test_key_123", session=s, raw_dir=str(tmp_path))
    ok, data, call = c.ai_search(A.build_body("q", "sys", ["web", "twitter"]), tag="t")
    assert ok and call["attempt"] == 2 and call["cost_usd"] == 0.004 and call["usage_count"] == 10
    assert len(c.calls) == 2 and c.calls[0]["ok"] is False and c.calls[0]["cost_usd"] is None
    assert s.sent[0]["headers"]["Authorization"] == "dsr_test_key_123"
    for f in tmp_path.iterdir():
        assert "dsr_test_key_123" not in f.read_text()
    assert A.cost_summary(c.calls) == {"calls": 2, "billed_calls": 1, "total_usd": 0.004, "units": 10, "errors": 1}


def test_run_check_end_to_end_with_ab(tmp_path):
    body = {"completion": SUMMARY, "search": [{"title": "t", "link": "https://www.example-reviews.com/x"}]}
    s = FakeSession([FakeResp(200, body, HDR) for _ in range(6)])
    c = A.Client("k", session=s)
    cfg = {"brand": {"name": "Asana"}, "competitors": [{"name": "ClickUp"}, {"name": "Trello"}],
           "questions": ["q1", "q2"]}
    brands, runs, ab = A.run_check(cfg, c, 2, "sys", ["web"], None, None, 1.0, ab_n=1, log=lambda m: None)
    assert len(runs) == 4 and len(ab) == 2
    assert "system_message" not in s.sent[-1]["json"] and s.sent[0]["json"]["system_message"] == "sys"
    md = A.render_markdown({"brand": "Asana", "questions": cfg["questions"], "runs": 2, "tools": ["web"],
                            "system_message": "sys", "started": "2026-10-10 10:00"}, runs, c.calls, list(brands),
                           A.ab_rows(runs, ab))
    assert "| Asana (you) | 4 / 4 | 100% |" in md
    assert "example-reviews.com" in md and "$0.0240" in md and "With vs without" in md
    assert "\u2014" not in md


def test_max_spend_stops_calls():
    s = FakeSession([FakeResp(200, {"completion": "x"}, HDR) for _ in range(5)])
    c = A.Client("k", session=s)
    cfg = {"brand": {"name": "Asana"}, "questions": ["q1", "q2", "q3"]}
    _, runs, _ = A.run_check(cfg, c, 1, "sys", ["web"], None, None, 0.008, log=lambda m: None)
    assert len(runs) == 2


def test_html_anchor_links_are_parsed_and_stripped():
    c = ('The easiest is <a href="https://www.reviews-example.com/easy/" target="_blank">Lark</a> '
         '[1](https://x.com/someone/status/123) and Asana.')
    r = A.analyse_run(c, "Asana", P)
    assert r["cited_urls"] == ["https://x.com/someone/status/123", "https://www.reviews-example.com/easy/"]
    assert r["html_links"] == 1 and "reviews-example.com" in r["cited_domains"]
    assert r["brand_sentence"] == "The easiest is Lark and Asana."


def test_redact_x_users_in_public_text():
    s = "Per @jane_doe99 (https://x.com/jane_doe99/status/42) and twitter.com/x, Asana is fine. mail a@b.com"
    out = A.redact_x_users(s)
    assert "jane_doe99" not in out and out.count("an X user") == 2 and "a@b.com" in out


def test_render_never_shows_x_handles():
    runs = [dict(_run("q1", 1, ["Asana"], ["x.com"]), brand_sentence="Asana is loved by @jane_doe99.",
                 sources=[], completion="")]
    md = A.render_markdown({"brand": "Asana", "questions": ["q1"], "runs": 1, "tools": ["web", "twitter"],
                            "system_message": "s", "started": "2026-10-10 10:00"}, runs, [], ["Asana"])
    assert "jane_doe99" not in md and "an X user" in md


def test_reanalyse_from_raw(tmp_path):
    body = {"completion": SUMMARY, "search": [{"title": "t", "link": "https://www.example-reviews.com/x"}]}
    s = FakeSession([FakeResp(503, {"detail": "x"}, {}), FakeResp(200, body, HDR), FakeResp(200, body, HDR)])
    c = A.Client("dsr_test_reanalyse", session=s, raw_dir=str(tmp_path))
    cfg = {"brand": {"name": "Asana"}, "competitors": [{"name": "Trello"}], "questions": ["q1", "q2"]}
    A.run_check(cfg, c, 1, "sys", ["web"], None, None, 1.0, log=lambda m: None)
    cfg2 = {"brand": {"name": "Trello"}, "competitors": [{"name": "Asana"}, {"name": "ClickUp"}], "questions": []}
    brands, runs, ab, calls = A.reanalyse(cfg2, str(tmp_path))
    assert len(calls) == 3 and len(runs) == 2 and all(r["ok"] for r in runs)
    assert runs[0]["brand_position"] == 3 and runs[0]["brands_named"] == ["ClickUp", "Asana", "Trello"]
