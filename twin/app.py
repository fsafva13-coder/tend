"""Tend digital twin: a simulated Alexa+ home that talks to the Tend MCP server.

This small web app is an MCP *client*. Every button and every sentence becomes a
real MCP tool call over Streamable HTTP, exactly as Alexa+ would make it.

Run (in a second terminal, with server.py already running):
    python twin/app.py
Then open http://127.0.0.1:8080
"""

import json
import os
import re
from pathlib import Path

import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

MCP_URL = os.environ.get("TEND_MCP_URL", "http://127.0.0.1:8000/mcp")
HERE = Path(__file__).parent


# ------------------------------------------------------------------ MCP client
def _unwrap(result):
    """Turn an MCP tool result into plain JSON."""
    sc = getattr(result, "structuredContent", None)
    if sc is not None:
        return sc["result"] if set(sc.keys()) == {"result"} else sc
    texts = [c.text for c in result.content if getattr(c, "text", None)]
    parsed = []
    for t in texts:
        try:
            parsed.append(json.loads(t))
        except ValueError:
            parsed.append(t)
    return parsed[0] if len(parsed) == 1 else parsed


async def mcp_calls(calls: list[tuple[str, dict]]) -> dict:
    """Run tool calls in one MCP session, then read the home state."""
    log = []
    async with streamablehttp_client(MCP_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            for name, args in calls:
                res = await session.call_tool(name, args)
                log.append({"tool": name, "args": args, "result": _unwrap(res)})
            state = _unwrap(await session.call_tool("get_home_state", {}))
    return {"protocol": init.protocolVersion, "calls": log, "state": state}


# ------------------------------------------------------------------ the "agent"
def meal_for(time_hhmm: str) -> str:
    hour = int(time_hhmm.split(":")[0])
    return "breakfast" if hour < 11 else "lunch" if hour < 16 else "dinner"


URGENT_HINT = re.compile(r"help|fell|fallen|pain|breathe|bleed")


def plan_calls(text: str, time_hhmm: str) -> list[tuple[str, dict]]:
    """Turn what the patient said into MCP tool calls.

    Every sentence goes to `heard` first, so urgent words are never missed.
    The intent rules are simple on purpose; an LLM can replace this function later.
    """
    low = text.lower()
    calls: list[tuple[str, dict]] = [("heard", {"text": text})]
    if any(w in low for w in ("pill", "medicine", "medication", "tablet")):
        if any(w in low for w in ("took", "taken", "swallowed", "had my")):
            calls.append(("__take__", {}))
        else:
            calls.append(("request_pills", {}))
    elif any(w in low for w in ("ate", "eaten", "breakfast", "lunch", "dinner", "finished eating")):
        calls.append(("log_meal", {"meal": meal_for(time_hhmm)}))
    elif any(w in low for w in ("water", "drank", "drink")):
        calls.append(("log_water", {}))
    elif any(w in low for w in ("i'm fine", "im fine", "i am fine", "okay", "i'm ok", "yes")):
        calls.append(("patient_replied", {}))
    elif len(low) > 15 and "?" not in low and not URGENT_HINT.search(low):
        # Not a request: a little story from her day. Save it for the caregiver's recap.
        calls.append(("note_moment", {"text": text}))
    return calls


# ------------------------------------------------------------------ routes
async def index(_: Request):
    return FileResponse(HERE / "index.html")


async def api_state(_: Request):
    return JSONResponse(await mcp_calls([]))


async def api_tool(request: Request):
    body = await request.json()
    return JSONResponse(await mcp_calls([(body["name"], body.get("args", {}))]))


async def api_say(request: Request):
    body = await request.json()
    text = body["text"].strip()
    now = (await mcp_calls([]))["state"]
    calls = plan_calls(text, now["time"])
    # "I took my pills" -> mark the open compartment as taken
    resolved = []
    nothing_open = False
    for name, args in calls:
        if name == "__take__":
            open_ = [c for c in now["compartments"] if not c["locked"]]
            if open_:
                resolved.append(("mark_taken", {"compartment": open_[0]["compartment"]}))
            else:
                nothing_open = True
        else:
            resolved.append((name, args))
    out = await mcp_calls(resolved)
    if len(resolved) == 1:  # only `heard` ran and nothing matched
        heard = out["calls"][0]["result"]
        if not heard:
            reply = ("There's no compartment open right now, so nothing to take. "
                     "I have your pills noted." if nothing_open else
                     "I'm here. You can ask for your pills, tell me you've eaten, or say help.")
            out["calls"].append({"tool": "(no tool)", "args": {}, "result": {
                "action": "none", "message": reply}})
    return JSONResponse(out)


app = Starlette(routes=[
    Route("/", index),
    Route("/api/state", api_state),
    Route("/api/tool", api_tool, methods=["POST"]),
    Route("/api/say", api_say, methods=["POST"]),
])

if __name__ == "__main__":
    print("Tend digital twin is running. Open http://127.0.0.1:8080 in Chrome or Edge.")
    print("(Keep this terminal open. Press Ctrl+C to stop.)")
    try:
        uvicorn.run(app, host="127.0.0.1", port=8080, log_level="warning")
    except KeyboardInterrupt:
        pass
    print("Tend digital twin stopped.")
