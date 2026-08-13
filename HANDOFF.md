# HANDOFF — Arm Device Connect demo (SUNHAUS)

Running-start notes for continuing this work. Last updated 2026-08-13 (evening).

## Goal

Build **SUNHAUS**, a smart-home energy demo on top of [`arm/device-connect`](https://github.com/arm/device-connect),
iterate on it in this public playground, and promote the pieces worth keeping into a pull request back to Arm.

Full concept: [`sunhaus/CONCEPT.md`](sunhaus/CONCEPT.md). Animated storyboard: [`sunhaus/sunhaus-demo-storyboard.html`](sunhaus/sunhaus-demo-storyboard.html).

## Repo layout

- **`arm-device-connect-playground/`** (this repo, public) — sandbox where demos are built in the open.
- **`device-connect/`** — clone of the fork [`quarterbit/device-connect`](https://github.com/quarterbit/device-connect)
  (✅ cloned, `upstream` remote wired to `arm/device-connect`, at v0.2.5). PRs go through the fork.
- AI thinking / chat history stays in the Claude Project **"Arm Device Connect Demo"**, out of the repo.

## Current state (what changed today)

- ✅ Full **API audit of arm/device-connect v0.2.5** done (see "API facts" below — these are verified against source).
- ✅ Design revision after review: **skycam dropped** (weather station's own irradiance + internet radar nowcast
  detect the cloud front), **indoor climate sensor (`climate-01`) and washing machine (`washer-01`) added**,
  **EVs announce `heading_home`** (ETA + intended charge energy) from the road. Roster is now 11 devices + agent.
- ✅ Storyboard rewritten to the new cast: PV panel placed flush on roof pitch, washer + climate sensor drawn,
  heading_home beat, underscore event names, `subscribe("event(*)")` log header, **top-right LLM consumption
  meter** (ticks per agent decision; Sonnet $3/$15 per Mtok; "policy mode $0.00"). Visually verified in browser.
- ✅ CONCEPT.md rewritten: roster, beats, "What is real" honesty section (§2), request/grant idiom,
  LLM token-cost analysis (§8: ~420k in / 24k out per day ≈ $1.60 Sonnet uncached, $0 in policy mode).
- ✅ Foundation code exists in `sunhaus/sunhaus/`: `simclock.py` (shared epoch+speed via env, no clock topic),
  `scenario.py` (deterministic world physics), `models.py` (payload dataclasses incl. HeadingHome, WasherJob).
- ⬜ Device drivers, agent, runner, tests **not yet written** (tasks #3–#5). API facts below make this mechanical.
- ⬜ `pip install eclipse-zenoh device-connect-edge device-connect-agent-tools` not yet verified on this machine
  (Python 3.12.10 present, needs >=3.11 ✅).

## API facts (verified against the clone — build against these)

- Imports: `from device_connect_edge import DeviceRuntime`;
  `from device_connect_edge.drivers import DeviceDriver, rpc, emit, periodic, on`;
  `from device_connect_edge.types import DeviceIdentity, DeviceStatus`.
- All decorated methods **must be `async def`**; decorators are called: `@rpc()`, `@emit()`, `@periodic(interval=5.0)`,
  `@on(device_id=..., event_name=...)` (handler signature: `self, device_id, event_name, payload`).
- Emit by calling the method: `await self.pv_forecast(total_kwh=...)` — body usually `pass`. Event names: `[A-Za-z0-9_-]+` only.
- Driver → world: `await self.invoke_remote(device_id, fn, **params)` (check `"error" in result`), `await self.list_devices()`.
- Entrypoint: `DeviceRuntime(driver=..., device_id=..., allow_insecure=True)` with **no messaging_urls → Zenoh D2D**.
  Windows: `loop.add_signal_handler` raises `NotImplementedError` — wrap in try/except, poll a stop Event.
  Set `PYTHONUTF8=1` for the emoji in upstream log messages.
- Agent tools (all sync): `from device_connect_agent_tools import connect, discover, invoke, subscribe`;
  `connect()` no args in D2D; selector grammar `device(type:...)`, `invoke("device(id).function(name)", params)`;
  `subscribe("event(*)")` → `Subscription.read()/.iter()`. (`discover_devices`/`invoke_device` are deprecated aliases.)
- `devctl tail` **does not exist** — never reference it; the log tail is our own `runner/tail.py` on `subscribe("event(*)")`.
- Multicast may be firewalled on Windows → fallback: `docker run -p7447:7447 eclipse/zenoh` +
  `ZENOH_CONNECT=tcp/localhost:7447` + `DEVICE_CONNECT_DISCOVERY_MODE=d2d` on every process.
- Testing without a bus: instantiate driver, `await driver.some_rpc(...)` directly; capture events via
  `driver.set_event_callback(async_cb)`. pytest: `asyncio_mode = auto` + `pytest-asyncio>=0.23`.

## Next steps

1. Write the 11 drivers in `sunhaus/sunhaus/devices/` + `sunhaus/sunhaus/runtime.py` (common Windows-safe entrypoint)
   per CONCEPT §4/§9. Simulator coupling only via `@on` (climate←hvac, ev←wallbox, meter←everything).
2. `agent/home_agent.py` + `agent/policies.py` (sync loop: poll `Subscription.read()` ~1 Hz; solar-first windows,
   washer ready-by, EV pre-plan on `heading_home`, peak cap, battery dispatch; daily stats at 21:55).
3. `runner/demo.py` (spawn processes with shared `SUNHAUS_SIM_EPOCH`/`SUNHAUS_SIM_SPEED` env + insecure flag,
   chaos keys via msvcrt) and `runner/tail.py`; `tests/` per CONCEPT; `pyproject.toml` (deps: device-connect-edge,
   device-connect-agent-tools; installable from PyPI, else `pip install -e` the two packages in the fork clone).
4. Verify: pytest, then two-process smoke test (inverter + agent discover), then full day at 6×.
5. M4: websocket bridge feeding the storyboard from live bus events; then promote a cleaned `sunhaus/` into the fork
   as `examples/sunhaus` on branch `example/sunhaus` → PR `quarterbit/device-connect` → `arm/device-connect`
   (merge `upstream/main` first).
