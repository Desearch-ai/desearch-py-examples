"""Offline tests: no network, no key. A fake MCP session stands in for the Desearch MCP server."""
import asyncio, datetime as dt, json
from types import SimpleNamespace as NS
import pytest
import helpers as h
import llm_loop
from toolbelt import TOOLS, Toolbelt, scripted


def result(payload, is_error=False):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return NS(content=[NS(type="text", text=text)], is_error=is_error, meta=None)


LINKS = {"search_results": [{"title": f"Page {i}", "link": f"https://example.org/{i}", "snippet": "tide pools"} for i in range(5)],
         "cost_usd": 0.004, "usage_count": 10}
PAGE = json.dumps("Tide pools form when the tide goes out and seawater stays in rock hollows. Other text here is long enough.")
POSTS = [{"url": "https://x.com/a/status/1", "text": "Tide pools at dawn \u2014 so calm", "created_at": "Fri Oct 09 05:00:00 +0000 2026"}]


class FakeSession:
    def __init__(self, extract_plan=None):
        self.sent, self.extract_plan = [], list(extract_plan or [])

    async def list_tools(self):
        names = ["ai-search", "web-search", "web-links-search", "extract", "x-search", "web-crawl"]
        return NS(tools=[NS(name=n, description=n, inputSchema={"type": "object"}) for n in names])

    async def call_tool(self, name, args):
        self.sent.append((name, args))
        if name == "web-links-search":
            return result(LINKS)
        if name == "extract":
            return self.extract_plan.pop(0) if self.extract_plan else result(PAGE)
        if name == "x-search":
            return result(POSTS)
        return result({"data": [], "cost_usd": 0.001})


def run(coro):
    return asyncio.run(coro)


def test_parse_result_json_string_and_plain_text():
    assert h.parse_result(result(LINKS))["cost_usd"] == 0.004
    assert h.parse_result(result(PAGE)).startswith("Tide pools form")
    assert h.parse_result(result("Extract error: HTTP 404")) == "Extract error: HTTP 404"
    assert h.parse_result(NS(content=[])) is None


def test_cost_fields_reported_estimated_and_error():
    assert h.cost_fields("web-links-search", LINKS)["cost_usd"] == 0.004
    est = h.cost_fields("extract", "some page text")
    assert est["cost_usd"] is None and est["est_cost_usd"] == h.REST_RATES["extract"]
    assert h.cost_fields("x-search", [{}] * 3)["est_cost_usd"] == pytest.approx(10 * h.REST_RATES["x-search"])
    assert h.cost_fields("x-search", [{}] * 20)["est_cost_usd"] == pytest.approx(20 * h.REST_RATES["x-search"])
    assert h.cost_fields("extract", None)["est_cost_usd"] is None
    assert h.cost_fields("extract", "x", meta={"cost_usd": 0.0005})["cost_source"] == "_meta"


def test_small_helpers():
    assert h.x_query("how do tide pools form") == "tide pools form"
    assert h.date_window(7, dt.date(2026, 10, 9)) == {"start_date": "2026-10-02", "end_date": "2026-10-10"}
    assert [r["link"] for r in h.link_results({"data": [{"title": "t", "link": "https://a"}]})] == ["https://a"]
    assert h.link_results("not a dict") == []
    assert "\u2014" not in h.clean("a \u2014 b") and h.clean("a \u2014 b") == "a - b"
    text = "Unrelated opening sentence about something else entirely. Tide pools form at low tide in rocky hollows on the shore."
    assert "low tide" in h.excerpt(text, "how do tide pools form", n=1)


def test_toolbelt_lists_only_four_tools_and_refuses_others(tmp_path):
    tb = Toolbelt(FakeSession(), tmp_path / "log.jsonl")
    assert sorted(t.name for t in run(tb.tools())) == sorted(TOOLS)
    with pytest.raises(ValueError):
        run(tb.call("ai-search", {"prompt": "x"}))


def test_scripted_loop_retries_empty_extract_once_and_logs(tmp_path, monkeypatch):
    monkeypatch.setenv("DESEARCH_API_KEY", "dsr_test_key_never_logged")
    s = FakeSession(extract_plan=[result(json.dumps("")), result(PAGE), result("Extract error: HTTP 404", True), result("Extract error: HTTP 404", True)])
    log = tmp_path / "log.jsonl"
    tb = Toolbelt(s, log, raw_dir=tmp_path / "raw")
    md = run(scripted(tb, "how do tide pools form", top=3, x_days=7))
    tools = [n for n, _ in s.sent]
    assert tools == ["web-links-search", "extract", "extract", "extract", "extract", "extract", "x-search"]
    assert all(a["js"] is False and a["format"] == "text" for n, a in s.sent if n == "extract")
    assert "start_date" in s.sent[-1][1] and "end_date" in s.sent[-1][1]
    assert "https://example.org/0" in md and "https://example.org/2" in md and "https://x.com/a/status/1" in md
    assert "\u2014" not in md
    recs = [json.loads(l) for l in log.read_text().splitlines()]
    assert len(recs) == 7 and {"ts", "tool", "args", "latency_s", "cost_usd"} <= set(recs[0])
    assert recs[0]["cost_usd"] == 0.004 and recs[3]["is_error"] is True and recs[3]["est_cost_usd"] is None
    assert "dsr_test_key_never_logged" not in log.read_text()
    assert len(list((tmp_path / "raw").iterdir())) == 7


def test_api_key_from_file(tmp_path, monkeypatch):
    monkeypatch.delenv("DESEARCH_API_KEY", raising=False)
    f = tmp_path / "k"
    f.write_text("dsr_from_file\n")
    monkeypatch.setenv("DESEARCH_API_KEY_FILE", str(f))
    assert h.api_key() == "dsr_from_file"
    monkeypatch.delenv("DESEARCH_API_KEY_FILE")
    with pytest.raises(SystemExit):
        h.api_key()


def test_llm_mode_with_stub_model(tmp_path, monkeypatch):
    for v in llm_loop.ENV:
        monkeypatch.setenv(v, "stub")
    replies = [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "1", "type": "function", "function": {"name": "extract", "arguments": json.dumps({"url": "https://example.org/0", "js": True})}},
            {"id": "2", "type": "function", "function": {"name": "web-crawl", "arguments": "{}"}}]},
        {"role": "assistant", "content": "Tide pools form at low tide. Links: https://example.org/0"},
    ]
    seen = []

    async def stub_chat(messages, tools):
        seen.append(sorted(t["function"]["name"] for t in tools))
        return replies.pop(0)

    s = FakeSession()
    md = run(llm_loop.run(Toolbelt(s, tmp_path / "log.jsonl"), "how do tide pools form", chat_fn=stub_chat))
    assert seen[0] == sorted(TOOLS)
    assert s.sent == [("extract", {"url": "https://example.org/0", "js": False})]
    assert "https://example.org/0" in md and "## Run" in md


def test_llm_mode_needs_env(tmp_path, monkeypatch):
    for v in llm_loop.ENV:
        monkeypatch.delenv(v, raising=False)
    with pytest.raises(SystemExit):
        run(llm_loop.run(Toolbelt(FakeSession(), tmp_path / "l"), "q"))
