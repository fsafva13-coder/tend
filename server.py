"""Tend MCP server (Streamable HTTP, MCP spec 2025-11-25).

Run:   python server.py
Then:  connect MCP Inspector to http://127.0.0.1:8000/mcp
"""

from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from tend.engine import CarePlan, SimClock, TendEngine

PLAN_PATH = Path(__file__).parent / "care_plan.json"

plan = CarePlan.load(PLAN_PATH)
clock = SimClock(datetime.now().replace(hour=7, minute=0, second=0, microsecond=0))
engine = TendEngine(plan, clock)

mcp = FastMCP(
    "tend",
    instructions=(
        "Tend runs an elderly person's day at home: medication pill box, meals, "
        "water, toilet, night lights and safety check-ins. It never changes a dose."
    ),
)


@mcp.tool()
def get_home_state() -> dict:
    """Current simulated time, pill box locks, meals and recent events."""
    return engine.snapshot()


@mcp.tool()
def request_pills() -> dict:
    """The patient asks for her pills. Tend unlocks only if it is safe and due."""
    return asdict(engine.request_pills())


@mcp.tool()
def log_meal(meal: str) -> dict:
    """Record that the patient has eaten (e.g. 'breakfast')."""
    decision = engine.log_meal(meal)
    return asdict(decision) if decision else {"action": "none", "message": "Meal noted."}


@mcp.tool()
def mark_taken(compartment: int) -> dict:
    """Pills removed from a compartment: relock it and record the dose."""
    return asdict(engine.mark_taken(compartment))


@mcp.tool()
def log_water() -> dict:
    """Record that the patient drank water."""
    engine.log_water()
    return {"action": "none", "message": "Water noted."}


@mcp.tool()
def patient_replied() -> dict:
    """The patient answered a check-in ("I'm fine")."""
    return asdict(engine.patient_replied())


@mcp.tool()
def motion(event: str) -> list[dict]:
    """Sensor event: 'left_bed', 'back_in_bed', 'entered_bathroom' or 'left_bathroom'."""
    return [asdict(d) for d in engine.motion(event)]


@mcp.tool()
def heard(text: str) -> list[dict]:
    """Something the patient said. Urgent words ('help', 'I fell') alert the caregiver at once."""
    return [asdict(d) for d in engine.heard(text)]


@mcp.tool()
def note_moment(text: str) -> dict:
    """Save something nice from the patient's day for the caregiver's recap."""
    engine.note_moment(text)
    return {"action": "none", "message": "Saved for the recap."}


@mcp.tool()
def start_off_duty(until_hhmm: str) -> dict:
    """Caregiver goes off duty until a time like '21:00'. Only emergencies break through."""
    return asdict(engine.start_off_duty(until_hhmm))


@mcp.tool()
def get_caregiver_inbox() -> dict:
    """What the caregiver's phone shows: alerts and recaps, plus items queued while off duty."""
    return {"inbox": engine.state.inbox, "queued": engine.state.queue}


@mcp.tool()
def advance_time(minutes: int) -> dict:
    """Demo control: fast-forward the clock minute by minute, running every rule."""
    fired = []
    for _ in range(minutes):
        clock.advance(1)
        for d in engine.tick():
            fired.append({"time": clock.now.strftime("%H:%M"), **asdict(d)})
    return {"time": clock.now.strftime("%H:%M"), "decisions": fired}


@mcp.tool()
def set_time(hhmm: str) -> dict:
    """Demo control: jump the simulated clock to a time like '08:05'."""
    clock.set_time(hhmm)
    return engine.snapshot()


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
