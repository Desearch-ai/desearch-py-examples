"""Offline tests: no key, no network."""
import csv, io, json, os, sys, tempfile, unittest
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import x_account_analytics as xa  # noqa: E402

USER = {"id": "1", "username": "example_account", "followers_count": 1000, "statuses_count": 50, "pinned_tweet_ids": ["p1"]}


def tw(i, when="Mon Oct 19 08:55:45 +0000 2026", **kw):
    t = {"id": str(i), "text": "hello", "created_at": when, "like_count": 10, "retweet_count": 2, "reply_count": 3,
         "quote_count": 1, "bookmark_count": 4, "view_count": 200, "url": f"https://example.invalid/{i}", "media": []}
    t.update(kw)
    return t


def raw_of(*pages):
    return {"started": "2026-10-19T15:00:00+04:00", "username": "example_account",
            "calls": [{"page": n, "cursor_sent": "c" if n > 1 else None, "status": 200, "seconds": 1.0,
                       "cost_usd": None, "body": {"user": USER, "tweets": list(p), "next_cursor": "c"}}
                      for n, p in enumerate(pages, 1)]}


class Parsing(unittest.TestCase):
    def test_parse_x_date(self):
        d = xa.parse_time("Mon Oct 19 08:55:45 +0000 2026")
        self.assertEqual((d.year, d.month, d.day, d.hour, d.minute), (2026, 10, 19, 8, 55))

    def test_parse_iso_and_bad(self):
        self.assertEqual(xa.parse_time("2026-10-19T08:55:45Z").hour, 8)
        self.assertIsNone(xa.parse_time("not a date"))
        self.assertIsNone(xa.parse_time(None))

    def test_post_types(self):
        self.assertEqual(xa.post_type(tw(1), "1"), "original")
        self.assertEqual(xa.post_type(tw(1, is_retweet=True, is_quote_tweet=True), "1"), "repost")
        self.assertEqual(xa.post_type(tw(1, text="RT @example_account: hi"), "1"), "repost")
        self.assertEqual(xa.post_type(tw(1, in_reply_to_status_id="9", in_reply_to_user_id="1"), "1"), "thread")
        self.assertEqual(xa.post_type(tw(1, in_reply_to_status_id="9", in_reply_to_user_id="2"), "1"), "reply")
        self.assertEqual(xa.post_type(tw(1, is_quote_tweet=True), "1"), "quote")

    def test_media_kind(self):
        self.assertEqual(xa.media_kind(tw(1)), "none")
        self.assertEqual(xa.media_kind(tw(1, media=[{"type": "photo"}, {"type": "photo"}])), "photo")
        self.assertEqual(xa.media_kind(tw(1, media=[{"type": "animated_gif"}])), "gif")
        self.assertEqual(xa.media_kind(tw(1, media=[{"type": "photo"}, {"type": "video"}])), "mixed")


class Rates(unittest.TestCase):
    def test_formula(self):
        tz = xa.ZoneInfo("UTC")
        r = xa.post_row(tw(1), 1000, "1", set(), tz)
        self.assertEqual(r["engagements"], 20)  # 10 + 2 + 3 + 1 + 4
        self.assertEqual(r["er_per_view_pct"], 10.0)  # 20 / 200
        self.assertEqual(r["er_per_follower_pct"], 2.0)  # 20 / 1000
        self.assertTrue(r["in_rates"])

    def test_repost_excluded(self):
        r = xa.post_row(tw(1, is_retweet=True, like_count=0), 1000, "1", set(), xa.ZoneInfo("UTC"))
        self.assertFalse(r["in_rates"])
        self.assertIsNone(r["er_per_view_pct"])
        self.assertIn("repost", r["excluded_reason"])

    def test_missing_views_only_drops_per_view(self):
        r = xa.post_row(tw(1, view_count=None), 1000, "1", set(), xa.ZoneInfo("UTC"))
        self.assertTrue(r["in_rates"])
        self.assertIsNone(r["er_per_view_pct"])
        self.assertEqual(r["er_per_follower_pct"], 2.0)

    def test_time_zone_shift(self):
        r = xa.post_row(tw(1), 1000, "1", set(), xa.ZoneInfo("Asia/Tbilisi"))
        self.assertEqual((r["hour_local"], r["created_utc"][-5:]), (12, "08:55"))

    def test_pinned_flag(self):
        r = xa.post_row(tw("p1"), 1000, "1", {"p1"}, xa.ZoneInfo("UTC"))
        self.assertTrue(r["pinned"])


class Build(unittest.TestCase):
    def test_dedupe_and_repeats(self):
        raw = raw_of([tw(1), tw(2)], [tw(2), tw(3, view_count=None)], [tw(4, is_retweet=True)])
        res = xa.build(raw)
        self.assertEqual(len(res["rows"]), 4)
        self.assertEqual([p["repeats"] for p in res["pages"]], [0, 1, 0])
        self.assertEqual(res["summary"]["posts_in_rates"], 3)
        self.assertEqual(res["summary"]["excluded"], 1)
        self.assertEqual(len(res["no_views"]), 1)
        self.assertEqual(res["summary"]["reposts"], 1)
        self.assertEqual(res["n_view_rates"], 2)

    def test_empty_raw(self):
        res = xa.build({"started": "x", "username": "nobody", "calls": [{"page": 1, "status": 404, "body": None}]})
        self.assertEqual(res["rows"], [])
        self.assertIsNone(res["summary"]["median_engagements"])
        self.assertIn("none", xa.render_md(res))

    def test_best_slot_needs_two_posts(self):
        rows = [{"weekday_local": "Mon", "engagements": 100}, {"weekday_local": "Tue", "engagements": 5},
                {"weekday_local": "Tue", "engagements": 7}]
        best, _ = xa.best_slot(rows, "weekday_local")
        self.assertTrue(best.startswith("Tue"))

    def test_from_raw_sample_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "s")
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                res = xa.main(["--from-raw", os.path.join(ROOT, "samples", "sample-raw.json"), "--out", out,
                               "--key-file", os.path.join(d, "no-such-key")])
            for ext in ("-posts.csv", "-summary.csv", "-summary.md"):
                self.assertTrue(os.path.isfile(out + ext))
            with open(out + "-posts.csv", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), len(res["rows"]))
            self.assertGreater(len(rows), 0)
            self.assertEqual(len({r["post_id"] for r in rows}), len(rows))
            with open(out + "-summary.md", encoding="utf-8") as f:
                md = f.read()
            self.assertIn("the latest", md)
            self.assertIn("engagements = likes + reposts + replies + quotes + bookmarks", md)

    def test_key_file_errors(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit):
                xa.read_key(os.path.join(d, "missing"))
            p = os.path.join(d, "empty"); open(p, "w").close()
            with self.assertRaises(SystemExit):
                xa.read_key(p)

    def test_bad_inputs(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                xa.main(["--username", "not a handle!"])
            with self.assertRaises(SystemExit):
                xa.main(["--from-raw", "x.json", "--tz", "Mars/Olympus"])
            with self.assertRaises(SystemExit):
                xa.main([])

    def test_no_environment_key(self):
        with open(os.path.join(ROOT, "x_account_analytics.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("os.environ", src)
        self.assertNotIn("getenv", src)


if __name__ == "__main__":
    unittest.main()
