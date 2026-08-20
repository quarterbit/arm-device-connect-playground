"""Pure decision policies for the SUNHAUS home-energy agent.

These are deterministic functions — no bus, no I/O — so they unit-test without
a running house. ``home_agent.py`` turns their outputs into real ``invoke()``
calls. This is the "intelligence" the concept promises lives in the agent, not
the devices.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Window:
    start_hour: float
    end_hour: float
    kwh: float
    reason: str


def schedule_dhw_window(load_kwh: float, deadline_hour: float,
                        peak_hour: float = 12.5) -> Window:
    """Place a DHW heating window on the solar peak, before the deadline."""
    start = min(peak_hour - 1.0, deadline_hour - 1.5)
    return Window(start_hour=round(start, 2), end_hour=round(start + 1.5, 2),
                  kwh=load_kwh, reason="solar peak")


def schedule_pool_window(load_kwh: float, deadline_hour: float,
                        heater_kw: float = 4.0, peak_hour: float = 12.5) -> Window:
    """Place pool filtration and heat-pump work around the solar peak."""
    duration_h = max(1.0, load_kwh / heater_kw)
    start = min(peak_hour - duration_h / 2, deadline_hour - duration_h)
    return Window(start_hour=round(start, 2), end_hour=round(start + duration_h, 2),
                  kwh=load_kwh, reason="solar peak")


def schedule_washer(latest_start_hour: float, peak_hour: float = 12.5) -> float:
    """Start the washer at the solar peak if that still meets the deadline,
    otherwise at the latest moment that does."""
    return round(min(peak_hour - 0.75, latest_start_hour), 2)


@dataclass
class ChargeSlot:
    start_hour: float
    end_hour: float
    kw: float
    source: str


def plan_ev_charge(needed_kwh: float, by_hour: float, arrival_hour: float,
                   pv_surplus_kw: float = 3.0, off_peak_start: float = 1.0,
                   off_peak_kw: float = 7.0) -> list[ChargeSlot]:
    """Split an EV charge: soak up PV surplus on arrival, finish off-peak.

    Returns the slots in order. Solar first (cheapest and greenest), the
    remainder shifted into the cheap overnight band before the deadline.
    """
    slots: list[ChargeSlot] = []
    remaining = needed_kwh

    # Any daylight left after arrival → charge on PV surplus.
    daylight_left = max(0.0, 20.0 - arrival_hour)
    pv_kwh = min(remaining, pv_surplus_kw * min(daylight_left, 2.0))
    if pv_kwh > 0.1:
        slots.append(ChargeSlot(start_hour=round(arrival_hour, 2),
                                 end_hour=round(arrival_hour + pv_kwh / pv_surplus_kw, 2),
                                 kw=pv_surplus_kw, source="pv_surplus"))
        remaining -= pv_kwh

    # Remainder → off-peak overnight.
    if remaining > 0.1:
        hours = remaining / off_peak_kw
        slots.append(ChargeSlot(start_hour=off_peak_start,
                                 end_hour=round(off_peak_start + hours, 2),
                                 kw=off_peak_kw, source="off_peak"))
    return slots


def stagger_topup(request_hour: float, grid_peak_end: float = 21.0) -> float:
    """Push an evening top-up past the grid peak to cap demand charges."""
    return round(max(request_hour, grid_peak_end + 1.5), 2)


def battery_mode(sim_hour: float, pv_kw: float, baseload_kw: float) -> tuple[str, float]:
    """Solar-first battery dispatch: charge on surplus, discharge at night."""
    surplus = pv_kw - baseload_kw
    if surplus > 0.3:
        return "charge", round(min(surplus, 3.0), 1)
    if sim_hour >= 18.0 or pv_kw < 0.2:
        return "discharge", 1.8
    return "hold", 0.0
