import hashlib, json, os, subprocess, sys
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import directory_finder as d  # noqa: E402

SAMPLE = os.path.join(ROOT, "samples", "raw-sample.json")
BOX_KEY = "/home/box/.saba/desearch_api_key"


def test_domain_strips_www():
    assert d.domain("https://www.Example.com/submit") == "example.com"


def test_extract_text_shapes():
    assert d.extract_text({"body": {"content": "hi"}}) == "hi"
    assert d.extract_text({"body": {"data": {"text": "yo"}}}) == "yo"
    assert d.extract_text({"body": {}}) == ""


def test_shortlist_dedupes_and_picks_submit_pages():
    raw = json.load(open(SAMPLE))
    cands, pick = d.shortlist_candidates(raw["searches"], 6)
    doms = [c["domain"] for c in cands]
    assert len(doms) == len(set(doms))
    assert pick and all(c["looks_like_submit_page"] for c in pick)


def test_clean_quote_blocks_seo_numbers():
    assert d.clean_quote("DR 70 backlink") == ""
    assert d.clean_quote("Submit for free") == "Submit for free"


def test_from_raw_offline(tmp_path):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "directory_finder.py"), "--from-raw", SAMPLE,
                        "--out", "out"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    md = (tmp_path / "out" / "shortlist.md").read_text()
    assert "Made by [Desearch](https://desearch.ai)." in md
    assert "\u2014" not in md
    assert (tmp_path / "out" / "directories.csv").read_text().startswith("domain,")


def test_missing_key_file_exits(tmp_path):
    with pytest.raises(SystemExit):
        d.load_key(str(tmp_path / "nope"))


def test_key_file_read_and_env_ignored(tmp_path, monkeypatch):
    f = tmp_path / "k"; f.write_text("abc123\n")
    monkeypatch.setenv("DESEARCH_API_KEY", "fromenv")
    assert d.load_key(str(f)) == "abc123"


@pytest.mark.skipif(not os.path.isfile(BOX_KEY), reason="box-only: key file missing")
def test_box_key_fingerprint():
    assert hashlib.sha256(d.load_key(BOX_KEY).encode()).hexdigest()[:8] == "a44f278b"
