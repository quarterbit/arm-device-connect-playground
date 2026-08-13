# SUNHAUS — a Device Connect smart-home energy demo

**One house. Ten devices. One agent. Three minutes.**

SUNHAUS is a demo built on [`arm/device-connect`](https://github.com/arm/device-connect) that shows a whole household — PV inverter, battery, wallbox, two EVs, heat pump, air conditioning, weather station, sky camera and grid meter — running as independent Device Connect devices. Each device is its own process with its own lifecycle. None of them knows about the others in advance. A home-energy agent discovers them over the Zenoh D2D bus and orchestrates a full simulated day, compressed into a 3-minute demo.

The pitch in one sentence: *plug an appliance into the network and every AI agent can immediately find it, ask it questions, and coordinate it with everything else in the house.*

Suggested repo name: `sunhaus` (alternatives: `device-connect-home-demo`, `casa-volt`).

---

## 1. Why this demo

Home energy is the ideal Device Connect showcase because the devices genuinely need to talk to *each other*, not just to a cloud dashboard. The inverter's solar forecast changes when the wallbox charges. The heat pump wants to run when the roof produces. The camera sees the car arrive before the wallbox feels the plug. Today that coordination means one proprietary integration per vendor. With Device Connect it collapses to: every appliance ships a `DeviceDriver`, and any agent — Strands, LangChain, MCP/Claude — can `discover_devices()` and `invoke_device()`.

The demo makes three claims and proves each on screen:

1. **Zero-infrastructure discovery.** All processes start in D2D mode; Zenoh multicast scouting finds the peers. No broker, no registry, no config.
2. **Devices with real lifecycles.** Devices boot, announce, publish telemetry, raise events, degrade, recover and shut down — the demo is not a slideshow of canned messages.
3. **Agent-grade orchestration.** The home agent makes visible, explainable decisions (shift the heat pump to solar peak, stagger EV charging, pre-cool before a heat wave) using only the generic agent-tools API.

## 2. Mapping onto arm/device-connect

| Demo component | device-connect package | What we use |
|---|---|---|
| Every appliance | `device-connect-edge` | `DeviceDriver` subclass per device, `DeviceRuntime` per process, `@rpc` for commands/queries, `@emit` for events, `@periodic` for telemetry loops |
| Home agent | `device-connect-agent-tools` | `connect()`, `discover_devices()`, `invoke_device()`, event subscriptions; adapters let the same house be driven from Strands, LangChain or MCP |
| Scale-up variant | `device-connect-server` | Optional: registry + router + `devctl` for the "fleet" version of the demo and for the live message-log view |
| Transport | Zenoh (default) | D2D multicast scouting for the 3-minute demo; NATS/MQTT profiles later |

Local development runs with `DEVICE_CONNECT_ALLOW_INSECURE=true`; the hardened variant (TLS/mTLS, commissioning PIN, per-device ACLs) is a roadmap milestone, not a day-one requirement.

## 3. The cast — device roster

Ten devices plus one agent. Every device is a separate Python process (`python -m sunhaus.devices.<name>` or one `docker compose up`).

| device_id | device_type | Key `@rpc` | Key `@emit` events | `@periodic` |
|---|---|---|---|---|
| `inverter-01` | `pv_inverter` | `get_production()`, `get_forecast()`, `set_export_limit(kw)` | `pv.forecast`, `pv.curtailed` | production telemetry every 5 s |
| `battery-01` | `home_battery` | `get_soc()`, `set_mode(charge\|discharge\|hold)`, `reserve(kwh)` | `soc.threshold`, `mode.changed` | SoC report every 10 s |
| `wallbox-01` | `ev_charger` | `start_charge(kw)`, `stop_charge()`, `get_session()` | `plug.connected`, `plug.disconnected`, `session.complete` | session meter every 5 s |
| `ev-blue`, `ev-red` | `electric_vehicle` | `get_soc()`, `request_charge(target_pct, by)`, `precondition(temp)` | `arrived`, `departed`, `target.reached` | SoC drift while driving |
| `heatpump-01` | `heat_pump` | `start_dhw()`, `set_setpoint(c)`, `request_window(kwh)` | `dhw.done`, `setback.entered` | tank temperature every 10 s |
| `hvac-01` | `air_conditioner` | `set_mode(cool\|eco\|off)`, `set_setpoint(c)` | `comfort.violation` | room temp every 10 s |
| `weather-01` | `weather_station` | `get_current()`, `get_forecast()` | `wx.alert`, `wx.update` | fused local + internet-feed forecast every 30 s |
| `cam-01` | `camera` | `get_snapshot()`, `detect(classes)` | `driveway.motion`, `sky.clouds` | sky-cover estimate every 20 s |
| `meter-01` | `grid_meter` | `get_power()`, `get_tariff()` | `tariff.changed`, `peak.warning` | import/export every 5 s |
| `agent-home` | *(agent, not a device)* | — consumes everything above via agent-tools | — | replans on every relevant event |

Design rule: **devices never call each other directly.** A device only answers RPCs and emits events. All cross-device intelligence lives in the agent, so swapping the agent framework (Strands ↔ LangChain ↔ Claude-via-MCP) demonstrably changes nothing on the device side.

## 4. Device lifecycles

Every driver runs the same outer lifecycle and a device-specific inner state machine. The outer lifecycle is what makes the demo feel alive — devices join and leave while everything keeps working.

```
                 ┌─────────────────────────────────────────────┐
   start ──▶ INIT ──▶ ANNOUNCE ──▶ ONLINE ⇄ DEGRADED ──▶ SHUTDOWN
                 (load state)  (zenoh     (periodic     (announce
                                scouting)  telemetry,    offline,
                                           rpc, emit)    flush)
```

Inner state machines (excerpt):

```
inverter-01:  SLEEP → RAMP_UP → PRODUCING ⇄ CURTAILED → RAMP_DOWN → SLEEP
battery-01:   IDLE → CHARGING ⇄ HOLD ⇄ DISCHARGING   (+ RESERVE guard band)
wallbox-01:   IDLE → PLUGGED → NEGOTIATING → CHARGING ⇄ PAUSED → COMPLETE
ev-*:         HOME_PLUGGED → DEPARTING → DRIVING → ARRIVING → HOME_PLUGGED
heatpump-01:  STANDBY → SCHEDULED → HEATING_DHW → STANDBY → NIGHT_SETBACK
hvac-01:      OFF → PRE_COOL → COMFORT ⇄ ECO → OFF
weather-01:   BOOT → OBSERVING (fuses mast sensors + internet feed + cam-01 sky data)
cam-01:       IDLE → DETECTING (motion / cloud events) → IDLE
```

A simulation clock (`sunhaus.simclock`) drives all inner state machines: 180 real seconds map to 06:00–22:00 sim time (1 s ≈ 5.3 min). Every device subscribes to the same clock topic, so the whole house can also run at 1× wall-clock for a soak test, or 6× for a 30-second smoke run.

## 5. The 3-minute demo script

One simulated day. Times below are demo-seconds / simulated clock. This is exactly the storyboard rendered in `sunhaus-demo-storyboard.html`.

| t | sim | Beat | On the bus |
|---|---|---|---|
| 0:00 | 06:00 | All ten processes boot; Zenoh scouting; agent discovers the full house | `discover` fan-out, announce replies |
| 0:03 | 06:30 | Weather station publishes fused forecast: sunny, 31 °C, ~28.4 kWh PV expected | `wx.forecast` |
| 0:06–0:11 | 07:00 | Inverter emits day forecast; sunrise ramp begins; battery at 35 % | `pv.forecast`, telemetry |
| 0:14 | 07:15 | Camera sees ev-blue leave; wallbox emits unplug; agent marks car AWAY | `driveway.motion`, `plug.disconnected` |
| 0:28 | 08:30 | Heat pump *asks* for a cheap 3 kWh window; agent schedules it at solar peak | `request_window` → reply `11:30–13:00` |
| 0:45 | 10:00 | Surplus flows to battery (SoC 48 %) | telemetry |
| 1:02 | 11:30 | Agent invokes `start_dhw` — hot water made from sunshine | `invoke_device` |
| 1:13 | 12:30 | Solar peak 8.1 kW; agent pre-cools house ahead of the hot afternoon | `set 22.5°C` |
| 1:30 | 14:00 | **Plot twist:** sky camera + internet nowcast agree a cloud front is inbound; inverter cuts forecast −18 %; agent flips HVAC to eco and pauses the heat pump | `sky.clouds`, `nowcast`, replan |
| 1:47 | 15:30 | Front passes; production recovers; battery reaches 88 % | `wx.update` |
| 2:09 | 17:30 | ev-blue returns (camera first, plug second); handshake: *60 % by 07:00* ; agent splits the charge: PV surplus now, off-peak remainder at 01:00 | `plug.connected`, `charge_plan` |
| 2:23 | 18:45 | Sunset; battery covers the dinner peak | `discharge` |
| 2:37 | 20:00 | ev-red requests a top-up; agent staggers it to 22:30 to cap grid peak | `request_charge`, queued |
| 2:49 | 21:00 | Heat pump night setback; house goes quiet | `setback` |
| 2:58 | 21:55 | Agent publishes daily stats: 24.1 kWh PV, 78 % self-consumption, 6.2 kWh import | `stats` |

Chaos options for live demos (each is one keypress in the runner): kill `weather-01` mid-day (agent falls back to inverter-only forecast, demonstrating graceful degradation), unplug ev-blue early, or force a tariff spike from `meter-01`.

## 6. What the audience actually sees

Three synchronized panes, all driven by the same bus traffic:

1. **The house** — the animated 2-D cutaway (`sunhaus-demo-storyboard.html`, later fed by live Zenoh events instead of the scripted timeline). Energy flows glow, message capsules travel the bus, device badges show live state.
2. **The log** — `devctl tail` style stream of every RPC and event, proving nothing is faked.
3. **The agent's mouth** — optional: the same house driven from a chat window via the MCP adapter ("Claude, make sure the blue car has 60 % by 7 am, cheapest way"), showing framework-agnosticism.

## 7. Repo structure

```
sunhaus/
├── README.md                  # this concept, distilled
├── docs/
│   ├── storyboard.html        # the animated cutaway (also the demo UI shell)
│   ├── architecture.md        # bus topology, topics, security profile
│   └── demo-script.md         # the 3-minute run sheet incl. chaos buttons
├── sunhaus/
│   ├── simclock.py            # shared simulated-day clock (1x / 60x / 360x)
│   ├── models.py              # shared dataclasses: Forecast, ChargePlan, ...
│   └── devices/
│       ├── inverter.py        # PvInverterDriver(DeviceDriver)
│       ├── battery.py
│       ├── wallbox.py
│       ├── ev.py              # parameterized: ev-blue / ev-red
│       ├── heatpump.py
│       ├── hvac.py
│       ├── weather.py         # mast sensors + internet feed fusion
│       ├── camera.py          # motion + sky-cover events
│       └── meter.py
├── agent/
│   ├── home_agent.py          # discovery, planning loop, replanning on events
│   ├── policies.py            # solar-first, peak-cap, comfort constraints
│   └── adapters/              # strands / langchain / mcp entrypoints
├── runner/
│   ├── demo.py                # launches everything, drives simclock, chaos keys
│   └── docker-compose.yml     # one container per device = honest lifecycles
└── tests/
    ├── test_drivers.py        # per-driver unit tests (no bus)
    └── test_day.py            # full 30-second 6x day, asserts the plan invariants
```

## 8. Quick start (target developer experience)

```bash
uv venv && source .venv/bin/activate
uv pip install device-connect-edge device-connect-agent-tools
git clone https://github.com/<you>/sunhaus && cd sunhaus

# terminal 1..n, or simply:
DEVICE_CONNECT_ALLOW_INSECURE=true python -m runner.demo --speed 1x
# → 10 devices boot in D2D mode, agent discovers them, the day begins
```

## 9. Milestones

| # | Milestone | Definition of done |
|---|---|---|
| M0 | Skeleton | Repo, CI (pytest on the three unit suites), simclock, one device (`inverter-01`) discoverable and invokable per the upstream quick start |
| M1 | Full cast | All ten drivers with lifecycles + telemetry; `discover_devices()` returns the complete house |
| M2 | The day | Scripted 3-minute day runs end-to-end from `runner/demo.py`; log pane matches the storyboard beats |
| M3 | Real agent | Replace the script with the planning agent; cloud-front replan and EV stagger emerge from policy, not hard-coding |
| M4 | Show floor | Storyboard HTML consumes live bus events (websocket bridge); chaos keys; MCP adapter so a chat agent can drive the house |
| M5 | Hardened | Server mode: registry + router, TLS/mTLS, commissioning PIN, per-device ACLs; same demo, production posture |

## 10. Open design questions

Topic naming convention (`home/<type>/<id>/<event>` vs. flat), whether the EVs simulate SoC drift while "driving" or simply disappear from the bus (disappearing is more honest about lifecycles and demos discovery twice), whether `meter-01` should own tariff data or the agent fetches it, and how much of the storyboard UI to keep scripted vs. live-fed for M2.

---

*License: Apache-2.0, matching upstream. Built on `arm/device-connect` v0.2.x.*
