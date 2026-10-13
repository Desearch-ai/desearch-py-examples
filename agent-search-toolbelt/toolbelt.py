"""Agent Search Toolbelt: a small research agent on Desearch hosted MCP (Made by Desearch, https://desearch.ai).

Default loop is scripted (no LLM): web-links-search -> extract the top links -> x-search -> answer with links.
Every tool call goes to a JSONL run log with args, latency and the cost the tool reports.
"""
import argparse, asyncio, datetime as dt, json, os, pathlib, sys, time
import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
import helpers as h

MCP_URL = os.environ.get("DESEARCH_MCP_URL", "https://mcp.desearch.ai/mcp")
TOOLS = ("web-search", "web-links-search", "extract", "x-search")  # the only tools the agent may call


class Toolbelt:
    def __init__(self, session, log_path, raw_dir=None):
        self.session, self.log_path, self.raw_dir, self.calls = session, pathlib.Path(log_path), raw_dir, []

    async def tools(self):
        listed = (await self.session.list_tools()).tools
        return [t for t in listed if t.name in TOOLS]

    async def call(self, name, args):
        if name not in TOOLS:
            raise ValueError(f"tool not allowed: {name}")
        t0 = time.perf_counter()
        res = await self.session.call_tool(name, args)
        latency = round(time.perf_counter() - t0, 3)
        data, err = h.parse_result(res), h.is_error(res)
        rec = {"ts": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "tool": name, "args": args,
               "latency_s": latency, "is_error": err, "items": 0 if err else h.count_items(data),
               **h.cost_fields(name, None if err else data, getattr(res, "meta", None))}
        self.calls.append(rec)
        if self.raw_dir:  # full tool result, for debugging (holds no key)
            h.save_raw(self.raw_dir, len(self.calls), name, args, res)
        with self.log_path.open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return data, rec


async def scripted(tb, q, top=3, links=10, x_count=10, x_days=None):
    found, rec = await tb.call("web-links-search", {"prompt": q, "tools": ["web"], "count": links})
    results = [] if rec["is_error"] else h.link_results(found)
    pages = []
    for r in results[:top]:
        for _attempt in range(2):  # one retry when a page comes back empty
            text, rec = await tb.call("extract", {"url": r["link"], "format": "text", "js": False})
            body = "" if rec["is_error"] else h.page_text(text)
            if body:
                pages.append({**r, "excerpt": h.excerpt(body, q)})
                break
    x_args = {"query": h.x_query(q), "count": x_count}
    if x_days:
        x_args |= h.date_window(x_days)
    posts, rec = await tb.call("x-search", x_args)
    return h.render_answer(q, results, pages, [] if rec["is_error"] else h.x_posts(posts), tb.calls)


async def run(q, args):
    headers = {"Authorization": f"Bearer {h.api_key()}"}
    async with httpx2.AsyncClient(headers=headers, timeout=httpx2.Timeout(30, read=180)) as http:
        async with streamable_http_client(MCP_URL, http_client=http) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tb = Toolbelt(session, args.log, args.raw)
                if args.llm:
                    import llm_loop
                    return await llm_loop.run(tb, q)
                return await scripted(tb, q, args.top, args.links, args.x_count, args.x_days)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("question")
    p.add_argument("--top", type=int, default=3, help="links to read with extract")
    p.add_argument("--links", type=int, default=10, help="web-links-search count (10-200)")
    p.add_argument("--x-count", type=int, default=10, help="x-search count")
    p.add_argument("--x-days", type=int, default=None, help="only X posts from the last N UTC days")
    p.add_argument("--log", default="run-log.jsonl", help="JSONL run log path")
    p.add_argument("--raw", default=None, help="save every raw tool result in this folder")
    p.add_argument("--out", default=None, help="write the answer Markdown here too")
    p.add_argument("--llm", action="store_true", help="optional: let an LLM pick tools (needs LLM_API_KEY)")
    a = p.parse_args(argv)
    md = asyncio.run(run(a.question, a))
    if a.out:
        pathlib.Path(a.out).write_text(md)
    print(md)


if __name__ == "__main__":
    sys.exit(main())
