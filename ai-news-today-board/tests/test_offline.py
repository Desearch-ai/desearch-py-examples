"""Offline tests: no key, no network. Run: python -m unittest discover -s tests"""
import csv, json, os, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import ai_news_board as b

SAMPLE = os.path.join(ROOT, "samples", "sample-raw.json")


def tweet(i, text, likes=50, when="Sun Oct 18 10:00:00 +0000 2026", rt=1, rp=2):
    return {"id": str(i), "text": text, "created_at": when, "like_count": likes, "retweet_count": rt, "reply_count": rp}


def raw_of(xbody, webbody=None, started="2026-10-18T16:00:00+04:00"):
    calls = [{"source": "x", "tag": "model release", "status": 200, "cost_usd": 0.001, "body": xbody}]
    if webbody is not None:
        calls.append({"source": "web", "tag": "ai funding", "status": 200, "cost_usd": "0.002", "body": {"search": webbody}})
    return {"started": started, "min_likes": 20, "sites": ["example-news.test"], "calls": calls}


class Offline(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def run_build(self, raw, **kw):
        return b.build(raw, self.d, **kw)

    def test_sample_rebuilds(self):
        rows, stats, c, m = self.run_build(json.load(open(SAMPLE)))
        self.assertTrue(rows); self.assertTrue(os.path.isfile(c)); self.assertTrue(os.path.isfile(m))
        self.assertEqual(stats["calls"], 10)

    def test_cli_from_raw(self):
        b.main(["--from-raw", SAMPLE, "--out", self.d, "--seen-file", os.path.join(self.d, "seen.txt")])
        self.assertTrue(any(f.endswith(".csv") for f in os.listdir(self.d)))
        self.assertFalse(os.path.exists(os.path.join(self.d, "seen.txt")))  # offline runs do not touch the seen file

    def test_text_is_not_edited(self):
        t = "New model “X-1” is out: https://t.co/abc"
        rows, *_ = self.run_build(raw_of([tweet(1, t)]))
        self.assertEqual(rows[0]["title_or_text"], t)

    def test_mentions_left_out(self):
        rows, stats, *_ = self.run_build(raw_of([tweet(1, "thanks @someone for the model"), tweet(2, "email me a@b.co about AI")]))
        self.assertEqual(stats["x_skipped_mentions"], 1); self.assertEqual(len(rows), 1)

    def test_min_likes_and_age_and_link_only(self):
        rows, stats, *_ = self.run_build(raw_of([tweet(1, "AI model", likes=5), tweet(2, "old AI news", when="Thu Oct 15 10:00:00 +0000 2026"),
                                                  tweet(3, "https://t.co/xyz"), tweet(4, "fresh AI news")]))
        self.assertEqual((stats["x_below_min_likes"], stats["x_too_old"], stats["x_link_only"]), (1, 1, 1))
        self.assertEqual([r["url"] for r in rows], ["https://x.com/i/status/4"])

    def test_dedupe_merges_tags(self):
        raw = raw_of([tweet(1, "AI model")])
        raw["calls"].append({"source": "x", "tag": "open source llm", "status": 200, "body": [tweet(1, "AI model")]})
        rows, stats, *_ = self.run_build(raw)
        self.assertEqual(len(rows), 1); self.assertEqual(rows[0]["tag"], "model release; open source llm"); self.assertEqual(stats["duplicates"], 1)

    def test_web_pages_dates_and_site_list(self):
        web = [{"title": "AI startup raises", "link": "https://www.example-news.test/2026/10/17/ai-startup/"},
               {"title": "Old AI story", "link": "https://example-news.test/2025/01/02/old/"},
               {"title": "Undated AI page", "link": "https://other.test/story/ai"},
               {"title": "Dated AI page", "link": "https://example-news.test/story/x", "published_date": "2026-10-16"}]
        rows, stats, *_ = self.run_build(raw_of([], web))
        self.assertEqual(stats["web_too_old"], 1); self.assertEqual(stats["web_undated"], 1); self.assertEqual(stats["web_off_list"], 1)
        self.assertEqual(len(rows), 3); self.assertEqual(rows[0]["published_utc"], "2026-10-17"); self.assertEqual(rows[2]["published_utc"], "2026-10-16")

    def test_seen_file_marks_new(self):
        seen = os.path.join(self.d, "seen.txt")
        open(seen, "w").write("https://x.com/i/status/1\n")
        rows, *_ = self.run_build(raw_of([tweet(1, "AI one"), tweet(2, "AI two")]), seen_file=seen, update_seen=True)
        self.assertEqual({r["url"]: r["new_today"] for r in rows}, {"https://x.com/i/status/1": False, "https://x.com/i/status/2": True})
        self.assertIn("https://x.com/i/status/2", open(seen).read())

    def test_top_15_by_engagement(self):
        rows, s, c, m = self.run_build(raw_of([tweet(i, f"AI item {i}", likes=20 + i) for i in range(20)]))
        md = open(m).read()
        self.assertIn("Top 15 posts", md); self.assertIn("AI item 19", md.split("\n")[6]); self.assertNotIn("AI item 4\"", md)

    def test_status_url_normalized(self):
        self.assertEqual(b.norm_url("https://twitter.com/someone/status/123?s=20"), "https://x.com/i/status/123")

    def test_no_handles_or_users_in_sample(self):
        raw = json.load(open(SAMPLE))
        for c in raw["calls"]:
            if c["source"] == "x":
                for t in c["body"]:
                    self.assertNotIn("user", t); self.assertIsNone(b.MENTION.search(t["text"]))

    def test_key_file_errors(self):
        with self.assertRaises(SystemExit): b.read_key(os.path.join(self.d, "missing"))
        p = os.path.join(self.d, "empty"); open(p, "w").close()
        with self.assertRaises(SystemExit): b.read_key(p)


if __name__ == "__main__":
    unittest.main()
