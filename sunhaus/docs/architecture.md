# SUNHAUS architecture

## Processes

Every box below is a separate OS process. There is no shared memory and no
central coordinator — the only thing they share is a simulated-day clock
derived locally from two environment values (`SUNHAUS_SIM_EPOCH`,
`SUNHAUS_SIM_SPEED`).

```
   ┌──────────── one machine, thirteen processes ─────────────┐
   │                                                          │
   │   inverter-01   battery-01   wallbox-01   ev-blue        │
   │   ev-red        heatpump-01  hvac-01      washer-01      │
   │   climate-01    weather-01   meter-01      pool-01       │
   │        │  each is a DeviceRuntime (Zenoh peer)  │        │
   │        └──────────────┬───────────────┬─────────┘        │
   │                       │  Zenoh D2D bus │                  │
   │              (multicast scouting, no broker)             │
   │                       │               │                  │
   │                    agent-home     runner.tail            │
   │           (device-connect-agent-tools)                   │
   └──────────────────────────────────────────────────────────┘
```

## Discovery

All processes start with **no messaging URL**, which selects Zenoh D2D mode:
each opens a Zenoh peer, announces its presence, and scouts for others over
multicast + gossip. The agent calls `discover("device(*)")` and gets the whole
house back — device ids, types, and the RPC functions each exposes. No broker,
no registry, no configuration.

## Topics

Device Connect maps onto Zenoh key-expressions (the `.` in the logical subject
becomes `/` on the wire):

```
device-connect/<tenant>/<device_id>/cmd                     JSON-RPC request/reply  (invoke → @rpc)
device-connect/<tenant>/<device_id>/event/<event_name>      events                  (@emit → subscribe)
device-connect/<tenant>/<device_id>/presence                D2D presence            (discovery)
device-connect/<tenant>/discovery/probe                     D2D discovery probe
```

`subscribe("event(*)")` resolves the set of event names currently known and
listens for `*/event/<name>` across the whole fleet, so late-joining devices
are still heard.

## The request/grant idiom

Devices state needs; the agent owns the schedule. This keeps all cross-device
intelligence in one place and out of the devices.

```
heatpump-01 ──@emit window_request(3 kWh, by 15:00)──▶ agent
agent ──invoke grant_window(11:30–13:00)──▶ heatpump-01        (@rpc)
… later …
agent ──invoke start_dhw()──▶ heatpump-01                      (@rpc)
```

The same shape drives the pool (`pool_heating_request` → `grant_heating_window`
→ filter and heat), washer (`job_queued` → `start_cycle`) and EV
(`heading_home` → charge plan → `start_charge`).

**Reliability over best-effort D2D.** Zenoh D2D pub/sub is best-effort: a single
one-shot event can be dropped when many peers share one link. SUNHAUS handles
this the way a real device would — a device **keeps advertising a pending
request until it is served** (the washer re-emits `job_queued` while loaded, the
heat pump re-emits `window_request` until granted, the car re-emits
`heading_home` until it arrives). The one transition where a missed event would
be costly — the car plugging in — is confirmed over **RPC** (`get_session`,
request/reply, reliable) rather than trusting a single `plug_connected` event.

## Simulator coupling

Devices are simulators, but they interact **only over the bus**, never through
shared state — so the wiring is identical to a real deployment. Where the
physical world couples two devices, a simulator subscribes (`@on`) to the
other's *public* events:

| Coupling | Mechanism |
|---|---|
| Room cools when the AC runs | `climate-01` `@on` `hvac-01.mode_changed` |
| EV SoC rises while charging | `ev-*` `@on` `wallbox-01.session` (meters real kW) |
| Grid net power reflects PV | `meter-01` `@on` `inverter-01.production` |
| Wallbox plug follows the car | `wallbox-01` reads ev-blue's home/away schedule |

## What is real vs simulated

| Real | Simulated |
|---|---|
| `DeviceRuntime` processes, one per device | The sun, sky, outdoor and pool-water temperature |
| Zenoh D2D discovery (presence, scouting) | Each device's internal physics |
| Every `@rpc` command and its reply | Car battery chemistry, PV output curve |
| Every `@emit` event on the bus | The passage of the day (compressed clock) |
| The agent's `discover`/`invoke`/`subscribe` calls | |
| The agent's decisions and their effects | |

The protocol layer and the agent are exactly what a production deployment runs.
Only the hardware behind each driver is a simulation.
