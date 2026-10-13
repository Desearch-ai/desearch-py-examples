"""Optional LLM mode for toolbelt.py (off by default; run with --llm).

The model picks among the same four Desearch MCP tools. Needs three env vars:
LLM_API_KEY, LLM_BASE_URL (an endpoint that speaks the common chat-completions
JSON shape with tool calling) and LLM_MODEL. Extract always runs with js=false.
"""
import json, os
import httpx2
import helpers as h

SYSTEM = ("You are a research assistant. Use the tools to find sources, read the best pages with extract, "
          "and answer briefly. End with a list of every link you used.")
ENV = ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL")


def tool_specs(tools):
    return [{"type": "function", "function": {"name": t.name, "description": t.description or "",
                                              "parameters": t.inputSchema}} for t in tools]


async def chat(messages, tools):
    url = os.environ["LLM_BASE_URL"].rstrip("/") + "/chat/completions"
    async with httpx2.AsyncClient(timeout=120) as c:
        r = await c.post(url, headers={"Authorization": f"Bearer {os.environ['LLM_API_KEY']}"},
                         json={"model": os.environ["LLM_MODEL"], "messages": messages, "tools": tools})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]


async def run(tb, q, max_steps=8, chat_fn=chat):
    missing = [v for v in ENV if not os.environ.get(v)]
    if missing:
        raise SystemExit(f"--llm needs {', '.join(missing)}; without them use the default scripted loop")
    tools = tool_specs(await tb.tools())
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": q}]
    for _ in range(max_steps):
        msg = await chat_fn(messages, tools)
        messages.append(msg)
        if not msg.get("tool_calls"):
            return f"# {q}\n\n{msg.get('content') or ''}\n" + h.run_footer(tb.calls)
        for call in msg["tool_calls"]:
            name, args = call["function"]["name"], json.loads(call["function"].get("arguments") or "{}")
            if name == "extract":
                args["js"] = False
            try:
                data, rec = await tb.call(name, args)
                out = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
            except ValueError as e:
                out = str(e)
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": out[:20000]})
    return f"# {q}\n\nStopped after {max_steps} steps without a final answer.\n" + h.run_footer(tb.calls)
