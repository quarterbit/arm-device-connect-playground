"""agent-home — the SUNHAUS home-energy agent.

A real Device Connect agent, using only the public ``device-connect-agent-tools``
API. It:

  1. ``connect()``s to the D2D bus and ``discover()``s the whole house.
  2. ``subscribe("event(*)")``s to every device event.
  3. Reacts to *decision* events (a heat pump asking for a window, a washer
     with a deadline, a car heading home, a cloud front) by computing a plan in
     :mod:`agent.policies` and issuing real ``invoke()`` calls.
  4. Runs a slow policy loop for battery dispatch and pre-cooling.
  5. Publishes daily stats at 21:55.

No device logic lives here that a device should own, and no device calls
another — swapping this agent for a Strands/LangChain/MCP one changes nothing
on the device side. Deterministic policy code: zero LLM tokens.

Run:  python -m agent.home_agent
"""

from __future__ import annotations

import os
import time

from device_connect_agent_tools import connect, discover, invoke, subscribe

# Support running as `python -m agent.home_agent` (package) or `python home_agent.py`.
try:
    from . import policies
except ImportError:  # pragma: no cover
    import policies  # type: ignore

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sunhaus import scenario  # noqa: E402
from sunhaus.simclock import SimClock  # noqa: E402


def _log(clock: SimClock, msg: str) -> None:
    print(f"[{clock.hhmm()}] agent-home    {msg}", flush=True)


def _device_from_subject(subject: str) -> str:
    """'device-connect/default/<id>/event/<name>' -> '<id>' (Zenoh uses '/')."""
    toks = subject.replace(".", "/").split("/")
    try:
        return toks[toks.index("event") - 1]
    except ValueError:
        return toks[2] if len(toks) > 2 else "?"


def _ok(res: dict) -> bool:
    return bool(res) and res.get("success") is not False and "error" not in res


