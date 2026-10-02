"""Rules 1-3: the pill box lock logic. Run with:  pytest -v"""

from datetime import datetime
from pathlib import Path

import pytest

from tend.engine import CarePlan, SimClock, TendEngine

PLAN = Path(__file__).parent.parent / "care_plan.json"


@pytest.fixture
def engine():
    clock = SimClock(datetime(2026, 10, 2, 7, 0))
    return TendEngine(CarePlan.load(PLAN), clock)


def test_everything_starts_locked(engine):
    assert all(engine.state.locked.values())


def test_r3_stays_locked_outside_window(engine):
    engine.clock.set_time("06:30")
    d = engine.request_pills()
    assert d.action == "keep_locked"
    assert d.rule == "R3_outside_window"
    assert "08:00" in d.message
    assert all(engine.state.locked.values())


def test_r2_food_first_holds_pills(engine):
    engine.clock.set_time("08:05")
    d = engine.request_pills()
    assert d.action == "keep_locked"
    assert d.rule == "R2_food_first"
    assert engine.state.locked[1] is True


def test_r2_unlocks_after_meal(engine):
    engine.clock.set_time("08:05")
    engine.request_pills()
    engine.clock.advance(15)
    d = engine.log_meal("breakfast")
    assert d is not None and d.action == "unlock"
    assert d.rule == "R2_food_confirmed_unlock"
    assert engine.state.locked[1] is False
    assert engine.state.locked[2] is True  # only the due compartment opens


def test_r1_unlocks_when_due_and_no_food_rule(engine):
    engine.clock.set_time("09:10")
    d = engine.request_pills()
    assert d.action == "unlock" and d.compartment == 2
    assert d.rule == "R1_due_unlock"


def test_r1_unlocks_with_food_if_already_ate(engine):
    engine.clock.set_time("07:40")
    engine.log_meal("breakfast")
    engine.clock.set_time("08:00")
    d = engine.request_pills()
    assert d.action == "unlock" and d.compartment == 1


def test_taken_relocks_and_is_not_reopened(engine):
    engine.clock.set_time("09:10")
    engine.request_pills()
    engine.mark_taken(2)
    assert engine.state.locked[2] is True
    d = engine.request_pills()
    assert d.action == "keep_locked"  # no double dose


def test_window_closes(engine):
    engine.clock.set_time("10:30")  # furosemide window 09:00-10:00 has passed
    d = engine.request_pills()
    assert d.action == "keep_locked"
