import csv, json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import tiktok_profile_analytics as t

SAMPLE = os.path.join(HERE, "samples", "sample-raw.json")


def post(i, ts, views=1000, likes=100, com=10, sh=5):
    return {"id": str(i), "url": f"u{i}", "text": "hi \u2014 there", "createTime": ts,
            "stats": {"playCount": views, "digCount": likes, "commentCount": com, "shareCount": sh, "collectCount": 1}}


class Offline(unittest.TestCase):
    def test_sample_rebuild(self):
        with tempfile.TemporaryDirectory() as d:
            rows, summ, _ = t.build(json.load(open(SAMPLE)), os.path.join(d, "x"))
            self.assertEqual(len(rows), 30)
            self.assertEqual(len(summ), 3)
            with open(os.path.join(d, "x-posts.csv")) as f:
                self.assertEqual(next(csv.reader(f)), t.POST_FIELDS)
            self.assertTrue(all(s["followers"] for s in summ))

    def test_engagement_rate(self):
        r = t.post_row("b", post(1, 1700000000))
        self.assertAlmostEqual(r["engagement_rate_pct"], 11.5)
        self.assertNotIn("\u2014", r["caption"])
        self.assertIsNone(t.post_row("b", post(2, 1700000000, views=0))["engagement_rate_pct"])

    def test_pinned_detection(self):
        ps = [post(1, 100), post(2, 200), post(3, 1000), post(4, 900), post(5, 800)]
        self.assertEqual(t.pinned_ids(ps), {"1", "2"})
        self.assertEqual(t.pinned_ids([post(1, 3), post(2, 2), post(3, 1)]), set())

    def test_cadence_floor(self):
        rows = [t.post_row("b", post(i, 1700000000 + i * 60)) for i in range(7)]
        s = t.summarize("b", {"followers": 10}, rows)
        self.assertEqual(s["posts_per_week"], 7.0)

    def test_empty_profile_skipped(self):
        raw = {"started": "x", "calls": [{"profile": "nope", "kind": "profile", "status": 503, "body": {"detail": "x"}, "params": {}, "label": "nope profile"}]}
        with tempfile.TemporaryDirectory() as d:
            rows, summ, _ = t.build(raw, os.path.join(d, "x"))
            self.assertEqual((rows, summ), ([], []))

    def test_count_cap_and_key_file_only(self):
        self.assertEqual(t.MAX_COUNT, 20)
        src = open(os.path.join(HERE, "tiktok_profile_analytics.py")).read()
        self.assertNotIn("os.environ", src)
        with self.assertRaises(SystemExit):
            t.read_key("/nonexistent/key")

    def test_cli_from_raw(self):
        with tempfile.TemporaryDirectory() as d:
            out = subprocess.run([sys.executable, os.path.join(HERE, "tiktok_profile_analytics.py"), "--from-raw", SAMPLE,
                                  "--out", os.path.join(d, "y")], capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("30 posts", out.stdout)


if __name__ == "__main__":
    unittest.main()
