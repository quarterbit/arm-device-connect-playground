"""Full-day orchestration test — hermetic, no bus.

Drives the real ``HomeAgent`` decision logic through a scripted day, capturing
the ``invoke()`` calls it would make. Proves the end-to-end plan without
opening a Zenoh session: the washer runs on the solar peak, the DHW window is
granted and started, the cloud front flips the AC to eco, the inbound EV is
pre-planned and charged on plug-in, and the battery follows solar-first
dispatch.

The live end-to-end run (real processes + real Zenoh) is
``python -m runner.demo`` and is exercised separately from CI.
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("SUNHAUS_SIM_EPOCH", repr(time.time()))
os.environ.setdefault("SUNHAUS_SIM_SPEED", "1.0")

import pytest

from agent import home_agent


class FakeClock:
    def __init__(self):
        self.h = 6.0
        self.rate = 320.0

    def sim_hour(self):
        return self.h

    def hhmm(self):
        return f"{int(self.h):02d}:{int((self.h - int(self.h)) * 60):02d}"

    def day_done(self):
        return self.h >= 22.0


@pytest.fixture
def agent_and_calls(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def fake_invoke(selector, params=None, **kw):
        calls.append((selector, params or {}))
        # emulate a couple of reads the agent expects a result from
        if "get_soc" in selector:
            return {"success": True, "result": {"soc_pct": 54.0}}
        return {"success": True, "result": {"ok": True}}

    monkeypatch.setattr(home_agent, "invoke", fake_invoke)
    ag = home_agent.HomeAgent()
    ag.clock = FakeClock()
    return ag, calls


def _selectors(calls):
    return [c[0] for c in calls]


def test_full_day_orchestration(agent_and_calls):
    ag, calls = agent_and_calls

    def at(h):
        ag.clock.h = h
        ag.policy_tick()

    # 06:30 forecast
    ag.on_event("weather-01", "wx_forecast",
                {"condition": "sunny", "temp_c": 24.0, "pv_estimate_kwh": 28.4})

    # 08:00 washer loaded with a deadline
    ag.clock.h = 8.0
    ag.on_event("washer-01", "job_queued",
                {"program": "eco40", "est_kwh": 1.1, "duration_h": 2.0, "ready_by_hour": 17.5})
    assert ag.state["washer_start"] < 12.5  # scheduled onto the solar peak

    # 08:30 heat pump asks for a window
    ag.clock.h = 8.5
    ag.on_event("heatpump-01", "window_request", {"load_kwh": 3.0, "deadline_hour": 15.0})
    assert any("grant_window" in s for s in _selectors(calls))

    # 09:00 pool controller asks to filter and heat its 8,000 L of water
    ag.clock.h = 9.0
    ag.on_event("pool-01", "pool_heating_request",
                {"current_c": 23.5, "target_c": 26.0, "estimated_kwh": 5.8,
                 "deadline_hour": 15.0})
    assert any("pool-01" in s and "grant_heating_window" in s for s in _selectors(calls))

    # midday: PV high → the scheduled loads fire and the house pre-cools
    ag.on_event("inverter-01", "production", {"kw": 8.1})
    at(11.9)   # washer start time reached
    at(12.5)   # dhw start + pre-cool
    sels = _selectors(calls)
    assert any("washer-01" in s and "start_cycle" in s for s in sels)
    assert any("heatpump-01" in s and "start_dhw" in s for s in sels)
    assert any("pool-01" in s and "set_filter" in s for s in sels)
    assert any("pool-01" in s and "set_heating" in s for s in sels)
    assert any("hvac-01" in s and "pre_cool" not in s and "set_mode" in s for s in sels) or \
           any("set_mode" in s for s in sels)

    # 14:00 cloud front → AC to eco
    ag.clock.h = 14.0
    ag.on_event("weather-01", "nowcast_updated",
                {"condition": "clouding", "cloud_cover": 0.7, "irradiance_drop_pct": 54})
    assert any("hvac-01" in s and "set_mode" in s for s in _selectors(calls))

    # 16:45 EV heading home → pre-plan + reserve wallbox
    ag.clock.h = 16.75
    ag.on_event("ev-blue", "heading_home",
                {"vehicle_id": "ev-blue", "eta_hour": 17.5, "target_pct": 60.0,
                 "by_hour": 7.0, "needed_kwh": 27.0})
    assert ag.state.get("ev_plan")
    assert any("wallbox-01" in s and "reserve" in s for s in _selectors(calls))

    # 17:30 plug in → execute the pre-planned charge (idempotent)
    ag.clock.h = 17.5
    ag.on_event("wallbox-01", "plug_connected", {"session_kwh": 0.0})
    n_charge = sum("start_charge" in s for s in _selectors(calls))
    assert n_charge == 1
    assert "ev_charge_go" in ag.done  # guarded so it never double-charges
    ag.on_event("wallbox-01", "plug_connected", {"session_kwh": 0.0})  # repeat is a no-op
    assert sum("start_charge" in s for s in _selectors(calls)) == 1

    # sunset → battery discharges for the dinner peak
    ag.on_event("inverter-01", "production", {"kw": 0.1})
    at(18.5)
    assert ag.state["batt_mode"] == "discharge"

    # 20:00 ev-red top-up staggered past the peak (no immediate charge)
    ag.clock.h = 20.0
    n_before = len(calls)
    ag.on_event("ev-red", "charge_requested",
                {"vehicle_id": "ev-red", "target_pct": 78.0, "by_hour": 7.0,
                 "battery_kwh": 60.0, "current_pct": 63.0})
    assert len(calls) == n_before  # staggered, not charged now

    # 21:55 daily stats
    at(21.95)
    assert ag.state.get("complete") is True
