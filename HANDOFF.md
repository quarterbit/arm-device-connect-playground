# HANDOFF — Arm Device Connect demo (SUNHAUS)

Running-start notes. Last updated 2026-08-18. **The demo is built and runs for real.**

## Goal

Build **SUNHAUS**, a smart-home energy demo on top of [`arm/device-connect`](https://github.com/arm/device-connect),
iterate here in this public playground, and promote it into a pull request back to Arm
as an `examples/sunhaus` contribution.

Full concept: [`sunhaus/CONCEPT.md`](sunhaus/CONCEPT.md) · How-to + what's-real: [`sunhaus/README.md`](sunhaus/README.md)
· Architecture: [`sunhaus/docs/architecture.md`](sunhaus/docs/architecture.md) · Animated storyboard:
[`sunhaus/sunhaus-demo-storyboard.html`](sunhaus/sunhaus-demo-storyboard.html).

## Repo layout

- **`arm-device-connect-playground/`** (this repo, public) — the sandbox; SUNHAUS lives in `sunhaus/`.
- **`device-connect/`** — clone of the fork [`quarterbit/device-connect`](https://github.com/quarterbit/device-connect)
  (`upstream` → `arm/device-connect`, at v0.2.5). PRs go through the fork.
- **`.venv/`** (untracked) — Python 3.12 venv at `E:\repos\device-connect\.venv` with `eclipse-zenoh`,
  `device-connect-edge`, `device-connect-agent-tools` (editable from the fork) + pytest. This is how the demo was run.

## Current state — DONE

SUNHAUS is a **real, nothing-faked** demo, verified end-to-end on this Windows box:

- ✅ 12 device drivers in `sunhaus/sunhaus/devices/` — each a real `DeviceRuntime` process
  (inverter, battery, wallbox, ev-blue/ev-red, heatpump, pool, hvac, washer, climate, weather, meter).
- ✅ Real Zenoh D2D discovery (multicast peer scouting, no broker), real `@rpc`/`@emit`/`@periodic`/`@on`.
- ✅ `agent/home_agent.py` + `agent/policies.py` — discovers the house, subscribes to `event(*)`,
  drives devices with real `invoke()`. Deterministic policy code, zero LLM tokens.
- ✅ `runner/demo.py` (launch all 13 processes, `--speed`/`--tail`) + `runner/tail.py` (live bus log).
- ✅ 20 tests pass (`pytest`): per-driver, policy, and a hermetic full-day orchestration test.
- ✅ Full 1×/3×/6× live runs succeed; captured transcript in `sunhaus/docs/sample-run-1x.txt`.
- ✅ `sunhaus/pyproject.toml` (installable; `sunhaus-demo` / `sunhaus-tail` scripts), README, architecture doc.

### Run it

```bash
cd sunhaus
# with the venv active (E:\repos\device-connect\.venv on this box):
python -m runner.demo               # 3-minute day (1x)
python -m runner.demo --speed 6x    # 30-second smoke run
python -m runner.demo --tail        # also stream the live event log
python -m pytest                    # 20 tests, no bus needed
```

## Hard-won API facts (verified against the v0.2.5 source + live runs)

- Event message on the wire is a JSON-RPC envelope: **`{"method": <event_name>, "params": <payload>, "_subject": ...}`**.
  Zenoh subjects use **`/`** separators: `device-connect/default/<device_id>/event/<event_name>`.
- **`subscribe("event(*)")` snapshots the event *names* known at subscribe time**, then listens
  `*/event/<name>` fleet-wide. → **discover the whole house BEFORE subscribing**, or you only hear
  events whose names were already known (this bit us; it's why the agent discovers, then subscribes).
- **Best-effort D2D drops one-shot events** under many local peers. Fix used: request/advertisement
  events **repeat while pending** (washer/heatpump/ev/weather), and the plug-in→charge transition is
  confirmed over **RPC** (`get_session`) not a single `plug_connected` event. Telemetry (repeated) is reliable.
- All decorated methods are `async def`; decorators are called (`@rpc()`); emit by calling the method;
  event names must match `[A-Za-z0-9_-]+`. Windows: wrap `loop.add_signal_handler` in try/except.
  `PYTHONUTF8=1` needed for upstream emoji logs. `devctl tail` does NOT exist — the tail is our own.
- Bash-tool cwd resets between calls — always `cd sunhaus` (or use absolute venv python path).

## Next steps (PR back to Arm)

1. Optional polish: M4 — feed the storyboard from live bus events over a websocket bridge
   (`runner/` + a tiny WS server publishing `subscribe("event(*)")`), so the animation is live not scripted.
   Also consider a Strands/MCP agent adapter under `agent/adapters/` to show framework-agnosticism.
2. Promote to the fork as `examples/sunhaus` on a feature branch, `git merge upstream/main` first, push,
   open PR `quarterbit/device-connect` → `arm/device-connect`. Keep AI-transcript-shaped files out of the PR
   (the sample-run txt is fine — it's real program output, not chat).
3. Before the PR, sanity-check the demo on Linux/macOS (multicast is friendlier there than Windows;
   the local-Zenoh-router fallback is documented in the README if a firewall blocks multicast).
