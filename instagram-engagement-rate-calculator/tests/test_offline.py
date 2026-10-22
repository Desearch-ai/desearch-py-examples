import csv, datetime as dt, json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import ig_engagement_rate as g

SAMPLE = os.path.join(HERE, "samples", "sample-raw.json")
REF = dt.datetime(2026, 10, 17, tzinfo=dt.timezone.utc)


def post(i, ts, likes=900, com=100, media="image", views=None, children=0):
    s = {"likeCount": likes, "commentCount": com}
    if views is not None: s["playCount"] = views
    return {"id": str(i), "shortcode": f"S{i}", "createTime": ts, "mediaType": media, "stats": s,
            "caption": "hi @someone \u2014 there", "children": [{}] * children}


class Offline(unittest.TestCase):
    def test_formula(self):
        r = g.post_row("b", 10000, post(1, "2026-10-10T10:00:00Z"), REF)
        self.assertAlmostEqual(r["engagement_rate_pct"], 10.0)  # (900 + 100) / 10000 x 100
        self.assertNotIn("\u2014", r["caption"]); self.assertNotIn("@someone", r["caption"])
        v = g.post_row("b", 10000, post(2, 1760000000, media="video", views=20000), REF)
        self.assertAlmostEqual(v["engagement_per_view_pct"], 5.0)
        self.assertIsNone(g.post_row("b", None, post(3, 1760000000), REF)["engagement_rate_pct"])

    def test_hidden_likes_excluded(self):
        for hidden in (None, -1):
            r = g.post_row("b", 10000, post(1, 1760000000, likes=hidden), REF)
            self.assertTrue(r["likes_hidden"]); self.assertIsNone(r["engagement_rate_pct"])

    def test_time_formats(self):
        a = g.parse_time(1792090802); b = g.parse_time("1792090802"); c = g.parse_time("2026-10-15T19:00:02Z")
        self.assertEqual(a, b); self.assertEqual(a.year, 2026); self.assertEqual(c.tzinfo, dt.timezone.utc)
        self.assertIsNone(g.parse_time("not a time"))

    def test_format_split_and_mean(self):
        rows = [g.post_row("b", 1000, post(i, 1759000000 + i, likes=l, com=0, media=m), REF)
                for i, (l, m) in enumerate([(10, "image"), (30, "image"), (50, "carousel"), (20, "video"), (40, "clips")])]
        for r in rows: r["used_in_rate"] = True
        s, f = g.summarize("b", 1000, rows)
        self.assertAlmostEqual(s["engagement_rate_pct"], 3.0)  # mean of 1, 3, 5, 2, 4
        self.assertAlmostEqual(s["median_engagement_rate_pct"], 3.0)
        by = {x["format"]: x for x in f}
        self.assertEqual(set(by), {"image", "carousel", "video/reel"})
        self.assertEqual(by["video/reel"]["posts"], 2); self.assertAlmostEqual(by["image"]["engagement_rate_pct"], 2.0)
        self.assertTrue(s["best_format"].startswith("carousel"))

    def test_format_map(self):
        self.assertEqual(g.fmt_of({"mediaType": "carousel_album"})[0], "carousel")
        self.assertEqual(g.fmt_of({"mediaType": None, "children": [{}]})[0], "carousel")
        self.assertEqual(g.fmt_of({"mediaType": "Video"})[0], "video/reel")

    def test_pinned_and_fresh_skipped(self):
        day = 86400; t0 = int(REF.timestamp())
        ps = [post(1, t0 - 40 * day), post(2, t0 - 30 * day), post(3, t0 - 3600), post(4, t0 - 2 * day), post(5, t0 - 3 * day)]
        self.assertEqual(g.pinned_ids(ps), {"1", "2"})
        raw = {"started": REF.isoformat(), "calls": [
            {"account": "b", "kind": "profile", "status": 200, "body": {"followers": 1000}, "params": {}, "label": "b profile"},
            {"account": "b", "kind": "posts", "status": 200, "body": ps, "params": {"count": 5}, "label": "b posts p1"}]}
        with tempfile.TemporaryDirectory() as d:
            rows, summ, _ = g.build(raw, os.path.join(d, "x"))
        s = summ[0]
        self.assertEqual((s["posts_returned"], s["posts_used"], s["skipped_pinned"], s["skipped_under_24h"]), (5, 2, 2, 1))

    def test_sample_rebuild(self):
        with tempfile.TemporaryDirectory() as d:
            rows, summ, fmts = g.build(json.load(open(SAMPLE)), os.path.join(d, "x"))
            self.assertEqual(len(rows), 36); self.assertEqual(len(summ), 3)
            self.assertEqual({s["account"] for s in summ}, {"brand_a", "brand_b", "brand_c"})
            self.assertTrue(all(s["followers"] and s["engagement_rate_pct"] for s in summ))
            self.assertEqual({f["format"] for f in fmts}, {"image", "carousel", "video/reel"})
            with open(os.path.join(d, "x-posts.csv")) as f:
                self.assertEqual(next(csv.reader(f)), g.POST_FIELDS)
            md = open(os.path.join(d, "x-summary.md")).read()
            self.assertIn("(likes + comments) / followers x 100", md)
            self.assertTrue(os.path.isfile(os.path.join(d, "x-formats.svg")))

    def test_not_found_skipped(self):
        raw = {"started": "2026-10-17T09:28:45+04:00", "calls": [
            {"account": "nope", "kind": "profile", "status": 404, "body": {"detail": "Resource not found"}, "params": {}, "label": "nope profile"}]}
        with tempfile.TemporaryDirectory() as d:
            rows, summ, _ = g.build(raw, os.path.join(d, "x"))
            self.assertEqual((rows, summ), ([], []))

    def test_public_sample_is_masked(self):
        blob = open(SAMPLE).read().lower()
        for bad in ("http", "cost_usd", "x-desearch-cost", "\u2014"):
            self.assertNotIn(bad, blob)

    def test_count_cap_and_key_file_only(self):
        self.assertEqual(g.MAX_COUNT, 20)
        src = open(os.path.join(HERE, "ig_engagement_rate.py")).read()
        self.assertNotIn("os.environ", src); self.assertNotIn("getenv", src)
        with self.assertRaises(SystemExit):
            g.read_key("/nonexistent/key")

    def test_cli_from_raw(self):
        with tempfile.TemporaryDirectory() as d:
            out = subprocess.run([sys.executable, os.path.join(HERE, "ig_engagement_rate.py"), "--from-raw", SAMPLE,
                                  "--out", os.path.join(d, "y")], capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("36 posts", out.stdout); self.assertIn("brand_b: engagement rate", out.stdout)

    def test_all_excluded_prints_na(self):
        day = 86400; t0 = int(REF.timestamp())
        # older posts listed first are likely pinned; the rest are under 24h, so none are eligible
        ps = [post(1, t0 - 40 * day), post(2, t0 - 30 * day), post(3, t0 - 3600)]
        raw = {"started": REF.isoformat(), "calls": [
            {"account": "b", "kind": "profile", "status": 200, "body": {"followers": 1000}, "params": {}, "label": "b profile"},
            {"account": "b", "kind": "posts", "status": 200, "body": ps, "params": {"count": 3}, "label": "b posts p1"}]}
        with tempfile.TemporaryDirectory() as d:
            raw_path = os.path.join(d, "raw.json")
            json.dump(raw, open(raw_path, "w"))
            outp = os.path.join(d, "y")
            out = subprocess.run([sys.executable, os.path.join(HERE, "ig_engagement_rate.py"), "--from-raw", raw_path,
                                  "--out", outp], capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertNotIn("None %", out.stdout)
            self.assertIn("b: engagement rate n/a (no eligible posts; try a higher --count)", out.stdout)
            with open(outp + "-summary.csv") as f:
                row = next(csv.DictReader(f))
            self.assertEqual((row["posts_used"], row["engagement_rate_pct"], row["median_engagement_rate_pct"]), ("0", "", ""))


if __name__ == "__main__":
    unittest.main()
