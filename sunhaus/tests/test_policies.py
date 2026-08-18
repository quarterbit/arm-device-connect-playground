"""Agent policy tests — pure functions, no bus.

These assert the *intelligence* of the house: solar-first scheduling, deadline
respect, EV charge splitting, peak staggering. If these hold, the agent makes
the right calls; ``test_day`` then checks they actually reach the devices.
"""

from __future__ import annotations

from agent import policies


def test_dhw_window_lands_on_solar_peak_before_deadline():
    w = policies.schedule_dhw_window(load_kwh=3.0, deadline_hour=15.0)
    assert w.start_hour < 12.5 and w.end_hour <= 15.0 and w.kwh == 3.0


def test_washer_starts_at_peak_when_deadline_allows():
    # deadline far away → start at the solar peak, not at the last minute
    assert policies.schedule_washer(latest_start_hour=15.5) < 12.5


def test_washer_respects_tight_deadline():
    # deadline forces an earlier start than the peak
    assert policies.schedule_washer(latest_start_hour=9.0) == 9.0


def test_ev_charge_is_solar_first_then_off_peak():
    slots = policies.plan_ev_charge(needed_kwh=27.0, by_hour=7.0, arrival_hour=17.5)
    assert slots[0].source == "pv_surplus"
    assert slots[-1].source == "off_peak"
    assert sum((s.end_hour - s.start_hour) * s.kw for s in slots) >= 26.0


def test_small_ev_need_uses_pv_only():
    slots = policies.plan_ev_charge(needed_kwh=4.0, by_hour=7.0, arrival_hour=17.5)
    assert all(s.source == "pv_surplus" for s in slots)


def test_topup_staggered_past_grid_peak():
    assert policies.stagger_topup(request_hour=20.0) > 21.0


def test_battery_charges_on_surplus_discharges_at_night():
    assert policies.battery_mode(12.0, pv_kw=6.0, baseload_kw=0.5)[0] == "charge"
    assert policies.battery_mode(19.0, pv_kw=0.0, baseload_kw=1.5)[0] == "discharge"