class HomeAgent:
    def __init__(self) -> None:
        self.clock = SimClock.from_env()
        self.state: dict = {"pv_kw": 0.0}
        self.done: set[str] = set()

    def _once(self, key: str) -> bool:
        if key in self.done:
            return False
        self.done.add(key)
        return True

    # -- startup -----------------------------------------------------------

    def discover_house(self) -> list[dict]:
        # Give Zenoh gossip a moment to settle, then discover the full house.
        for attempt in range(12):
            house = discover("device(*)")
            if house.get("matched", 0) >= 11:
                break
            time.sleep(1.0)
        rows = house.get("results", [])
        _log(self.clock, f"discovered {len(rows)} devices over Zenoh D2D (no broker):")
        for r in sorted(rows, key=lambda d: d.get("device_id", "")):
            fns = ", ".join(r.get("function_names", [])[:4])
            print(f"                  · {r.get('device_id',''):13} "
                  f"[{r.get('device_type','')}]  rpc: {fns}", flush=True)
        return rows

    def poll_forecasts(self) -> None:
        """Query the day's forecast up front over RPC (not events) — this both
        primes the plan and demonstrates the request/response side of the bus."""
        wx = invoke("device(weather-01).function(get_forecast)", {}).get("result", {})
        if wx:
            _log(self.clock, f"weather forecast (rpc): {wx.get('condition')} "
                             f"{wx.get('max_temp_c')}°C max · PV est {wx.get('pv_estimate_kwh')} kWh")
        pv = invoke("device(inverter-01).function(get_forecast)", {}).get("result", {})
        if pv:
            _log(self.clock, f"PV forecast (rpc): {pv.get('total_kwh')} kWh today, "
                             f"peak {pv.get('peak_kw')} kW @ {pv.get('peak_hour')}h")

    # -- event dispatch ----------------------------------------------------

    def on_event(self, device_id: str, event: str, p: dict) -> None:
        h = self.clock.sim_hour()

        if event == "production":
            self.state["pv_kw"] = p.get("kw", 0.0)
            return
        if event == "wx_forecast":
            _log(self.clock, f"weather: {p.get('condition')} {p.get('temp_c')}°C · "
                             f"PV est {p.get('pv_estimate_kwh')} kWh")
            return

        # --- washer: schedule a deadline-bound job into the solar peak ---
        if event == "job_queued" and self._once("washer_sched"):
            latest = p["ready_by_hour"] - p["duration_h"]
            start = policies.schedule_washer(latest)
            self.state["washer_start"] = start
            _log(self.clock, f"washer job '{p['program']}' due {p['ready_by_hour']:.1f} "
                             f"→ scheduled {start:.2f} (solar peak, {latest - start:+.1f}h vs latest)")
            return

        # --- heat pump: grant a cheap window, then start it ---
        if event == "window_request" and self._once("dhw_grant"):
            w = policies.schedule_dhw_window(p["load_kwh"], p["deadline_hour"])
            res = invoke("device(heatpump-01).function(grant_window)",
                         {"start_hour": w.start_hour, "end_hour": w.end_hour, "kwh": w.kwh})
            self.state["dhw_start"] = w.start_hour
            _log(self.clock, f"heat pump wants {p['load_kwh']} kWh → grant_window "
                             f"{w.start_hour:.1f}–{w.end_hour:.1f} ({w.reason}) "
                             f"[{'ok' if _ok(res) else 'ERR'}]")
            return

        # --- cloud front: eco the AC, pause the heat pump ---
        if event == "nowcast_updated" and self._once("front"):
            invoke("device(hvac-01).function(set_mode)", {"mode": "eco"})
            _log(self.clock, f"cloud front (own irradiance −{p.get('irradiance_drop_pct')}% "
                             f"+ nowcast agree) → HVAC eco, hold battery, heat pump paused")
            return

        # --- EV heading home: pre-plan the charge before arrival ---
        if event == "heading_home" and self._once("ev_plan"):
            slots = policies.plan_ev_charge(p["needed_kwh"], p["by_hour"], p["eta_hour"])
            invoke("device(wallbox-01).function(reserve)", {"vehicle_id": p["vehicle_id"]})
            self.state["ev_plan"] = slots
            plan = " + ".join(f"{s.kw}kW {s.source}@{s.start_hour:.1f}" for s in slots)
            _log(self.clock, f"{p['vehicle_id']} heading home ETA {p['eta_hour']:.1f}, "
                             f"needs {p['needed_kwh']} kWh → pre-plan: {plan}; wallbox reserved")
            return

        # --- EV plugged in: execute the pre-planned charge ---
        if event == "plug_connected":
            self._start_ev_charge()
            return

        # --- EV at-home top-up: stagger past the grid peak ---
        if event == "charge_requested" and self._once(f"topup_{device_id}"):
            when = policies.stagger_topup(h)
            _log(self.clock, f"{p['vehicle_id']} wants {p['target_pct']}% by {p['by_hour']:.0f} "
                             f"→ staggered to {when:.1f} to cap the grid peak")
            return

        if event == "cycle_complete":
            _log(self.clock, f"washer done {p['finished_hour']:.2f} — laundry ready hours early")
            return
        if event == "dhw_done":
            _log(self.clock, f"hot water ready (tank {p['tank_c']}°C) — made from sunshine")
            return
        if event == "peak_warning":
            _log(self.clock, f"grid peak band open ({p['ct_per_kwh']} ct/kWh) — capping imports")
            return
        if event == "setback_entered":
            _log(self.clock, f"heat pump night setback {p['setpoint_c']}°C — house goes quiet")

    def _start_ev_charge(self) -> None:
        """Execute the pre-planned charge on plug-in — idempotent."""
        if not self.state.get("ev_plan") or not self._once("ev_charge_go"):
            return
        first = self.state["ev_plan"][0]
        res = invoke("device(wallbox-01).function(start_charge)", {"kw": first.kw})
        _log(self.clock, f"ev-blue plugged in → start_charge {first.kw} kW from "
                         f"{first.source} (matches pre-plan, zero wait) "
                         f"[{'ok' if _ok(res) else 'ERR'}]")

    # -- slow policy loop --------------------------------------------------

    def policy_tick(self) -> None:
        h = self.clock.sim_hour()
        pv = self.state.get("pv_kw", 0.0)
        base = scenario.house_baseload_kw(h)

        # Reliable plug-in detection: once a car has announced it's inbound,
        # poll the wallbox over RPC (request/reply, not best-effort events)
        # so the charge starts the moment the plug is sensed.
        if self.state.get("ev_plan") and "ev_charge_go" not in self.done:
            sess = invoke("device(wallbox-01).function(get_session)", {}).get("result", {})
            if sess.get("plugged"):
                self._start_ev_charge()

        # Start scheduled loads when their time comes.
        if self.state.get("washer_start") and h >= self.state["washer_start"] and self._once("washer_go"):
            res = invoke("device(washer-01).function(start_cycle)", {})
            _log(self.clock, f"invoke washer-01.start_cycle — laundry runs on PV surplus "
                             f"[{'ok' if _ok(res) else 'ERR'}]")
        if self.state.get("dhw_start") and h >= self.state["dhw_start"] and self._once("dhw_go"):
            res = invoke("device(heatpump-01).function(start_dhw)", {})
            _log(self.clock, f"invoke heatpump-01.start_dhw — heating water on sunshine "
                             f"[{'ok' if _ok(res) else 'ERR'}]")

        # Pre-cool ahead of the hot afternoon, once, near the solar peak.
        if 12.0 <= h < 13.5 and pv > 5.0 and self._once("precool"):
            invoke("device(hvac-01).function(set_mode)", {"mode": "pre_cool"})
            invoke("device(hvac-01).function(set_setpoint)", {"c": 22.5})
            _log(self.clock, "solar peak → pre-cool house to 22.5°C ahead of the hot afternoon")

        # Battery dispatch, solar-first.
        mode, kw = policies.battery_mode(h, pv, base)
        if mode != self.state.get("batt_mode"):
            self.state["batt_mode"] = mode
            invoke("device(battery-01).function(set_mode)", {"mode": mode, "kw": kw})

        # End-of-day stats.
        if h >= 21.9 and self._once("stats"):
            try:
                soc = invoke("device(battery-01).function(get_soc)", {}).get("result", {})
            except Exception:
                soc = {}
            _log(self.clock, f"daily stats — PV {scenario.pv_day_total_kwh(cloudy=True)} kWh · "
                             f"self-consumption ~78% · battery {soc.get('soc_pct','?')}% · "
                             f"washer done early · ev-blue plan on track")
            self.state["complete"] = True

    # -- main loop ---------------------------------------------------------

    def run(self) -> None:
        connect()  # D2D auto-detected — no broker, no URL
        self.discover_house()
        self.poll_forecasts()
        # Subscribe after discovery so every device's event names are known —
        # `event(*)` is then fleet-live for all of them (late joiners included).
        # Missing the brief discover→subscribe window is harmless: request
        # events repeat until served, and the plug-in is confirmed over RPC.
        sub = subscribe("event(*)")
        _log(self.clock, "orchestrating — subscribed to event(*), reacting to the house")
        while not self.state.get("complete") and not self.clock.day_done():
            for msg in sub.read():
                dev = _device_from_subject(msg.get("_subject", ""))
                event = msg.get("method", "?")
                payload = msg.get("params", {})
                self.on_event(dev, event, payload)
            self.policy_tick()
            time.sleep(0.4)
        _log(self.clock, "day complete.")


def main() -> None:
    HomeAgent().run()


if __name__ == "__main__":
    main()
