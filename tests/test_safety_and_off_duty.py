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
    assert "took her Metformin" in msg and "ate dinner" in msg and "kittens" in msg
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


# ---- A new day starts fresh
def test_new_day_relocks_and_resets_schedule(engine):
    engine.clock.set_time("09:05")
    engine.request_pills()
    engine.mark_taken(2)
    engine.clock.set_time("09:05")      # same time -> stays today
    assert engine.request_pills().action == "keep_locked"
    engine.clock.set_time("02:00")      # earlier than now -> tomorrow
    engine.clock.set_time("09:05")
    d = engine.request_pills()
    assert d.action == "unlock" and d.compartment == 2


# ---- Pills are offered at their time, and a missed dose reaches the caregiver
def test_r1_pills_offered_at_due_time_without_asking(engine):
    engine.clock.set_time("08:50")
    fired = run(engine, 15)                       # 09:00 furosemide has no food rule
    offer = [d for d in fired if d.rule == "R1_due_time_unlock"]
    assert len(offer) == 1 and offer[0].compartment == 2
    assert engine.state.locked[2] is False


def test_r2_due_time_holds_until_she_eats(engine):
    engine.clock.set_time("19:55")
    fired = run(engine, 10)
    assert "R2_due_food_first" in rules(fired)
    assert engine.state.locked[3] is True
    d = engine.log_meal("dinner")
    assert d.action == "unlock" and d.compartment == 3


def test_r14_missed_dose_is_queued_off_duty_and_in_recap(engine):
    engine.clock.set_time("19:00")
    engine.start_off_duty("22:00")
    fired = run(engine, 181)                      # dose offered at 20:00, never taken
    missed = [d for d in fired if d.rule == "R14_missed_dose"]
    assert len(missed) == 1 and missed[0].caregiver == "queued"
    assert engine.state.locked[3] is True
    recap = [d for d in fired if d.rule == "R13_recap"][0]
    assert "Needs you" in recap.message and "missed her 20:00" in recap.message


def test_no_missed_dose_alert_for_times_that_were_skipped(engine):
    engine.clock.set_time("19:00")                # jumped past the morning doses
    assert "R14_missed_dose" not in rules(run(engine, 30))


def test_no_stale_meal_reminder_after_a_jump(engine):
    engine.clock.set_time("19:00")
    msgs = [d.message for d in run(engine, 20)]
    assert not any("lunch" in m or "breakfast" in m for m in msgs)


def test_recap_is_honest_about_what_is_still_open(engine):
    engine.clock.set_time("19:00")
    engine.start_off_duty("21:00")
    recap = [d for d in run(engine, 120) if d.rule == "R13_recap"][0]
    assert "quiet" not in recap.message
    assert "hasn't had dinner" in recap.message
    assert "20:00 Metformin 500mg hasn't been taken" in recap.message


# ---- The caregiver's week view
def test_week_counts_what_tend_handled_and_what_needed_her(engine):
    engine.clock.set_time("09:05")
    engine.request_pills()
    engine.mark_taken(2)
    engine.log_water()
    engine.heard("help")
    today = engine.week_summary()["days"][-1]
    assert today["doses_taken"] == 1 and today["doses_due"] == 3
    assert today["water"] == 1 and today["urgent"] == 1
    assert today["handled"] >= 1 and today["sample"] is False


def test_week_keeps_a_summary_of_each_finished_day(engine):
    engine.clock.set_time("09:05")
    engine.request_pills()
    engine.mark_taken(2)
    engine.clock.set_time("02:00")           # next day
    week = engine.week_summary()
    assert len(week["days"]) == 2
    assert week["days"][0]["doses_taken"] == 1 and week["days"][1]["doses_taken"] == 0
    assert week["totals"]["doses_due"] == 6


def test_missed_dose_shows_in_the_week(engine):
    engine.clock.set_time("08:55")
    run(engine, 70)                          # the 08:00 and 09:00 doses are offered, never taken
    today = engine.week_summary()["days"][-1]
    assert today["missed"] == 2 and today["needs_you"] >= 2
