# SUNHAUS — a Device Connect smart-home energy demo

**One house. Twelve devices. One agent. A full day in three minutes.**

SUNHAUS is a runnable demo built on [`arm/device-connect`](https://github.com/arm/device-connect).
Twelve ordinary household appliances — PV inverter, home battery, EV wallbox, two
electric cars, heat pump, air conditioner, washing machine, indoor climate sensor,
weather station, grid meter, and an 8,000 L pool with filter, heat pump, cover, and
water-temperature sensor — each run as an **independent Device Connect device
process**. None of them knows about the others in advance. A home-energy agent
discovers them over the Zenoh device-to-device bus and orchestrates a full simulated
day: laundry and hot water shifted onto the solar peak, a cloud front handled, an
EV charge planned before the car reaches the driveway, and the evening grid peak
capped — all from real bus traffic.

> **What's real:** everything in the Device Connect layer. Real `DeviceRuntime`
> processes, real Zenoh D2D discovery (multicast peer scouting, **no broker**), real
> `@rpc` commands, real `@emit` events, and an agent that uses only the public
> `device-connect-agent-tools` API (`connect` / `discover` / `invoke` / `subscribe`).
> The *hardware* is simulated (sun, temperatures, car batteries are deterministic
> physics), but the *protocol and the agent's decisions are not*. Nothing is faked.
> See [`CONCEPT.md` §2](CONCEPT.md).

---

## Run it

```bash
# from the sunhaus/ directory, in a venv with the two device-connect packages:
pip install device-connect-edge device-connect-agent-tools eclipse-zenoh
pip install -e .            # installs sunhaus + the sunhaus-demo / sunhaus-tail scripts

python -m runner.demo               # the 3-minute day (real time 1x)
python -m runner.demo --speed 6x    # 30-second smoke run
python -m runner.demo --tail        # also stream the live event log
```

`runner.demo` launches all twelve device processes plus the agent, each sharing one
simulated-day clock through the environment. What you see is the agent's decisions as
they happen; add `--tail` (or run `python -m runner.tail` in a second terminal) to
watch the raw Zenoh event stream underneath.

### What a run looks like

```
SUNHAUS — launching 12 devices + agent  (speed 1x, day ≈ 180s)
· 12 device processes booting in Zenoh D2D mode (peer scouting, no broker)…
[06:00] agent-home    discovered 12 devices over Zenoh D2D (no broker):
                  · battery-01    [home_battery]  rpc: get_soc, reserve, set_mode
                  · heatpump-01   [heat_pump]     rpc: get_state, grant_window, set_setpoint, start_dhw
                  · pool-01       [pool_system]    rpc: get_state, grant_heating_window, set_cover, set_filter
                  · … (9 more)
[06:00] agent-home    PV forecast (rpc): 68.1 kWh today, peak 8.1 kW @ 12.5h
[08:00] agent-home    washer job 'eco40' due 17.5 → scheduled 11.75 (solar peak, +3.8h vs latest)
[08:30] agent-home    heat pump wants 3.0 kWh → grant_window 11.5–13.0 (solar peak) [ok]
[09:00] agent-home    pool water 23.5°C → 26.0°C: filter + heat pump scheduled on solar [ok]
[11:30] agent-home    invoke heatpump-01.start_dhw — heating water on sunshine [ok]
[11:45] agent-home    invoke washer-01.start_cycle — laundry runs on PV surplus [ok]
[11:47] agent-home    invoke pool-01 filter + heat pump — 8,000 L pool on PV surplus [ok]
[14:00] agent-home    cloud front (own irradiance −40% + nowcast agree) → HVAC eco, heat pump paused
[16:45] agent-home    ev-blue heading home ETA 17.5, needs 21 kWh → pre-plan: PV surplus now + off-peak 01:00
[17:30] agent-home    ev-blue plugged in → start_charge 3.0 kW from pv_surplus (matches pre-plan, zero wait) [ok]
[20:00] agent-home    ev-red wants 78% by 7 → staggered to 22:30 to cap the grid peak
[21:55] agent-home    daily stats — PV 61.5 kWh · self-consumption ~78% · battery 60% · washer done early
```

Every `[ok]` is a real RPC round-trip returning success.

---

## How it works

| Layer | What it is | Real / simulated |
|---|---|---|
| **Discovery** | Zenoh D2D multicast peer scouting — no broker, no registry | **real** |
| **Commands** | `invoke("device(id).function(name)", params)` → device `@rpc` | **real** |
| **Events** | device `@emit` → agent `subscribe("event(*)")` | **real** |
| **Devices** | one `DeviceRuntime` process each, real lifecycles | **real processes**, simulated hardware |
| **Agent** | `device-connect-agent-tools`; deterministic policy code | **real**, zero LLM tokens |
| **World** | sun, clouds, temperatures, car SoC | deterministic sim (`scenario.py`) |

Design rules the demo enforces:

- **Devices never call each other** — only the agent does. Swap the agent for a
  Strands / LangChain / MCP one and nothing on the device side changes.
- **Request/grant, not push** — a device that wants something (heat pump needs a
  cheap window, washer must be done by 17:30, EV wants 60 % by 07:00) *emits a
  request*; the agent answers with an RPC. Request events repeat until served, so
  the demo is reliable over best-effort D2D pub/sub.
- **Simulator coupling flows over the real bus** — e.g. the indoor climate sensor
  cools when it *hears* the AC's `mode_changed` event (`@on`), and each EV's SoC
  rises by metering the wallbox's real session telemetry. Never through shared
  memory — exactly as real hardware gets its coupling from the real world.

See [`CONCEPT.md`](CONCEPT.md) for the full device roster, the minute-by-minute demo
script, the request/grant idiom, and the LLM token-cost analysis (if the agent's
planning were run on a public model instead of policy code).

---

## Layout

```
sunhaus/
├── sunhaus/            # the device package
│   ├── simclock.py     #   shared simulated-day clock (epoch + speed via env)
│   ├── scenario.py     #   deterministic world: sun, clouds, temps, tariff, car schedule
│   ├── models.py       #   shared payloads: SolarForecast, ChargePlan, WasherJob, HeadingHome…
│   ├── runtime.py      #   common Windows-safe device entrypoint + base driver
│   └── devices/        #   the 11 DeviceDriver subclasses
├── agent/
│   ├── home_agent.py   # discovery, event dispatch, planning loop, daily stats
│   └── policies.py     # pure decision functions (solar-first, ready-by, peak-cap)
├── runner/
│   ├── demo.py         # launch the whole house; --speed / --tail / chaos
│   └── tail.py         # live event log — subscribe("event(*)") on the real bus
└── tests/              # per-driver unit tests, agent policy tests, full-day orchestration
```

Run the tests with `pytest` (no bus needed — drivers and policies test in isolation,
and `test_day.py` drives the real agent logic through a scripted day).

---

## Windows note

Zenoh D2D uses UDP multicast, which Windows Defender Firewall may block on Public
networks. If discovery finds fewer than 12 devices, allow `python.exe` through the
firewall on Private networks, or run a local Zenoh router and point every process at
it over loopback:

```bash
docker run -p 7447:7447 eclipse/zenoh
set ZENOH_CONNECT=tcp/localhost:7447
set DEVICE_CONNECT_DISCOVERY_MODE=d2d
```

---

*License: Apache-2.0, matching upstream. Built on `arm/device-connect` v0.2.x.*
