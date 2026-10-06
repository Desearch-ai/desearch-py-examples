"""Offline checks (no Desearch calls, no cost): python test_vocreport.py
1. keyword rules on hand-written examples
2. full pipeline on inline post and comment fixtures (both platforms)
3. the optional LLM classifier against a local stub server (/chat/completions shape)"""
import csv, http.server, json, os, tempfile, threading
import vocreport as v


def test_rules():
    k = v.KeywordClassifier()
    cases = {
        "PLEASE ADD ASL": "request", "please add a driving lesson": "request", "We need Georgian!": "request",
        "the app keeps crashing after the update": "complaint", "why did you remove the hearts": "complaint",
        "how do I reset my streak?": "question", "is this on android": "question",
        "I love this so much": "praise", "🔥🔥🔥": "praise", "Sonic! Buenos tardes": "other", "": "other",
    }
    bad = {t: (k.classify_text(t)[0], want) for t, want in cases.items() if k.classify_text(t)[0] != want}
    assert not bad, bad
    print(f"rules: {len(cases)} cases ok")


def _ig_post(shortcode, created, caption="hello"):
    return {
        "shortcode": shortcode,
        "url": f"https://www.instagram.com/p/{shortcode}/",
        "createTime": created,
        "caption": caption,
        "stats": {"commentCount": 100, "likeCount": 10},
    }


def _tt_post(video_id, created, text="hello"):
    return {
        "id": video_id,
        "url": f"https://www.tiktok.com/@duolingo/video/{video_id}",
        "createTime": created,
        "text": text,
        "stats": {"commentCount": 50, "digCount": 10},
    }


def test_pipeline_offline():
    ig_id = "DeAD9Qlh2CW"
    tt_id = "7692128874154429709"
    ig_posts = [_ig_post("OLD2025pin", "2025-03-01T00:00:00Z", "old pinned")]
    ig_posts.append(_ig_post(ig_id, "2026-10-05T18:00:00Z", "newest post"))
    for i in range(8):
        ig_posts.append(_ig_post(f"IG{i:02d}xxxx", f"2026-09-{20 - i:02d}T00:00:00Z"))
    tt_posts = [_tt_post(tt_id, "2026-10-05T15:00:00Z", "newest video")]
    for i in range(9):
        tt_posts.append(_tt_post(str(7690000000000000000 + i), f"2026-09-{20 - i:02d}T00:00:00Z"))

    ig_texts = [
        "PLEASE ADD ASL",
        "the app keeps crashing after the update",
        "how do I reset my streak?",
        "I love this so much",
        "so good \u2014 really",
        "Sonic! Buenos tardes",
        "",
    ] + ["ok"] * 8
    tt_texts = ["can you add this please"] + ["nice one"] * 14
    ig_comments = [
        {
            "id": f"igc{i}",
            "createTime": f"2026-10-05T12:{i:02d}:00Z",
            "likes": i,
            "replies": [],
            "author": {"id": f"a{i}", "username": f"user{i}"},
            "text": text,
        }
        for i, text in enumerate(ig_texts)
    ]
    # TikTok comments came back without an id. Epoch seconds for createTime.
    tt_comments = [
        {
            "createTime": 1759680000 + i,
            "likes": 10 - (i % 5),
            "replies": [],
            "author": {"id": f"ta{i}", "username": f"ttuser{i}"},
            "text": text,
        }
        for i, text in enumerate(tt_texts)
    ]

    def fake_get(self, path, params, label):
        self.calls.append({"path": path, "params": params, "cost_usd": 0.0, "status": 200})
        if path == "/desearch/instagram/profile/duolingo/posts":
            return 200, ig_posts
        if path == "/desearch/tiktok/profile/duolingo/posts":
            return 200, tt_posts
        if path == f"/desearch/instagram/comments/{ig_id}":
            return 200, ig_comments
        if path == f"/desearch/tiktok/comments/{tt_id}":
            return 200, tt_comments
        return 200, []

    orig = v.Desearch.get
    v.Desearch.get = fake_get
    try:
        with tempfile.TemporaryDirectory() as d:
            os.environ.setdefault("DESEARCH_API_KEY", "offline-test")
            out = v.main(["--instagram", "duolingo", "--tiktok", "duolingo", "--posts", "10", "--out", d, "--no-raw"])
            rep = open(os.path.join(out, "report.md")).read()
            rows = list(csv.reader(open(os.path.join(out, "comments.csv"), encoding="utf-8")))
            assert "Made by Desearch" in rep and "\u2014" not in rep
            assert len(rows) == 1 + 15 + 15, len(rows)  # header + 15 IG + 15 TikTok
            ig_rows = [r for r in rows[1:] if r[0] == "instagram"]
            tt_rows = [r for r in rows[1:] if r[0] == "tiktok"]
            assert len(ig_rows) == 15 and all(r[6] for r in ig_rows)
            assert len(tt_rows) == 15 and all(r[6] == "" and "|" in r[5] for r in tt_rows)
            run = json.load(open(os.path.join(out, "run.json")))
            # pinned 2025 post must be dropped
            assert run["posts"]["instagram"]
            assert all(not p["created_utc"].startswith("2025") for p in run["posts"]["instagram"][:9])
            assert "offline-test" not in rep
            assert "offline-test" not in open(os.path.join(out, "run.json")).read()
    finally:
        v.Desearch.get = orig
    print("pipeline (offline fixtures): ok")


class Stub(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers["Content-Length"])
        body = json.loads(self.rfile.read(n))
        texts = json.loads(body["messages"][1]["content"])
        labels = ["question" if "?" in t else "praise" for t in texts]
        out = json.dumps({"choices": [{"message": {"content": json.dumps(labels)}}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(out)

    def log_message(self, *a):
        pass


def test_llm_stub():
    srv = http.server.HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    c = v.LLMClassifier(f"http://127.0.0.1:{srv.server_port}/v1", "stub", "stub-model", batch=2)
    mk = lambda t: v.Comment("tiktok", "b", "p", "u", "", t, "", "", 0, 0, "a", t)
    res = c.classify([mk("how?"), mk("nice"), mk("when?")])
    assert [b for b, _ in res] == ["question", "praise", "question"], res
    bad = v.LLMClassifier("http://127.0.0.1:9/v1", "x", "m")  # nothing listens: falls back to rules
    assert bad.classify([mk("PLEASE ADD ASL")])[0][0] == "request"
    srv.shutdown()
    print("llm classifier (local stub + fallback): ok")


if __name__ == "__main__":
    test_rules(); test_pipeline_offline(); test_llm_stub()
