import hashlib
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import whos_asking as wa  # noqa: E402

FIX = json.load(open(os.path.join(os.path.dirname(__file__), "fixture_posts.json")))


def test_build_args_keeps_or_in_parentheses_and_adds_no_retweets():
    a = wa.build_args('("alternative to" OR "switching from") newsletter', "2026-09-03", "2026-10-03", 30)
    assert a == {"query": '("alternative to" OR "switching from") newsletter -filter:retweets',
                 "count": 30, "start_date": "2026-09-03", "end_date": "2026-10-03", "lang": "en"}


def test_default_groups_wrap_or_terms():
    for g in wa.DEFAULT_GROUPS:
        assert g.startswith("(") and " OR " in g


def test_build_args_never_sends_exclude_domains():
    assert "exclude_domains" not in wa.build_args("x", "2026-01-01", "2026-01-02")


def test_build_args_rejects_empty():
    with pytest.raises(ValueError):
        wa.build_args(" ", "2026-01-01", "2026-01-02")


def test_window():
    import datetime as dt
    assert wa.window(30, dt.date(2026, 10, 3)) == ("2026-09-03", "2026-10-03")


def test_intent_levels():
    assert wa.intent("Can anyone recommend a newsletter tool?") == "High"
    assert wa.intent("Which newsletter app do you all use?") == "Medium"
    assert wa.intent("Check out the latest issue of my newsletter") == "Low"


def test_rank_dedupes_drops_out_of_window_and_orders():
    rows = wa.rank(FIX, "2026-09-03", "2026-10-03")
    assert [r["link"] for r in rows] == ["https://x.com/i/status/1", "https://x.com/i/status/2",
                                         "https://x.com/i/status/3"]
    assert [r["intent"] for r in rows] == ["High", "Medium", "Low"]


def test_parse_posts():
    assert len(wa.parse_posts([{"type": "text", "text": json.dumps(FIX)}])) == len(FIX)
    assert wa.parse_posts([{"type": "text", "text": "oops"}]) == []


def test_hide_handles():
    t = wa.format_table(wa.rank(FIX, "2026-09-03", "2026-10-03"), hide_handles=True)
    assert "user_a" not in t and "x.com" not in t and "person #1" in t


def test_read_key_from_file_not_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DESEARCH_API_KEY", "env-key-must-not-be-used")
    f = tmp_path / "k"
    f.write_text("file-key\n")
    assert wa.read_key(str(f)) == "file-key"
    assert wa.key_fingerprint("file-key") == hashlib.sha256(b"file-key").hexdigest()[-4:]


def test_main_exits_without_key_file(tmp_path):
    with pytest.raises(SystemExit):
        wa.main(["--key-file", str(tmp_path / "missing")])


@pytest.mark.skipif(not os.path.exists("/home/box/.keti/desearch-api-key"), reason="builder box only")
def test_builder_key_fingerprint():
    assert wa.key_fingerprint(wa.read_key("/home/box/.keti/desearch-api-key")) == "560b"
