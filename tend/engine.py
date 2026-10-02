"""Tend rules engine.

Every event in the home updates one shared state. The rules read that state
and decide the next action. No LLM, no network: deterministic and testable.

Safety principle: the care plan (from the doctor) is the source of truth.
Tend never changes a dose. It only sequences around rules the caregiver sets.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------- clock
class SimClock:
    """A clock you can fast-forward, so a whole day can be demoed in minutes."""

    def __init__(self, start: datetime):
        self.now = start

    def advance(self, minutes: int) -> datetime:
        self.now += timedelta(minutes=minutes)
        return self.now

    def set_time(self, hhmm: str) -> datetime:
        h, m = map(int, hhmm.split(":"))
        self.now = self.now.replace(hour=h, minute=m, second=0, microsecond=0)
        return self.now


# ---------------------------------------------------------------- care plan
@dataclass
class Medication:
    id: str
    name: str
    compartment: int
    time: str  # "HH:MM"
    window_minutes: int
    with_food: bool
    diuretic: bool

    def due_at(self, day: datetime) -> datetime:
        h, m = map(int, self.time.split(":"))
        return day.replace(hour=h, minute=m, second=0, microsecond=0)


@dataclass
class CarePlan:
    patient_name: str
    caregiver_name: str
    meals: dict
    meal_counts_for_food_rule_minutes: int
    medications: list[Medication]
    thresholds: dict = field(default_factory=dict)

    def t(self, key: str):
        return self.thresholds[key]

    @classmethod
    def load(cls, path: str | Path) -> "CarePlan":
        data = json.loads(Path(path).read_text())
        meds = [Medication(**m) for m in data.pop("medications")]
        return cls(medications=meds, **data)


# ---------------------------------------------------------------- state + decisions
@dataclass
class Decision:
    action: str          # "unlock" | "keep_locked" | "remind" | "escalate" | "none"
    message: str         # what Tend says out loud to the patient
    severity: str = "routine"  # "routine" | "escalate" | "urgent"
    compartment: Optional[int] = None
    rule: str = ""       # which rule fired, for logs and tests
    caregiver: str = "none"  # "none" | "alerted" | "queued"  (set by off-duty routing)


@dataclass
class HomeState:
    locked: dict[int, bool] = field(default_factory=dict)
    held_for_food: set[str] = field(default_factory=set)
    taken: set[str] = field(default_factory=set)
    meals_logged: list[tuple[str, datetime]] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    unlocked_at: dict[int, datetime] = field(default_factory=dict)
    checkin_sent_at: Optional[datetime] = None
    checkin_reason: str = ""
    toilet_due_at: Optional[datetime] = None
    last_water: Optional[datetime] = None
    lights: dict[str, bool] = field(default_factory=lambda: {
        "bedroom": False, "hallway": False, "bathroom": False, "kitchen": False})
    fired: set[str] = field(default_factory=set)  # one-shot reminders already sent
    bathroom_since: Optional[datetime] = None
    last_activity: Optional[datetime] = None
    off_duty_from: Optional[datetime] = None
    off_duty_until: Optional[datetime] = None
    inbox: list[dict] = field(default_factory=list)    # what the caregiver's phone shows
    queue: list[dict] = field(default_factory=list)    # held until off duty ends
    handled: list[dict] = field(default_factory=list)  # done silently while off duty
    moments: list[str] = field(default_factory=list)   # nice things from her day


# ---------------------------------------------------------------- engine
class TendEngine:
    def __init__(self, plan: CarePlan, clock: SimClock):
        self.plan = plan
        self.clock = clock
        self.state = HomeState(locked={m.compartment: True for m in plan.medications})

    # Events that prove the patient is up and about.
    ACTIVITY = {"unlock", "request_denied", "held_for_food", "meal", "taken", "water",
                "checkin_reply", "motion", "heard"}

    # -- helpers
    def _log(self, kind: str, **data) -> None:
        self.state.events.append({"time": self.clock.now.isoformat(), "kind": kind, **data})
        if kind in self.ACTIVITY:
            self.state.last_activity = self.clock.now

    def _due_med(self) -> Optional[Medication]:
        """The medication whose time window is open right now and not yet taken."""
        now = self.clock.now
        for med in self.plan.medications:
            if med.id in self.state.taken:
                continue
            start = med.due_at(now)
            if start <= now <= start + timedelta(minutes=med.window_minutes):
                return med
        return None

    def _next_opening(self) -> Optional[Medication]:
        now = self.clock.now
        upcoming = [m for m in self.plan.medications
                    if m.id not in self.state.taken and m.due_at(now) > now]
        return min(upcoming, key=lambda m: m.due_at(now), default=None)

    def _ate_recently(self) -> bool:
        limit = timedelta(minutes=self.plan.meal_counts_for_food_rule_minutes)
        return any(self.clock.now - t <= limit for _, t in self.state.meals_logged)

    def _unlock(self, med: Medication, rule: str) -> Decision:
        self.state.locked[med.compartment] = False
        self.state.unlocked_at[med.compartment] = self.clock.now
        self.state.held_for_food.discard(med.id)
        self._log("unlock", compartment=med.compartment, med=med.id, rule=rule)
        return Decision("unlock",
                        f"Compartment {med.compartment} is open. It's your {med.name}.",
                        compartment=med.compartment, rule=rule)

    # -- events from the home
    def request_pills(self) -> Decision:
        """The patient asks for her pills (voice) or touches the pill box."""
        med = self._due_med()

        # Rule 3: nothing is due -> stay locked, say when it opens next.
        if med is None:
            nxt = self._next_opening()
            when = f" Your next pills are at {nxt.time}." if nxt else " No more pills today."
            self._log("request_denied", reason="not_due")
            return Decision("keep_locked", "It's not time for your pills yet." + when,
                            rule="R3_outside_window")

        # Rule 2: must be taken with food and no recent meal -> hold.
        if med.with_food and not self._ate_recently():
            self.state.held_for_food.add(med.id)
            self._log("held_for_food", med=med.id)
            return Decision("keep_locked",
                            "These pills need food first. Let's have something to eat, "
                            "then tell me and I'll open them.",
                            compartment=med.compartment, rule="R2_food_first")

        # Rule 1: due and safe -> unlock only that compartment.
        return self._unlock(med, "R1_due_unlock")

    def log_meal(self, meal: str) -> Optional[Decision]:
        """Patient says "I ate" (or the kitchen sensor confirms a meal)."""
        self.state.meals_logged.append((meal, self.clock.now))
        self._log("meal", meal=meal)
        # Rule 2 continued: a pill held for food unlocks once she has eaten.
        med = self._due_med()
        if med and med.id in self.state.held_for_food:
            return self._unlock(med, "R2_food_confirmed_unlock")
        return None

    def mark_taken(self, compartment: int) -> Decision:
        """Compartment opened and pills removed -> relock and record."""
        med = next(m for m in self.plan.medications if m.compartment == compartment)
        self.state.taken.add(med.id)
        self.state.locked[compartment] = True
        self.state.unlocked_at.pop(compartment, None)
        if self.state.checkin_reason == f"unopened:{compartment}":
            self._clear_checkin()
        # Rule 5: a diuretic means a toilet trip soon -> remind before it's urgent.
        if med.diuretic:
            self.state.toilet_due_at = self.clock.now + timedelta(
                minutes=self.plan.t("toilet_after_diuretic_minutes"))
        self._log("taken", med=med.id)
        return Decision("none", "Thank you. I've noted that.", compartment=compartment,
                        rule="taken")

    # -- more events from the home
    def log_water(self) -> None:
        self.state.last_water = self.clock.now
        self._log("water")

    def patient_replied(self) -> Decision:
        """Patient answered a check-in ("I'm fine")."""
        self._log("checkin_reply", reason=self.state.checkin_reason)
        if self.state.checkin_reason == "bathroom":
            self.state.bathroom_since = self.clock.now  # restart the timer
        self._clear_checkin()
        return Decision("none", "Good to hear. I'm here if you need me.", rule="reply")

    def motion(self, event: str) -> list[Decision]:
        """Sensor events: 'left_bed', 'back_in_bed', 'entered_bathroom', 'left_bathroom'."""
        self._log("motion", event=event)
        if event == "entered_bathroom":
            self.state.bathroom_since = self.clock.now
        elif event == "left_bathroom":
            self.state.bathroom_since = None
            if self.state.checkin_reason == "bathroom":
                self._clear_checkin()
        # Rule 8: at night, light a path from the bed to the bathroom.
        if event == "left_bed" and self._is_night():
            for room in ("bedroom", "hallway", "bathroom"):
                self.state.lights[room] = True
            return self._route([Decision("lights_on", "I've turned on the lights to the bathroom.",
                                         rule="R8_night_light_path")])
        if event == "back_in_bed" and self._is_night():
            for room in ("bedroom", "hallway", "bathroom"):
                self.state.lights[room] = False
            return self._route([Decision("lights_off", "Lights off. Sleep well.",
                                         rule="R8_lights_off")])
        return []

    # -- time-based rules, called every simulated minute
    def tick(self) -> list[Decision]:
        out: list[Decision] = []
        for rule in (self._no_reply, self._r4_unopened, self._r9_bathroom, self._r10_no_movement,
                     self._r5_toilet, self._r6_water, self._r7_meals):
            d = rule()
            if d:
                out.append(d)
        out = self._route(out)
        recap = self._r13_recap()
        if recap:
            out.append(recap)
        return out

    # -- check-ins: ask first, alert the caregiver only if there is no answer
    def _checkin(self, reason: str, message: str, rule: str, **kw) -> Decision:
        self.state.checkin_sent_at = self.clock.now
        self.state.checkin_reason = reason
        self._log("checkin", reason=reason)
        return Decision("remind", message, rule=rule, **kw)

    def _no_reply(self) -> Optional[Decision]:
        st = self.state
        if not st.checkin_sent_at:
            return None
        wait = timedelta(minutes=self.plan.t("no_reply_escalate_minutes"))
        if self.clock.now - st.checkin_sent_at < wait:
            return None
        reason, name = st.checkin_reason, self.plan.patient_name
        self._log("escalate", reason=reason)
        self._clear_checkin()
        if reason.startswith("unopened"):
            return Decision("escalate", f"{name} hasn't taken her pills and isn't answering.",
                            severity="escalate", rule="R4_no_reply_escalate")
        if reason == "bathroom":
            st.bathroom_since = None
            return Decision("escalate", f"{name} has been in the bathroom a long time and "
                            "isn't answering. Please check on her now.",
                            severity="urgent", rule="R9_bathroom_urgent")
        return Decision("escalate", f"No movement from {name} this morning and she isn't "
                        "answering. Please check on her now.",
                        severity="urgent", rule="R10_no_movement_urgent")

    def _r4_unopened(self) -> Optional[Decision]:
        now, th = self.clock.now, self.plan.thresholds
        if self.state.checkin_sent_at:
            return None  # one check-in at a time
        # Rule 4a: unlocked but not opened in time -> gentle voice check-in.
        for comp, at in self.state.unlocked_at.items():
            key = f"unopened:{comp}:{at.isoformat()}"
            if key not in self.state.fired and \
                    now - at >= timedelta(minutes=th["unopened_checkin_minutes"]):
                self.state.fired.add(key)
                return self._checkin(f"unopened:{comp}",
                                     "Your pills are ready in the box. Are you okay?",
                                     "R4_unopened_checkin", compartment=comp)
        return None

    def _r9_bathroom(self) -> Optional[Decision]:
        st = self.state
        if st.checkin_sent_at or not st.bathroom_since:
            return None
        if self.clock.now - st.bathroom_since >= timedelta(
                minutes=self.plan.t("bathroom_checkin_minutes")):
            return self._checkin("bathroom", "You've been in the bathroom a while. Are you okay?",
                                 "R9_bathroom_checkin")
        return None

    def _r10_no_movement(self) -> Optional[Decision]:
        st, th = self.state, self.plan.thresholds
        key = f"no_movement:{self.clock.now.date()}"
        if st.checkin_sent_at or key in st.fired:
            return None
        deadline = self._at(th["usual_wake_time"]) + timedelta(minutes=th["no_movement_grace_minutes"])
        today = self.clock.now.replace(hour=0, minute=0, second=0, microsecond=0)
        active_today = st.last_activity is not None and st.last_activity >= today
        if self.clock.now >= deadline and not active_today:
            st.fired.add(key)
            return self._checkin("no_movement", "Good morning. Are you awake and okay?",
                                 "R10_no_movement_checkin")
        return None

    def _r5_toilet(self) -> Optional[Decision]:
        if self.state.toilet_due_at and self.clock.now >= self.state.toilet_due_at:
            self.state.toilet_due_at = None
            self._log("remind", what="toilet")
            return Decision("remind", "It might be a good time to visit the bathroom.",
                            rule="R5_toilet_after_diuretic")
        return None

    def _r6_water(self) -> Optional[Decision]:
        th, now = self.plan.thresholds, self.clock.now
        if not (self._at(th["day_start"]) <= now < self._at(th["quiet_after"])):
            return None  # no water nudges at night: fewer toilet trips, better sleep
        evening = now >= self._at(th["evening_start"])
        interval = th["water_interval_evening_minutes" if evening else "water_interval_day_minutes"]
        since = self.state.last_water or self._at(th["day_start"])
        if now - since >= timedelta(minutes=interval):
            self.state.last_water = now  # count the nudge as the new start
            self._log("remind", what="water")
            return Decision("remind", "Time for a glass of water.", rule="R6_water")
        return None

    def _r7_meals(self) -> Optional[Decision]:
        grace = timedelta(minutes=self.plan.t("meal_grace_minutes"))
        eaten = {m for m, _ in self.state.meals_logged}
        for meal, hhmm in self.plan.meals.items():
            key = f"meal:{meal}"
            if meal in eaten or key in self.state.fired:
                continue
            if self.clock.now >= self._at(hhmm) + grace:
                self.state.fired.add(key)
                self._log("remind", what=meal)
                return Decision("remind", f"Have you had your {meal}? Let's eat something.",
                                rule="R7_meal_reminder")
        return None

    # -- Rule 11: urgent words are never delayed, even when the caregiver is off duty
    def heard(self, text: str) -> list[Decision]:
        self._log("heard", text=text)
        low = text.lower()
        if any(p in low for p in self.plan.t("urgent_phrases")):
            self._clear_checkin()
            d = Decision("escalate", f'{self.plan.patient_name} said: "{text}". '
                         "Please check on her now.", severity="urgent", rule="R11_urgent_words")
            return self._route([d])
        return []

    def note_moment(self, text: str) -> None:
        """Something nice from her day, saved for the evening recap."""
        self.state.moments.append(text)

    # -- Rule 12: off duty. Routine = handled silently, escalate = queued, urgent = breaks through
    def start_off_duty(self, until_hhmm: str) -> Decision:
        self.state.off_duty_from = self.clock.now
        self.state.off_duty_until = self._at(until_hhmm)
        self._log("off_duty", until=until_hhmm)
        return Decision("none", f"You're off duty until {until_hhmm}. I'll only interrupt "
                        "you for an emergency.", rule="R12_off_duty_start")

    def _off_duty(self) -> bool:
        u = self.state.off_duty_until
        return u is not None and self.clock.now < u

    def _route(self, decisions: list[Decision]) -> list[Decision]:
        st, stamp = self.state, self.clock.now.strftime("%H:%M")
        for d in decisions:
            item = {"time": stamp, "message": d.message, "severity": d.severity, "rule": d.rule}
            if d.severity == "urgent":
                d.caregiver = "alerted"
                st.inbox.append(item)
            elif d.severity == "escalate":
                if self._off_duty():
                    d.caregiver = "queued"
                    st.queue.append(item)
                else:
                    d.caregiver = "alerted"
                    st.inbox.append(item)
            elif self._off_duty():
                st.handled.append(item)
        return decisions

    # -- Rule 13: when off duty ends, one short recap instead of a list of chores
    def _r13_recap(self) -> Optional[Decision]:
        st = self.state
        if st.off_duty_until is None or self.clock.now < st.off_duty_until:
            return None
        text = self.build_recap()
        st.inbox.append({"time": self.clock.now.strftime("%H:%M"), "message": text,
                         "severity": "routine", "rule": "R13_recap"})
        st.off_duty_from = st.off_duty_until = None
        st.queue.clear()
        st.handled.clear()
        return Decision("recap", text, rule="R13_recap", caregiver="alerted")

    def build_recap(self) -> str:
        st, name = self.state, self.plan.patient_name
        since = st.off_duty_from or self.clock.now.replace(hour=0, minute=0)
        ev = [e for e in st.events if datetime.fromisoformat(e["time"]) >= since]
        doses = sum(e["kind"] == "taken" for e in ev)
        meals = [e["meal"] for e in ev if e["kind"] == "meal"]
        waters = sum(e["kind"] == "water" for e in ev)
        parts = [f"While you were off duty: {name} took {doses} dose{'s' if doses != 1 else ''}"]
        parts.append(f"ate {', '.join(meals)}" if meals else "no meal logged")
        parts.append(f"drank water {waters} time{'s' if waters != 1 else ''}")
        text = ", ".join(parts) + f". I handled {len(st.handled)} reminder" \
            + ("s" if len(st.handled) != 1 else "") + " for you."
        if st.queue:
            text += " Needs you: " + " ".join(q["message"] for q in st.queue)
        else:
            text += " Nothing needs you tonight."
        if st.moments:
            text += f" Something nice: {st.moments[-1]}"
        return text

    # -- helpers
    def _at(self, hhmm: str) -> datetime:
        h, m = map(int, hhmm.split(":"))
        return self.clock.now.replace(hour=h, minute=m, second=0, microsecond=0)

    def _is_night(self) -> bool:
        th, now = self.plan.thresholds, self.clock.now
        return now >= self._at(th["night_start"]) or now < self._at(th["night_end"])

    def _clear_checkin(self) -> None:
        self.state.checkin_sent_at = None
        self.state.checkin_reason = ""

    def snapshot(self) -> dict:
        return {
            "time": self.clock.now.strftime("%H:%M"),
            "locked": {str(k): v for k, v in self.state.locked.items()},
            "taken": sorted(self.state.taken),
            "held_for_food": sorted(self.state.held_for_food),
            "meals": [(m, t.strftime("%H:%M")) for m, t in self.state.meals_logged],
            "lights": self.state.lights,
            "checkin_pending": self.state.checkin_reason or None,
            "in_bathroom": self.state.bathroom_since is not None,
            "off_duty_until": self.state.off_duty_until.strftime("%H:%M")
            if self.state.off_duty_until else None,
            "caregiver_inbox": self.state.inbox[-10:],
            "queued_for_caregiver": list(self.state.queue),
            "recent_events": self.state.events[-10:],
        }
