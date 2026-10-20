# Tend

**An Alexa+ agent that runs an elderly parent's day at home, so the working caregiver gets her evenings back.**

![Track](https://img.shields.io/badge/Hackathon-Alexa%2B%20track-B76E79)
![MCP](https://img.shields.io/badge/MCP-2025--11--25%20·%20Streamable%20HTTP-3B2A3F)
![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB)
![Tests](https://img.shields.io/badge/tests-44%20passing-5F8068)
![License](https://img.shields.io/badge/license-MIT-blue)

> Built for the **Build, Ship, Shape: Amazon Developer Hackathon** (Alexa+ track). All code was written during the submission period.

---

## Overview

People who care for an aging parent while holding a job spend their evenings on logistics: pills, meals, water, the bathroom, checking in. Smart pill boxes, reminder apps and fall alarms exist, but each works alone, and every one of them is built to watch the parent.

**Tend connects every signal in the home and acts on them together.** It keeps the pill box locked until she has eaten, expects a bathroom trip after a water pill, lights the way at night, and checks in before it alarms anyone. The caregiver taps **Off duty**, and Tend handles the routine silently, holds what can wait, and breaks through only for a real emergency.

The result is a parent who never has to wait for help, and a caregiver whose phone stays quiet unless it matters.

**Tend is not a medical device.** The care plan is the source of truth. Tend never changes a dose; it only sequences around rules the caregiver sets.

---

## Features

**For the parent (voice-first, through Alexa+)**

- **Pills at the right time, not before.** Each compartment unlocks only in its time window. Outside it, the box stays locked and Tend says when it opens next.
- **Food-first doses.** A pill marked "with food" is held until a meal is confirmed, then unlocks on its own.
- **Cross-signal reminders.** A water pill triggers a bathroom reminder 40 minutes later. Water reminders taper off in the evening so sleep isn't broken.
- **Night light path.** Getting out of bed at night lights the bedroom, hallway and bathroom, and turns them off when she is back in bed.
- **Check in before alarming.** Unopened pills, a long bathroom visit or a silent morning lead to a gentle voice check-in first.

**For the caregiver**

- **Off duty mode.** Routine events are handled silently, non-urgent problems are held, urgent ones always get through.
- **Missed-dose alert.** An offered dose that isn't taken relocks the box and is reported.
- **One recap, not a list of chores.** When off duty ends: what she ate and took, what still needs attention, and one nice moment from her day.
- **A week at a glance.** Doses taken, what Tend handled itself, what needed her and how many urgent alerts, with a bar per day.
- **Urgent words never wait.** "Help", "I fell" or "chest pain" alert the caregiver immediately, off duty or not.

**For developers**

- **A real MCP server** with 15 tools over Streamable HTTP (spec 2025-11-25).
- **A deterministic rules engine**, with every rule covered by tests. No LLM in the safety path.
- **A digital twin home** that makes every MCP call visible as it happens.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Agent protocol | Model Context Protocol, spec **2025-11-25**, Streamable HTTP |
| MCP server | Python, official MCP Python SDK (`mcp>=1.30,<2`) |
| Rules engine | Pure Python, dataclasses, simulated clock |
| Twin backend (MCP client) | Starlette + Uvicorn |
| Twin front end | HTML, CSS, vanilla JavaScript, inline SVG |
| Voice | Web Speech API (speech recognition + synthesis) |
| Tests | pytest (44 tests) |

---

## Screenshots

**Morning: pills are due, but she hasn't eaten. The box stays locked.**

![Pill box held until she eats](docs/screenshots/01-morning-food-first.png)

**She says "I ate". The compartment unlocks on its own.**

![Compartment unlocked after a meal](docs/screenshots/02-compartment-unlocked.png)

**Evening: the caregiver was off duty. She gets one recap.**

![Evening recap on the caregiver's phone](docs/screenshots/03-evening-recap.png)

**Night: lights guide her to the bathroom. No reply to the check-in, so the alert breaks through.**

![Night light path and urgent alert](docs/screenshots/04-night-urgent-alert.png)

> **Demo video (under 3 minutes):** [https://youtu.be/iJUlLaYF9cc](https://youtu.be/iJUlLaYF9cc)
>
> [![Watch the Tend demo](https://img.youtube.com/vi/iJUlLaYF9cc/hqdefault.jpg)](https://youtu.be/iJUlLaYF9cc)

---

## Architecture

```mermaid
flowchart TD
    A["Parent's Alexa+<br/>voice in, voice out"] -->|what she says| B
    H["Digital twin home<br/>pill box, lights, sensors"] -->|events| B
    P["Caregiver's phone<br/>alerts, off duty, recap"] <-->|alerts and off duty| B
    B["Twin backend<br/>MCP client"] <-->|MCP 2025-11-25, Streamable HTTP| S["Tend MCP server<br/>15 tools"]
    S --> E["Rules engine<br/>14 tested rules"]
    E <--> C["Care plan + home state<br/>care_plan.json"]
```

Every button press and every sentence in the twin becomes a real MCP tool call. The server passes it to the rules engine, which reads the care plan and the home state and returns one decision: unlock, keep locked, remind, light, or escalate.

Because Alexa+ speaks MCP, the same server can drive real Alexa-compatible devices in place of the simulated ones.

### From simulation to a real home

Tend uses no cameras. In the twin, buttons stand in for sensors; in a real home the same signals come from small Alexa-compatible devices. Motion and door sensors tell Tend which room she is in and for how long, without recording anyone in her bedroom or bathroom.

| In the twin | In a real home |
|---|---|
| "Gets out of bed" / "Back in bed" | Bed pressure pad or bedroom motion sensor |
| "Enters / Leaves bathroom" | Motion sensor plus a door contact sensor |
| "Goes to kitchen" | Motion sensor |
| Pill box compartments | Smart pill dispenser with a lock and a lid sensor |
| Rooms lighting up | Smart bulbs or smart plugs |
| Caregiver's phone panel | Phone notifications (see Future Improvements) |

The MCP tools stay the same; only the source of the events changes.

### The rules

| # | Situation | What Tend does | Severity |
|---|---|---|---|
| 1 | Dose is due, no food rule | Unlocks that compartment only | Routine |
| 2 | Dose is due, "with food", no meal yet | Keeps it locked, unlocks when she has eaten | Routine |
| 3 | Pills requested outside any window | Stays locked, says when it opens next | Routine |
| 4 | Unlocked but not opened in 20 min | Voice check-in, then tells the caregiver | Escalate |
| 5 | Diuretic taken | Bathroom reminder 40 min later | Routine |
| 6 | 2 hours without water (day) | Water reminder; fewer in the evening, none at night | Routine |
| 7 | Mealtime passed, no meal | One meal reminder | Routine |
| 8 | Out of bed at night | Lights a path to the bathroom | Routine |
| 9 | In the bathroom over 25 min | Voice check-in, then an urgent alert | Urgent |
| 10 | No sign of activity in the morning | Voice check-in, then an urgent alert | Urgent |
| 11 | "Help", "I fell", "chest pain" | Urgent alert at once | Urgent |
| 12 | Caregiver off duty | Routine silent, escalations held, urgent breaks through | Mode |
| 13 | Off duty ends | One recap | Recap |
| 14 | Offered dose not taken in its window | Relocks the box, tells the caregiver | Escalate |

Every timing lives in `care_plan.json`, not in code.

---

## Installation

Requires Python 3.11 or newer. Tested on Windows 11 with Python 3.14.

```powershell
git clone https://github.com/fsafva13-coder/tend.git
cd tend
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
```

Check that everything works:

```powershell
python -m pytest -v             # 44 passed
```

---

## Usage

**One command starts everything:**

```powershell
python run.py
```

This starts the MCP server and the digital twin, opens `http://127.0.0.1:8080` in your browser, and stops both when you press Ctrl+C. On Windows you can also double-click **`start.bat`**.

<details>
<summary>Prefer to run the two programs separately?</summary>

Use two terminals, both with the virtual environment activated.

```powershell
python server.py                # Terminal 1: MCP server at http://127.0.0.1:8000/mcp
python twin/app.py              # Terminal 2: twin at http://127.0.0.1:8080
```

</details>

Open the page in Chrome or Edge (needed for voice).

### A two-minute walkthrough

1. Press **Play**. At 08:00 Tend offers the morning pills but holds them: she must eat first.
2. Say or tap **I ate**. Compartment 1 unlocks. Tap it to take the pills.
3. **Evening** → **Go off duty** → **The neighbour's cat had kittens!** → **+1 hour** → **I ate** → tap the compartment → **+1 hour**. The caregiver gets one calm recap.
4. **Reset day** and repeat step 3 without eating. The dose is missed, the box relocks, and the caregiver is told.
5. **Night** → **Gets out of bed** → **Enters bathroom** → **+15 min** twice. The lights come on, Tend checks in, and the urgent alert breaks through.

### Calling the tools directly

```powershell
npx @modelcontextprotocol/inspector
```

Connect with **Streamable HTTP** to `http://127.0.0.1:8000/mcp`.

| Tool | Purpose |
|---|---|
| `get_home_state` | Clock, pill box, lights, caregiver inbox |
| `request_pills` | Parent asks for her pills |
| `log_meal`, `log_water` | Record a meal or a drink |
| `mark_taken` | Pills removed from a compartment |
| `motion` | Bed and bathroom sensor events |
| `heard` | Anything the parent says; urgent words alert at once |
| `patient_replied` | Answer to a check-in |
| `note_moment` | Save a nice moment for the recap |
| `start_off_duty` | Caregiver goes off duty until a time |
| `get_caregiver_inbox` | Alerts, recaps and held items |
| `get_week_summary` | The caregiver's week: doses, handled by Tend, needed her, urgent |
| `advance_time`, `set_time`, `reset_day` | Demo clock controls |

---

## Project Structure

```
tend/
├── run.py                     # One command: starts everything, opens the page
├── start.bat                  # Windows: double-click to start
├── server.py                  # MCP server: 15 tools over Streamable HTTP
├── care_plan.json             # Medications, meal times and every threshold
├── tend/
│   └── engine.py              # Rules engine, home state, simulated clock
├── twin/
│   ├── app.py                 # Twin backend: an MCP client + intent parser
│   └── index.html             # Digital twin home (floor plan, pill box, phone)
├── tests/
│   ├── test_pillbox.py        # Rules 1-3
│   ├── test_daily_rules.py    # Rules 4-8
│   └── test_safety_and_off_duty.py   # Rules 9-14, recap, day rollover
├── docs/screenshots/
├── FRICTION_LOG.md            # Developer-experience notes for the hackathon
├── requirements.txt
└── LICENSE
```

---

## Results

| Measure | Value |
|---|---|
| Rules implemented | 14 |
| Automated tests | 44, all passing |
| MCP tools | 15 |
| MCP protocol negotiated | 2025-11-25 over Streamable HTTP |
| External services required | None; runs fully on one laptop |
| Cost to run | Zero |

The week view on the caregiver's side counts these as they happen. Its earlier days are **sample data** (marked as such in the app and in the tool's output); only today's column is live.

In the walkthrough above, a calm evening produces **one** notification for the caregiver (the recap) while Tend handles the reminders itself. Urgent words reach her at once, even when she is off duty.

---

## Challenges & Learnings

- **Overlapping dose windows.** At exactly 09:00 the 08:00 window and the 09:00 window are both open. Tend offers one dose at a time and holds the later one until the earlier is resolved, which is the safe order.
- **A recap that sounded fine when it wasn't.** An early version said "a quiet evening" while dinner and a dose were still outstanding. The recap now lists anything still open under "Needs you" before it says anything reassuring.
- **Silent missed doses.** At first the box only opened when asked, so a dose nobody requested simply vanished. Tend now offers each dose at its time and reports any that are missed.
- **Time jumps in a demo.** Skipping the clock forward produced stale reminders ("have you had lunch?" at 19:00). Reminders now expire, and a dose is only reported as missed if Tend actually offered it.
- **MCP SDK versions.** `pip install mcp` installs 2.x, where `FastMCP` was renamed and a newer protocol is negotiated. Pinning `mcp>=1.30,<2` gives exactly spec 2025-11-25. See `FRICTION_LOG.md`.
- **"Ate" versus "eight".** Browser speech recognition returned "8" for "I ate". The twin now reads several recognition candidates and picks the one that makes sense.

---

## Future Improvements

- Replace the keyword intent parser with an LLM, keeping the rules engine as the only decision-maker.
- Smarter urgent-word detection: "that was helpful" currently matches "help". A false alarm is the safer failure, but it should be rare.
- Real devices: Alexa-compatible smart lock pill dispenser, lights and motion sensors in place of the simulation.
- Deliver caregiver alerts to a real phone: Alexa app notifications first, text messages for urgent alerts, then a small companion app with the Off duty button and recap.
- Build the week view from stored history. Today's column is live; the six earlier days are sample data seeded for the demo.
- Several caregivers with a handover between them.
- Caregiver-editable care plan in the app instead of a JSON file.

---

## Demo

- **Video:** [https://youtu.be/iJUlLaYF9cc](https://youtu.be/iJUlLaYF9cc)
- **Run it yourself:** follow [Installation](#installation) and [Usage](#usage); it takes about two minutes.

---

## License

MIT. See [LICENSE](LICENSE).

Built by [Fathima Safva](https://github.com/fsafva13-coder).
