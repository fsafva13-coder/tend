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


# ---------------------------------------------------------------- engine
class TendEngine:
    def __init__(self, plan: CarePlan, clock: SimClock):
        self.plan = plan
        self.clock = clock
        self.state = HomeState(locked={m.compartment: True for m in plan.medications})

    # -- helpers
    def _log(self, kind: str, **data) -> None:
        self.state.events.append({"time": self.clock.now.isoformat(), "kind": kind, **data})

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
        self._clear_checkin()
        return Decision("none", "Good to hear. I'm here if you need me.", rule="reply")

    def motion(self, event: str) -> list[Decision]:
        """Motion sensor events: 'left_bed', 'back_in_bed'."""
        self._log("motion", event=event)
        # Rule 8: at night, light a path from the bed to the bathroom.
        if event == "left_bed" and self._is_night():
            for room in ("bedroom", "hallway", "bathroom"):
                self.state.lights[room] = True
            return [Decision("lights_on", "I've turned on the lights to the bathroom.",
                             rule="R8_night_light_path")]
        if event == "back_in_bed" and self._is_night():
            for room in ("bedroom", "hallway", "bathroom"):
                self.state.lights[room] = False
            return [Decision("lights_off", "Lights off. Sleep well.", rule="R8_lights_off")]
        return []

    # -- time-based rules, called every simulated minute
    def tick(self) -> list[Decision]:
        out: list[Decision] = []
        for rule in (self._r4_unopened, self._r5_toilet, self._r6_water, self._r7_meals):
            d = rule()
            if d:
                out.append(d)
        return out

    def _r4_unopened(self) -> Optional[Decision]:
        now, th = self.clock.now, self.plan.thresholds
        # Rule 4b: check-in sent and no reply -> alert the caregiver.
        if self.state.checkin_sent_at and self.state.checkin_reason.startswith("unopened"):
            if now - self.state.checkin_sent_at >= timedelta(minutes=th["no_reply_escalate_minutes"]):
                self._log("escalate", reason=self.state.checkin_reason)
                self._clear_checkin()
                return Decision("escalate",
                                f"{self.plan.patient_name} hasn't taken her pills and isn't answering.",
                                severity="escalate", rule="R4_no_reply_escalate")
            return None
        # Rule 4a: unlocked but not opened in time -> gentle voice check-in.
        for comp, at in self.state.unlocked_at.items():
            if now - at >= timedelta(minutes=th["unopened_checkin_minutes"]):
                self.state.checkin_sent_at = now
                self.state.checkin_reason = f"unopened:{comp}"
                self._log("checkin", reason=self.state.checkin_reason)
                return Decision("remind", "Your pills are ready in the box. Are you okay?",
                                compartment=comp, rule="R4_unopened_checkin")
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
            "recent_events": self.state.events[-10:],
        }
