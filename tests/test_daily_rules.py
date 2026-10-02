"""Rules 4-8: check-ins, toilet, water, meals, night lights. Run with:  pytest -v"""

from datetime import datetime
from pathlib import Path

import pytest

from tend.engine import CarePlan, SimClock, TendEngine

PLAN = Path(__file__).parent.parent / "care_plan.json"


@pytest.fixture
def engine():
    return TendEngine(CarePlan.load(PLAN), SimClock(datetime(2026, 10, 2, 7, 0)))


def run(engine, minutes):
    """Fast-forward minute by minute, collecting every decision."""
    out = []
    for _ in range(minutes):
        engine.clock.advance(1)
        out += engine.tick()
    return out


def rules(decisions):
    return [d.rule for d in decisions]


# ---- Rule 4: unlocked but not opened
def test_r4_checkin_after_20_minutes(engine):
    engine.clock.set_time("09:05")
    engine.request_pills()  # compartment 2 unlocks
    fired = run(engine, 20)
    assert "R4_unopened_checkin" in rules(fired)


def test_r4_escalates_when_no_reply(engine):
    engine.clock.set_time("09:05")
    engine.request_pills()
    fired = run(engine, 26)
    esc = [d for d in fired if d.rule == "R4_no_reply_escalate"]
    assert len(esc) == 1 and esc[0].severity == "escalate"


def test_r4_reply_cancels_escalation(engine):
    engine.clock.set_time("09:05")
    engine.request_pills()
    run(engine, 20)
    engine.patient_replied()
    engine.mark_taken(2)
    assert "R4_no_reply_escalate" not in rules(run(engine, 10))


# ---- Rule 5: toilet after diuretic
def test_r5_toilet_reminder_40_min_after_diuretic(engine):
    engine.clock.set_time("09:05")
    engine.request_pills()
    engine.mark_taken(2)  # furosemide = diuretic
    assert "R5_toilet_after_diuretic" not in rules(run(engine, 39))
    assert "R5_toilet_after_diuretic" in rules(run(engine, 1))


def test_r5_no_toilet_reminder_for_other_pills(engine):
    engine.clock.set_time("07:40")
    engine.log_meal("breakfast")
    engine.clock.set_time("08:00")
    engine.request_pills()
    engine.mark_taken(1)  # metformin, not a diuretic
    assert "R5_toilet_after_diuretic" not in rules(run(engine, 60))


# ---- Rule 6: water
def test_r6_water_every_2_hours_in_day(engine):
    engine.clock.set_time("08:00")
    engine.log_meal("breakfast")
    engine.log_meal("lunch")
    fired = [d for d in run(engine, 240) if d.rule == "R6_water"]
    assert len(fired) == 2


def test_r6_drinking_resets_the_timer(engine):
    engine.clock.set_time("09:30")
    engine.log_water()
    engine.log_meal("breakfast")
    assert "R6_water" not in rules(run(engine, 119))


def test_r6_quiet_at_night(engine):
    engine.clock.set_time("21:00")
    assert "R6_water" not in rules(run(engine, 300))


# ---- Rule 7: meals
def test_r7_meal_reminder_after_grace(engine):
    engine.clock.set_time("07:30")
    fired = run(engine, 45)
    assert rules(fired).count("R7_meal_reminder") == 1


def test_r7_no_reminder_if_eaten(engine):
    engine.clock.set_time("07:35")
    engine.log_meal("breakfast")
    assert "R7_meal_reminder" not in rules(run(engine, 60))


# ---- Rule 8: night light path
def test_r8_light_path_at_night(engine):
    engine.clock.set_time("02:00")
    d = engine.motion("left_bed")
    assert d[0].rule == "R8_night_light_path"
    assert engine.state.lights["hallway"] and engine.state.lights["bathroom"]
    engine.motion("back_in_bed")
    assert not any(engine.state.lights.values())


def test_r8_no_light_path_in_daytime(engine):
    engine.clock.set_time("14:00")
    assert engine.motion("left_bed") == []
