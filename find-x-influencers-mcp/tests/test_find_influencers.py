import hashlib
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import find_influencers as fi  # noqa: E402


def post(i, handle, likes, followers=100):
    return {"id": str(i), "url": f"https://x.com/{handle}/status/{i}", "like_count": likes,
            "user": {"username": handle, "name": handle.title(), "followers_count": followers}}


POSTS = [post(1, "alpha", 10), post(2, "alpha", 30), post(3, "beta", 5), post(4, "beta", 5),
         post(5, "beta", 1), post(6, "gamma", 999), post(2, "alpha", 30)]


def test_build_args_adds_no_retweets_and_keeps_parentheses():
    a = fi.build_args('("sourdough" OR "bread baking") lang:en', 30)
    assert a == {"query": '("sourdough" OR "bread baking") lang:en -is:retweet', "count": 30}


def test_build_args_never_sends_exclude_domains():
    assert "exclude_domains" not in fi.build_args("x", verified=True, min_likes=5)


def test_build_args_filters():
    a = fi.build_args("x", verified=True, min_likes=5)
    assert a["verified"] is True and a["min_likes"] == 5


def test_build_args_rejects_empty():
    with pytest.raises(ValueError):
        fi.build_args("  ")


def test_rank_authors_min_posts_dedupe_and_order():
    r = fi.rank_authors(POSTS)
    assert [a["handle"] for a in r] == ["alpha", "beta"]
    assert r[0]["posts"] == 2 and r[0]["likes"] == 40
    assert r[0]["top_link"].endswith("/2")


def test_rank_authors_min_posts_one_includes_single():
    assert fi.rank_authors(POSTS, 1)[0]["handle"] == "gamma"


def test_parse_posts():
    assert len(fi.parse_posts([{"type": "text", "text": json.dumps(POSTS)}])) == 7
    assert fi.parse_posts([{"type": "text", "text": "oops"}]) == []


def test_hide_handles():
    t = fi.format_table(fi.rank_authors(POSTS), hide_handles=True)
    assert "alpha" not in t and "a creator #1" in t


def test_read_key_from_file_not_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DESEARCH_API_KEY", "env-key-must-not-be-used")
    f = tmp_path / "k"
    f.write_text("file-key\n")
    assert fi.read_key(str(f)) == "file-key"
    assert fi.key_fingerprint("file-key") == hashlib.sha256(b"file-key").hexdigest()[-4:]


def test_main_exits_without_key_file(tmp_path):
    with pytest.raises(SystemExit):
        fi.main(["x", "--key-file", str(tmp_path / "missing")])


@pytest.mark.skipif(not os.path.exists("/home/box/.keti/desearch-api-key"), reason="builder box only")
def test_builder_key_fingerprint():
    assert fi.key_fingerprint(fi.read_key("/home/box/.keti/desearch-api-key")) == "560b"
