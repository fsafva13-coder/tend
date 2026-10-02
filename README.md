# Tend

> An Alexa+ agent that runs an elderly parent's day at home, so the working caregiver gets her evenings back.

**Status:** in development for the Build, Ship, Shape: Amazon Developer Hackathon (Alexa+ track). The full README comes later.

**Not a medical device.** Tend never changes a dose. It only sequences around rules set by the caregiver.

## Run it (Windows)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python -m pytest -v  # run the rules tests
python server.py     # start the MCP server at http://127.0.0.1:8000/mcp
```

## Open the digital twin home

With `python server.py` still running, open a second terminal:

```powershell
.venv\Scripts\activate
python twin/app.py
```

Then open **http://127.0.0.1:8080** in Chrome or Edge. Every button and sentence is a real MCP tool call (shown in the log at the bottom).

A quick story to try:

1. Click **+1 hour**. At 08:00 Tend offers the morning pills itself, but holds them: she must eat first
2. **I ate** → compartment 1 unlocks → tap the green compartment (or say **I took my pills**)
3. **Evening** → **Go off duty** → **The neighbour's cat had kittens!** → **+1 hour** (Tend reminds her about dinner and holds the 20:00 pills) → **I ate** → tap the compartment → **+1 hour** → Sara gets one calm recap
4. Try step 3 again without eating: the dose is missed, the box relocks, and the recap tells Sara
5. **Night** → **Gets out of bed** (lights come on) → **Enters bathroom** → **+15 min** twice → urgent alert

## Inspect the raw MCP tools

```powershell
npx @modelcontextprotocol/inspector
```

Connect with **Transport: Streamable HTTP** and **URL: http://127.0.0.1:8000/mcp**.

## License

MIT
