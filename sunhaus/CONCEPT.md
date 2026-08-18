# SUNHAUS — a Device Connect smart-home energy demo

**One house. Eleven devices. One agent. Three minutes.**

SUNHAUS is a demo built on [`arm/device-connect`](https://github.com/arm/device-connect) that shows a whole household — PV inverter, battery, wallbox, two EVs, heat pump, air conditioning, washing machine, indoor climate sensor, weather station and grid meter — running as independent Device Connect devices. Each device is its own process with its own lifecycle. None of them knows about the others in advance. A home-energy agent discovers them over the Zenoh D2D bus and orchestrates a full simulated day, compressed into a 3-minute demo.

The pitch in one sentence: *plug an appliance into the network and every AI agent can immediately find it, ask it questions, and coordinate it with everything else in the house.*

---

## 1. Why this demo

Home energy is the ideal Device Connect showcase because the devices genuinely need to talk to *each other*, not just to a cloud dashboard. The inverter's solar forecast changes when the wallbox charges. The heat pump wants to run when the roof produces. The car announces from the road that it is heading home before the wallbox ever feels the plug. The washing machine is loaded in the morning and just needs to be done before anyone returns. Today that coordination means one proprietary integration per vendor. With Device Connect it collapses to: every appliance ships a `DeviceDriver`, and any agent — Strands, LangChain, MCP/Claude — can `discover()` and `invoke()`.

The demo makes three claims and proves each on screen:

1. **Zero-infrastructure discovery.** All processes start in D2D mode; Zenoh multicast scouting finds the peers. No broker, no registry, no config.
2. **Devices with real lifecycles.** Devices boot, announce, publish telemetry, raise events, degrade, recover and shut down — the demo is not a slideshow of canned messages.
3. **Agent-grade orchestration.** The home agent makes visible, explainable decisions (shift the washer and heat pump to solar peak, plan the EV charge before the car arrives, stagger loads to cap the grid peak) using only the generic agent-tools API.

## 2. What is real and what is simulated

Honesty rules for this demo, so nobody has to ask:

- **The Device Connect layer is 100% real.** Every device is a real `DeviceRuntime` process; discovery is real Zenoh D2D presence (multicast scouting, no broker); every command is a real `@rpc` invocation; every event is a real `@emit` on the bus; the agent uses only the public `device-connect-agent-tools` API (`connect()`, `discover()`, `invoke()`, `subscribe()`). The log pane shows genuine bus traffic from `subscribe("event(*)")`.
- **The hardware is simulated.** Sun, clouds, temperatures and car batteries are deterministic physics functions of the simulated clock (`sunhaus/scenario.py`). Devices are simulators of real appliances — but they interact *only* over the bus, never through shared memory. Where the physical world couples devices (the room cools because the AC runs), a simulator subscribes to the other device's *public* events to stay consistent — real hardware would get that coupling from the real air.
- **The storyboard HTML is scripted** (milestone M2 replaces its timeline with live bus events over a websocket bridge). Until M4 lands, treat it as an animated storyboard, not a live view.
- **No LLM required.** Device Connect is transport + discovery — zero tokens. The default `agent-home` is deterministic policy code ($0.00/day). The optional MCP/Strands adapter mode drives the same house from an LLM; the storyboard's consumption meter shows what that would cost (see §8).

## 3. Mapping onto arm/device-connect

| Demo component | device-connect package | What we use |
|---|---|---|
| Every appliance | `device-connect-edge` | `DeviceDriver` subclass per device, `DeviceRuntime` per process, `@rpc` for commands/queries, `@emit` for events, `@periodic` for telemetry loops, `@on` for event subscriptions |
| Home agent | `device-connect-agent-tools` | `connect()`, `discover()`, `invoke()`, `subscribe()`; adapters let the same house be driven from Strands, LangChain or MCP |
| Scale-up variant | `device-connect-server` | Optional: registry + router + `devctl` for the "fleet" version of the demo |
| Transport | Zenoh (default) | D2D multicast scouting for the 3-minute demo; NATS/MQTT profiles later |

Local development runs with `DEVICE_CONNECT_ALLOW_INSECURE=true`; the hardened variant (TLS/mTLS, commissioning PIN, per-device ACLs) is a roadmap milestone, not a day-one requirement. Event names follow the upstream constraint `[A-Za-z0-9_-]` — so `pv_forecast`, not `pv.forecast`.

## 4. The cast — device roster

Eleven devices plus one agent. Every device is a separate Python process (`python -m sunhaus.devices.<name>` or one `docker compose up`). Deliberately ordinary appliances — the point is that *normal* household gear benefits from a common device bus.

| device_id | device_type | Key `@rpc` | Key `@emit` events | `@periodic` |
|---|---|---|---|---|
| `inverter-01` | `pv_inverter` | `get_production()`, `get_forecast()`, `set_export_limit(kw)` | `pv_forecast`, `pv_curtailed` | production telemetry every 5 s |
| `battery-01` | `home_battery` | `get_soc()`, `set_mode(charge\|discharge\|hold, kw)`, `reserve(kwh)` | `soc_threshold`, `mode_changed` | SoC report every 10 s |
| `wallbox-01` | `ev_charger` | `start_charge(kw)`, `stop_charge()`, `get_session()` | `plug_connected`, `plug_disconnected`, `session_complete` | session meter every 5 s |
| `ev-blue`, `ev-red` | `electric_vehicle` | `get_soc()`, `request_charge(target_pct, by_hour)`, `precondition(temp_c)` | `departed`, **`heading_home`** (ETA + energy it intends to charge, sent from the road via telematics), `arrived`, `target_reached` | SoC drift while driving |
| `heatpump-01` | `heat_pump` | `start_dhw()`, `set_setpoint(c)`, `grant_window(start, end, kwh)` | `window_request`, `dhw_done`, `setback_entered` | tank temperature every 10 s |
| `hvac-01` | `air_conditioner` | `set_mode(cool\|eco\|off)`, `set_setpoint(c)` | `mode_changed`, `comfort_violation` | power telemetry every 10 s |
| `washer-01` | `washing_machine` | `get_job()`, `start_cycle()` | `job_queued` (program, est. kWh, **ready_by** deadline set by the owner), `cycle_started`, `cycle_complete` | cycle meter while running |
| `climate-01` | `climate_sensor` | `get_climate()` | `comfort_alert` | indoor temp/humidity every 10 s |
| `weather-01` | `weather_station` | `get_current()`, `get_forecast()` | `wx_forecast`, `nowcast_updated` (own irradiance sensor + internet radar nowcast), `wx_update` | outdoor observations every 30 s |
| `meter-01` | `grid_meter` | `get_power()`, `get_tariff()` | `tariff_changed`, `peak_warning` | import/export every 5 s |
| `agent-home` | *(agent, not a device)* | — consumes everything above via agent-tools | — | replans on every relevant event |

Design rules:

- **Devices never call each other directly.** A device only answers RPCs and emits events. All cross-device intelligence lives in the agent, so swapping the agent framework (Strands ↔ LangChain ↔ Claude-via-MCP) demonstrably changes nothing on the device side.
- **Request/grant over push.** A device that wants something (heat pump needs 3 kWh, EV wants 60% by 07:00, washer must be done by 17:30) *emits a request event*; the agent answers with an RPC (`grant_window`, `start_cycle`, a charge plan). This is the natural Device Connect idiom — devices state needs, the agent owns the schedule.
- **Simulator coupling only via public bus traffic.** e.g. `climate-01`'s room model subscribes (`@on`) to `hvac-01`'s `mode_changed`; `ev-blue`'s SoC rises by listening to `wallbox-01` session telemetry.

Natural extensions (same pattern, deliberately left out of the 3-minute cut): dishwasher and tumble dryer (identical "ready-by" jobs), robot vacuum ("clean while nobody is home, on solar"), smart blinds ("shade before cooling harder"), DHW/water heater as separate device, smart plugs for dumb loads.

## 5. Device lifecycles

Every driver runs the same outer lifecycle and a device-specific inner state machine. The outer lifecycle is what makes the demo feel alive — devices join and leave while everything keeps working.

```
                 ┌─────────────────────────────────────────────┐
   start ──▶ INIT ──▶ ANNOUNCE ──▶ ONLINE ⇄ DEGRADED ──▶ SHUTDOWN
                 (load state)  (zenoh     (periodic     (announce
                                presence)  telemetry,    departing,
                                           rpc, emit)    flush)
```

Inner state machines (excerpt):

```
inverter-01:  SLEEP → RAMP_UP → PRODUCING ⇄ CURTAILED → RAMP_DOWN → SLEEP
battery-01:   IDLE → CHARGING ⇄ HOLD ⇄ DISCHARGING   (+ RESERVE guard band)
wallbox-01:   IDLE → PLUGGED → NEGOTIATING → CHARGING ⇄ PAUSED → COMPLETE
ev-*:         HOME_PLUGGED → DEPARTING → DRIVING → HEADING_HOME → ARRIVING → HOME_PLUGGED
washer-01:    IDLE → LOADED → QUEUED → RUNNING → DONE
heatpump-01:  STANDBY → SCHEDULED → HEATING_DHW → STANDBY → NIGHT_SETBACK
hvac-01:      OFF → PRE_COOL → COMFORT ⇄ ECO → OFF
climate-01:   BOOT → OBSERVING (room model follows outdoor temp + hvac events)
weather-01:   BOOT → OBSERVING (own sensors fused with internet forecast/nowcast)
```

A simulation clock (`sunhaus.simclock`) drives all inner state machines: 180 real seconds map to 06:00–22:00 sim time (1 s ≈ 5.3 min). All processes derive sim time from a shared epoch + speed in the environment — no clock topic, no coordinator. The whole house can also run at wall-clock for a soak test, or 6× faster (30 s) for a smoke run.

## 6. The 3-minute demo script

One simulated day. Times below are demo-seconds / simulated clock. This is exactly the storyboard rendered in `sunhaus-demo-storyboard.html`.

| t | sim | Beat | On the bus |
|---|---|---|---|
| 0:00 | 06:00 | All eleven processes boot; Zenoh presence; agent discovers the full house | `discover` fan-out, presence replies |
| 0:03 | 06:30 | Weather station publishes forecast: sunny, 31 °C, ~28.4 kWh PV expected | `wx_forecast` |
| 0:06–0:11 | 07:00 | Inverter emits day forecast; sunrise ramp begins; battery at 35 % | `pv_forecast`, telemetry |
| 0:14 | 07:15 | ev-blue departs (telematics link to the bus stays up); wallbox emits unplug | `departed`, `plug_disconnected` |
| 0:22 | 08:00 | Washer loaded before the owner leaves: *eco 40°, ready by 17:30* — agent schedules it into the solar peak (11:45, done 13:45, 3¾ h margin) | `job_queued` → reply |
| 0:28 | 08:30 | Heat pump *asks* for a cheap 3 kWh window; agent grants 11:30–13:00 | `window_request` → `grant_window` |
| 0:45 | 10:00 | Surplus flows to battery (SoC 48 %) | telemetry |
| 1:02 | 11:30 | Agent invokes `start_dhw` — hot water made from sunshine | `invoke` |
| 1:05 | 11:45 | Agent invokes `start_cycle` — laundry runs on PV surplus | `invoke` |
| 1:13 | 12:30 | Solar peak 8.1 kW; agent pre-cools house ahead of the hot afternoon; indoor sensor confirms | `set 22.5°C`, climate telemetry |
| 1:27 | 13:45 | Washer done — hours before anyone is home | `cycle_complete` |
| 1:30 | 14:00 | **Plot twist:** weather station's own irradiance drop + internet radar nowcast agree a cloud front is inbound; inverter cuts forecast −18 %; agent flips HVAC to eco and pauses the heat pump | `nowcast_updated`, `pv_forecast` rev 2, replan |
| 1:47 | 15:30 | Front passes; production recovers; battery reaches 88 % | `wx_update` |
| 2:01 | 16:45 | **ev-blue announces itself from the road:** ETA 17:30, wants 60 % by 07:00 (≈27 kWh); agent pre-plans the charge and reserves the wallbox *before the car arrives* | `heading_home`, reserve |
| 2:09–2:13 | 17:30 | ev-blue arrives, plugs in; handshake matches the pre-plan — zero wait: PV surplus now, off-peak remainder at 01:00 | `arrived`, `plug_connected`, charge plan |
| 2:23 | 18:45 | Sunset; battery covers the dinner peak | `discharge` |
| 2:37 | 20:00 | ev-red requests a top-up; agent staggers it to 22:30 to cap grid peak | `request_charge`, queued |
| 2:49 | 21:00 | Heat pump night setback; house goes quiet | `setback` |
| 2:58 | 21:55 | Agent publishes daily stats: 24.1 kWh PV, 78 % self-consumption, 6.2 kWh import, laundry done 13:45 | `stats` |

Chaos options for live demos (each is one keypress in the runner): kill `weather-01` mid-day (agent falls back to inverter-only forecast, demonstrating graceful degradation), have ev-blue's process leave the bus while driving and rejoin on arrival (demos discovery twice), or force a tariff spike from `meter-01`.

## 7. What the audience actually sees

Three synchronized panes, all driven by the same bus traffic:

1. **The house** — the animated 2-D cutaway (`sunhaus-demo-storyboard.html`, later fed by live Zenoh events instead of the scripted timeline). Energy flows glow, message capsules travel the bus, device badges show live state, and the top-right meter tracks hypothetical LLM cost (§8).
2. **The log** — a `subscribe("event(*)")` tail of every RPC and event, proving nothing is faked.
3. **The agent's mouth** — optional: the same house driven from a chat window via the MCP adapter ("Claude, make sure the blue car has 60 % by 7 am, cheapest way"), showing framework-agnosticism.

## 8. Does the agent burn LLM tokens?

Device Connect itself: **no**. Discovery, RPC and events are plain Zenoh messages — zero tokens, regardless of how many devices chat all day.

Tokens enter only if `agent-home`'s *planning* runs on an LLM, and a production integration keeps that remarkably cheap:

1. **The LLM writes the policy; the policy runs the house.** The ~15 decisions on a SUNHAUS day are arithmetic against known preferences — deadlines, tariffs, forecasts — which is exactly what `agent/policies.py` encodes. The natural place for a big model is one level up: it *authors and re-tunes* those rules (when a new device joins, the tariff changes, or at a weekly review) and the rules then execute all day at $0.00. The LLM is a compiler, not the control loop.
2. **When the LLM is consulted, it's one cached call.** The stable prefix — system prompt, tool schemas, the discovered device roster — is byte-identical every time, so it prompt-caches (cache reads are ~10× cheaper). The fresh tokens are just the triggering event plus current state (~a few hundred), and the reply is one structured decision (~250 tokens).
3. **A small model is enough.** "Fit 3 kWh of DHW inside 11:30–13:00" is not frontier reasoning — a Haiku-class model handles it, and the Batch API halves anything that isn't latency-critical (daily summary, weekly re-tune).
4. **Or no cloud at all.** Run a small model on the home gateway itself — this is Arm hardware, after all. Zero cloud tokens; you pay in local silicon and milliwatts.

| Architecture (per home, per day) | Tokens/day (in / out) | Cost/day |
|---|---|---|
| **Policy mode (this demo)** — LLM only re-tunes the rules ~weekly | ~12k / 1k amortized | **$0.00 runtime · ~1–2¢ amortized** |
| \+ chat front-end ("60 % by 7 am, cheapest way" — a handful of asks) | ~40k / 2k, mostly cached | ~2–5¢ |
| LLM decides *every* beat (1 cached Haiku-class call × ~15 decisions) | ~62k / 4k | **~8¢** (Sonnet-class: ~25¢) |
| Small model on the Arm gateway | 0 cloud tokens | $0 cloud |

So even a *fully* LLM-driven house runs on the order of **$1–3 per month**, and the sensible hybrid is **effectively $0** — cost is not the reason to prefer policy code; determinism and latency are. The same math scales calmly to fleets (100 000 homes ≈ $8k/day fully LLM-driven, ≈ $0 in policy mode), which is why the LLM belongs one level up, tuning policies. The storyboard's top-right meter ticks the built-right cost live as the day's decisions fire.

## 9. Repo structure

```
sunhaus/
├── README.md                  # this concept, distilled
├── docs/
│   ├── storyboard.html        # the animated cutaway (also the demo UI shell)
│   ├── architecture.md        # bus topology, topics, security profile
│   └── demo-script.md         # the 3-minute run sheet incl. chaos buttons
├── sunhaus/
│   ├── simclock.py            # shared simulated-day clock (epoch+speed via env)
│   ├── scenario.py            # deterministic world: sun, clouds, temps, car schedule
│   ├── models.py              # shared dataclasses: SolarForecast, ChargePlan, WasherJob, ...
│   ├── runtime.py             # common device-process entrypoint (Windows-safe)
│   └── devices/
│       ├── inverter.py        # PvInverterDriver(DeviceDriver)
│       ├── battery.py
│       ├── wallbox.py
│       ├── ev.py              # parameterized: ev-blue / ev-red (heading_home!)
│       ├── heatpump.py
│       ├── hvac.py
│       ├── washer.py          # ready-by job scheduling
│       ├── climate.py         # indoor climate sensor
│       ├── weather.py         # outdoor sensors + internet forecast/nowcast
│       └── meter.py
├── agent/
│   ├── home_agent.py          # discovery, planning loop, replanning on events
│   ├── policies.py            # solar-first, ready-by deadlines, peak-cap, comfort
│   └── adapters/              # strands / langchain / mcp entrypoints
├── runner/
│   ├── demo.py                # launches everything, drives simclock, chaos keys
│   ├── tail.py                # live message log (subscribe("event(*)"))
│   └── docker-compose.yml     # one container per device = honest lifecycles
└── tests/
    ├── test_drivers.py        # per-driver unit tests (no bus)
    └── test_day.py            # full 30-second 6x day, asserts the plan invariants
```

## 10. Quick start (target developer experience)

```bash
uv venv && source .venv/bin/activate
uv pip install device-connect-edge device-connect-agent-tools
git clone https://github.com/<you>/sunhaus && cd sunhaus

# terminal 1..n, or simply:
DEVICE_CONNECT_ALLOW_INSECURE=true python -m runner.demo --speed 1x
# → 11 devices boot in D2D mode, agent discovers them, the day begins
```

On Windows, if multicast scouting is blocked by the firewall, run a local Zenoh router (`docker run -p7447:7447 eclipse/zenoh`) and set `ZENOH_CONNECT=tcp/localhost:7447` + `DEVICE_CONNECT_DISCOVERY_MODE=d2d` — same presence-based discovery, loopback transport.

## 11. Milestones

| # | Milestone | Definition of done |
|---|---|---|
| M0 | Skeleton | Repo, CI (pytest on the unit suites), simclock + scenario, one device (`inverter-01`) discoverable and invokable per the upstream quick start |
| M1 | Full cast | All eleven drivers with lifecycles + telemetry; `discover()` returns the complete house |
| M2 | The day | Scripted 3-minute day runs end-to-end from `runner/demo.py`; log pane matches the storyboard beats |
| M3 | Real agent | Replace the script with the planning agent; cloud-front replan, washer ready-by scheduling and EV pre-planning emerge from policy, not hard-coding |
| M4 | Show floor | Storyboard HTML consumes live bus events (websocket bridge); chaos keys; MCP adapter so a chat agent can drive the house |
| M5 | Hardened | Server mode: registry + router, TLS/mTLS, commissioning PIN, per-device ACLs; same demo, production posture |

## 12. Open design questions

Whether `meter-01` owns tariff data or the agent fetches it; how much of the storyboard UI to keep scripted vs live-fed for M2; whether the chaos "EV leaves the bus while driving" should become the default (more honest about lifecycles, demos discovery twice) instead of the always-connected telematics link.

---

*License: Apache-2.0, matching upstream. Built on `arm/device-connect` v0.2.x.*
