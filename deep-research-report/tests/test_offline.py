"""Offline tests: no key, no network. Run: python -m unittest discover -s tests"""
import csv, json, os, re, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import deep_research_report as d

SAMPLE = os.path.join(ROOT, "samples", "sample-raw.json")


def res(url, title, date="2026-10-10", hl=None, pt=None):
    return {"url": url, "title": title, "published_date": date, "highlights": hl, "page_text": pt}


def raw_of(*calls, start="2026-10-01", end="2026-10-19"):
    return {"started": "2026-10-19T10:00:00+04:00", "topic": "test topic", "question": "Q?", "start_date": start, "end_date": end,
            "mode": "balanced", "count": 20,
            "calls": [{"tag": t, "params": {"query": q}, "status": 200, "cost_usd": 0.01, "body": {"results": rs, "cost_usd": 0.01}}
                      for t, q, rs in calls]}


S1 = "Stablecoin payments grew quickly this year, the report said."
PT = "Intro line about something else entirely here. " + S1 + " Another sentence that does not matter much at all."
HL = re.sub(r"(?<=[,.])\s+", "", S1)  # highlights come back with spaces after punctuation removed


class Offline(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def test_sample_rebuilds(self):
        sources, findings, st, c, m = d.build(json.load(open(SAMPLE, encoding="utf-8")), self.d)
        self.assertEqual(st["calls"], 5); self.assertTrue(sources)
        self.assertTrue(all(p for _, _, p in findings)); self.assertTrue(os.path.isfile(c) and os.path.isfile(m))

    def test_cli_from_raw(self):
        d.main(["--from-raw", SAMPLE, "--out", self.d])
        self.assertTrue(any(f.startswith("report-") for f in os.listdir(self.d)))

    def test_every_quote_is_exact_returned_text(self):
        raw = json.load(open(SAMPLE, encoding="utf-8"))
        returned = " ".join((r.get("page_text") or "") + " " + " ".join(r.get("highlights") or [])
                            for c in raw["calls"] for r in c["body"]["results"])
        _, findings, *_ = d.build(raw, self.d)
        for _, _, picked in findings:
            for s in picked:
                self.assertIn(s["quote"], returned)

    def test_every_finding_has_link_and_date_in_window(self):
        raw = json.load(open(SAMPLE, encoding="utf-8"))
        *_, m = d.build(raw, self.d)
        lines = open(m, encoding="utf-8").read().splitlines()
        cites = [l for l in lines if l.startswith("Source [")]
        self.assertEqual(len(cites), sum(1 for l in lines if l.startswith("> ")))
        for l in cites:
            date = re.search(r"published (\d{4}-\d\d-\d\d)$", l).group(1)
            self.assertTrue(raw["start_date"] <= date <= raw["end_date"]); self.assertIn("](http", l)

    def test_quote_from_page_text_inside_highlight(self):
        q, kind = d.pick_quote(res("https://a.test/x", "T", hl=[HL], pt=PT), "stablecoin payments growth")
        self.assertEqual((q, kind), (S1, "page text, inside matched passage"))
        q, kind = d.pick_quote(res("https://a.test/x", "T", hl=[HL + " Extra words here to fill"], pt=None), "stablecoin payments")
        self.assertEqual(kind, "highlight as returned"); self.assertIn(q, HL + " Extra words here to fill")

    def test_sentences_keep_abbreviations(self):
        t = "He said on Oct. 16 that the U.S. rules would change for every issuer. Next one is here and long enough."
        self.assertEqual(list(d.sentences(t))[0], "He said on Oct. 16 that the U.S. rules would change for every issuer.")

    def test_dedupe_by_url(self):
        raw = raw_of(("a", "q a", [res("https://www.a.test/story/?utm=1", "Alpha story one", hl=[HL], pt=PT)]),
                     ("b", "q b", [res("https://a.test/story", "Alpha story one", hl=[HL], pt=PT)]))
        sources, _, st, *_ = d.build(raw, self.d)
        self.assertEqual(len(sources), 1); self.assertEqual(st["dup_url"], 1); self.assertEqual(sources[0]["sub_questions"], ["a", "b"])

    def test_near_identical_titles_merge(self):
        a = d.title_key("Issuer Circle to push into 40 new markets, CEO says | Wire News | Wire")
        b = d.title_key("Issuer Circle to push into 40 new markets, CEO says \u2014 Other Site")
        c = d.title_key("Regulators warn about stablecoin runs ahead of summit")
        self.assertTrue(d.near_same(a, b)); self.assertFalse(d.near_same(a, c))
        raw = raw_of(("a", "q", [res("https://one.test/1", "Issuer Circle to push into 40 new markets, CEO says - One", hl=[HL], pt=PT),
                                 res("https://two.test/2", "Issuer Circle to push into 40 new markets, CEO says | Two", hl=[HL], pt=PT)]))
        sources, _, st, *_ = d.build(raw, self.d)
        self.assertEqual((len(sources), st["dup_title"]), (1, 1))

    def test_out_of_window_and_undated_listed_not_quoted(self):
        raw = raw_of(("a", "stablecoin payments", [res("https://old.test/1", "Old page about payments", "2025-01-01", [HL], PT),
                                                    res("https://nodate.test/2", "Undated page about payments", None, [HL], PT),
                                                    res("https://ok.test/3", "Good page about payments", "2026-10-10", [HL], PT)]))
        sources, findings, st, c, m = d.build(raw, self.d)
        self.assertEqual((st["out_of_window"], st["undated"], len(sources)), (1, 1, 3))
        self.assertEqual([s["outlet"] for s in findings[0][2]], ["ok.test"])
        md = open(m, encoding="utf-8").read()
        self.assertIn("| no date | no date |", md); self.assertIn("| 2025-01-01 | no |", md)

    def test_one_per_outlet_and_fresh_sources_first(self):
        r1 = res("https://a.test/1", "First page title words", hl=[HL], pt=PT)
        r2 = res("https://a.test/2", "Second page different title", hl=[HL], pt=PT)
        r3 = res("https://b.test/3", "Third page other outlet name", hl=[HL], pt=PT)
        _, findings, *_ = d.build(raw_of(("a", "stablecoin payments", [r1, r2]), ("b", "stablecoin payments", [r1, r3])), self.d)
        self.assertEqual([s["url"] for s in findings[0][2]], ["https://a.test/1"])
        self.assertEqual([s["url"] for s in findings[1][2]], ["https://b.test/3", "https://a.test/1"])

    def test_csv_has_quote_and_passage(self):
        *_, c, m = d.build(raw_of(("a", "stablecoin payments", [res("https://a.test/1", "Page", hl=[HL], pt=PT)])), self.d)
        row = next(csv.DictReader(open(c, encoding="utf-8")))
        self.assertEqual((row["quote"], row["passage"]), (S1, HL))

    def test_request_body_and_headers(self):
        sent = {}
        class Resp:
            status_code, headers = 200, {"Date": "x"}
            def json(self): return {"results": [], "cost_usd": 0.005, "usage_count": 10}
        class Sess:
            headers = {}
            def post(self, url, json=None, timeout=None): sent.update(url=url, body=json); return Resp()
        rec = d.search(Sess(), "t", "a question", start_date="2026-10-01", end_date="2026-10-19")
        self.assertEqual(sent["url"], "https://api.desearch.ai/search")
        self.assertEqual(sent["body"], {"query": "a question", "mode": "balanced", "count": 20, "highlights": True, "page_text": True,
                                        "start_date": "2026-10-01", "end_date": "2026-10-19"})
        self.assertEqual(rec["cost_usd"], 0.005)  # body cost used when no cost header is sent
        self.assertIn("User-Agent", d.session_for("k").headers)

    def test_plan(self):
        self.assertEqual(len(d.plan("x")), 5); self.assertIn("x", d.plan("x")[0][1])
        self.assertEqual(d.plan("x", ["a?", "b?"]), [("q1", "a?"), ("q2", "b?")])

    def test_no_handles_or_em_dashes_in_samples(self):
        for f in os.listdir(os.path.join(ROOT, "samples")):
            t = open(os.path.join(ROOT, "samples", f), encoding="utf-8").read()
            self.assertNotIn("\u2014", t, f); self.assertIsNone(re.search(r"(?<![\w/.])@\w{2,15}", t), f)

    def test_key_file_errors(self):
        with self.assertRaises(SystemExit): d.read_key(os.path.join(self.d, "missing"))
        p = os.path.join(self.d, "empty"); open(p, "w").close()
        with self.assertRaises(SystemExit): d.read_key(p)


if __name__ == "__main__":
    unittest.main()
