# Friction Log

One entry per problem you hit. Submitting these can earn up to a 10% judging bonus.

## Template

- **Date:**
- **Task attempted:**
- **Steps taken:**
- **Expected:**
- **Actual:**
- **Severity:** Critical / Major / Minor
- **Workaround:**
- **Suggestion for Amazon:**

## Entries

### 1. Python MCP SDK 2.x breaks FastMCP imports

- **Date:** 2026-10-02
- **Task attempted:** Start a self-hosted MCP server (Streamable HTTP) built with the official Python SDK.
- **Steps taken:** `pip install mcp`, then `python server.py` with `from mcp.server.fastmcp import FastMCP`, as most tutorials and samples show.
- **Expected:** The server starts and negotiates MCP spec 2025-11-25.
- **Actual:** pip installed mcp 2.2.0, where FastMCP was renamed to MCPServer. The server crashed on import with `ModuleNotFoundError: No module named 'mcp.server.fastmcp'`. SDK 2.x also negotiates a newer protocol version than the 2025-11-25 named in the hackathon rules.
- **Severity:** Major (blocks first run; cost about an hour).
- **Workaround:** Pinned `mcp>=1.30,<2` in requirements.txt. SDK 1.30 negotiates exactly 2025-11-25.
- **Suggestion for Amazon:** In the Alexa+ resources, state which SDK major version matches spec 2025-11-25, and whether later protocol versions are accepted. A pinned starter sample (like the Fire TV and Ring hello-world repos) would remove the guesswork.

### 2. Windows blocks pip-installed tool launchers

- **Date:** 2026-10-02
- **Task attempted:** Run the test suite with `pytest -v` in a Python virtual environment on Windows 11.
- **Steps taken:** Activated the venv, ran `pytest -v`.
- **Expected:** Tests run.
- **Actual:** Windows Security (Application Control) blocked `pytest.exe` because the launcher is unsigned: "An Application Control policy has blocked this file". It had worked the previous day.
- **Severity:** Minor (confusing, intermittent).
- **Workaround:** Run tools through the signed interpreter: `python -m pytest -v`.
- **Suggestion for Amazon:** Setup guides for Windows should use the `python -m <tool>` form for all commands, since pip-generated launchers can be blocked on new Windows 11 machines.
