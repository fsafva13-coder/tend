"""Rules 9-13: bathroom timer, no movement, urgent words, off duty, recap."""

from datetime import datetime
from pathlib import Path

import pytest

from tend.engine import CarePlan, SimClock, TendEngine

PLAN = Path(__file__).parent.parent / "care_plan.json"


@pytest.fixture
def engine():
    return TendEngine(CarePlan.load(PLAN), SimClock(datetime(2026, 10, 2, 7, 0)))


def run(engine, minutes):
    out = []
    for _ in range(minutes):
        engine.clock.advance(1)
        out += engine.tick()
    return out


def rules(decisions):
    return [d.rule for d in decisions]


# ---- Rule 9: bathroom timer
def test_r9_checkin_then_urgent(engine):
    engine.clock.set_time("14:00")
    engine.motion("entered_bathroom")
    fired = run(engine, 25)
    assert "R9_bathroom_checkin" in rules(fired)
    urgent = [d for d in run(engine, 5) if d.rule == "R9_bathroom_urgent"]
    assert len(urgent) == 1 and urgent[0].severity == "urgent"
    assert engine.state.inbox[-1]["rule"] == "R9_bathroom_urgent"


def test_r9_leaving_bathroom_cancels(engine):
    engine.clock.set_time("14:00")
    engine.motion("entered_bathroom")
    run(engine, 10)
    engine.motion("left_bathroom")
    assert not [r for r in rules(run(engine, 40)) if r.startswith("R9")]


def test_r9_reply_restarts_timer(engine):
    engine.clock.set_time("14:00")
    engine.motion("entered_bathroom")
    run(engine, 25)
    engine.patient_replied()
    assert "R9_bathroom_urgent" not in rules(run(engine, 20))


# ---- Rule 10: no movement in the morning
def test_r10_no_movement_checkin_then_urgent(engine):
    fired = run(engine, 95)  # 07:00 -> 08:35, nothing happened
    assert "R10_no_movement_checkin" in rules(fired)
    assert "R10_no_movement_urgent" in rules(fired)
    assert rules(fired).count("R10_no_movement_checkin") == 1


def test_r10_silent_if_she_is_up(engine):
    engine.clock.set_time("07:20")
    engine.log_meal("breakfast")
    assert not [r for r in rules(run(engine, 120)) if r.startswith("R10")]


# ---- Rule 11: urgent words
@pytest.mark.parametrize("phrase", ["Help!", "I fell in the kitchen", "I have chest pain"])
def test_r11_urgent_words_alert_immediately(engine, phrase):
    d = engine.heard(phrase)
    assert d[0].severity == "urgent" and d[0].caregiver == "alerted"
    assert engine.state.inbox[-1]["rule"] == "R11_urgent_words"


def test_r11_normal_speech_is_not_urgent(engine):
    assert engine.heard("The neighbour's cat had kittens") == []
    assert engine.state.inbox == []


# ---- Rule 12: off duty
def test_r12_routine_is_silent_and_escalate_is_queued(engine):
    engine.clock.set_time("19:45")
    engine.log_meal("dinner")
    engine.clock.set_time("20:00")
    engine.start_off_duty("22:00")
    engine.request_pills()  # compartment 3 unlocks, never opened
    fired = run(engine, 30)
    esc = [d for d in fired if d.rule == "R4_no_reply_escalate"]
    assert esc and esc[0].caregiver == "queued"
    assert engine.state.inbox == []           # phone stayed quiet
    assert len(engine.state.queue) == 1
    assert len(engine.state.handled) >= 1     # the check-in was handled silently


def test_r12_urgent_breaks_through_off_duty(engine):
    engine.clock.set_time("20:00")
    engine.start_off_duty("22:00")
    d = engine.heard("help")
    assert d[0].caregiver == "alerted"
    assert engine.state.inbox[-1]["severity"] == "urgent"


def test_r12_escalate_goes_straight_through_when_on_duty(engine):
    engine.clock.set_time("09:05")
    engine.request_pills()
    esc = [d for d in run(engine, 30) if d.rule == "R4_no_reply_escalate"]
    assert esc[0].caregiver == "alerted"


# ---- Rule 13: recap
def test_r13_recap_when_off_duty_ends(engine):
    engine.clock.set_time("19:00")
    engine.start_off_duty("21:00")
    engine.clock.set_time("19:40")
    engine.log_meal("dinner")
    engine.log_water()
    engine.clock.set_time("20:00")
    engine.request_pills()
    engine.mark_taken(3)
    engine.note_moment("She laughed about the neighbour's kittens.")
    fired = run(engine, 61)
    recap = [d for d in fired if d.rule == "R13_recap"]
    assert len(recap) == 1
    msg = recap[0].message
    assert "1 dose" in msg and "dinner" in msg and "kittens" in msg
    assert "Nothing needs you" in msg
    assert engine.state.off_duty_until is None


def test_r13_recap_lists_what_needs_the_caregiver(engine):
    engine.clock.set_time("19:45")
    engine.log_meal("dinner")
    engine.clock.set_time("20:00")
    engine.start_off_duty("21:00")
    engine.request_pills()
    fired = run(engine, 61)
    recap = [d for d in fired if d.rule == "R13_recap"][0]
    assert "Needs you" in recap.message and "pills" in recap.message
