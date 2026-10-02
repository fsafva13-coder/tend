# Tend

> An Alexa+ agent that runs an elderly parent's day at home, so the working caregiver gets her evenings back.

**Status:** in development for the Build, Ship, Shape: Amazon Developer Hackathon (Alexa+ track). The full README comes later.

**Not a medical device.** Tend never changes a dose. It only sequences around rules set by the caregiver.

## Run it (Windows)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

pytest -v            # run the rules tests
python server.py     # start the MCP server at http://127.0.0.1:8000/mcp
```

## Try the tools

In a second terminal:

```powershell
npx @modelcontextprotocol/inspector
```

Connect with **Transport: Streamable HTTP** and **URL: http://127.0.0.1:8000/mcp**. Then:

1. `set_time` → `08:05`
2. `request_pills` → stays locked (pills need food first)
3. `log_meal` → `breakfast` → compartment 1 unlocks

## License

MIT
