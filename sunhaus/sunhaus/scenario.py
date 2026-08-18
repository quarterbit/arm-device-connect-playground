"""The physical world SUNHAUS devices live in.

Devices never talk to each other directly — but they inhabit the same house
under the same sky. This module is that sky: deterministic functions of
simulated time that each device process evaluates locally. The weather
station *measures* :func:`cloud_cover`, the camera *sees* it, and the
inverter's production *follows* it, so their bus traffic is consistent
without any hidden channel between them.

Everything is a pure function of the simulated hour (06:00-22:00), so runs
are reproducible and unit-testable without a bus.
"""

from __future__ import annotations

import math

# -- headline numbers (mirrored in the storyboard) --------------------------

PV_KWP = 9.6  # roof array size
PV_PEAK_KW = 8.1  # what actually shows at solar peak on the demo day
BATTERY_KWH = 12.0
WALLBOX_MAX_KW = 11.0

# The one plot twist of the day: a cloud front passes in the afternoon.
CLOUD_FRONT_START = 14.0
CLOUD_FRONT_PEAK = 14.6
CLOUD_FRONT_END = 15.5
CLOUD_FRONT_COVER = 0.72

# EV timetable
EV_BLUE_DEPARTS = 7.25  # 07:15
EV_BLUE_ANNOUNCES = 16.75  # 16:45 — heading_home over telematics, before arrival
EV_BLUE_RETURNS = 17.5  # 17:30
EV_RED_REQUESTS = 20.0  # asks for a top-up in the evening

# Washer: loaded before the owner leaves, must be done before they return
WASHER_LOADED = 8.0  # 08:00
WASHER_READY_BY = 17.5  # 17:30
WASHER_EST_KWH = 1.1
WASHER_DURATION_H = 2.0  # eco40 cycle


def _bump(hour: float, start: float, peak: float, end: float) -> float:
    """Piecewise-linear 0→1→0 bump used for the cloud front."""
    if hour <= start or hour >= end:
        return 0.0
    if hour <= peak:
        return (hour - start) / (peak - start)
    return (end - hour) / (end - peak)


def cloud_cover(sim_hour: float) -> float:
    """Fraction of sky covered, 0.0-1.0. Sunny day, one afternoon front."""
    base = 0.05
    front = CLOUD_FRONT_COVER * _bump(
        sim_hour, CLOUD_FRONT_START, CLOUD_FRONT_PEAK, CLOUD_FRONT_END
    )
    return min(1.0, base + front)


def clear_sky_pv_kw(sim_hour: float) -> float:
    """Clear-sky PV output: half-sine between 06:30 and 20:30, peak 12:30."""
    sunrise, sunset = 6.5, 20.5
    if sim_hour <= sunrise or sim_hour >= sunset:
        return 0.0
    x = (sim_hour - sunrise) / (sunset - sunrise)
    return PV_PEAK_KW / 0.95 * math.sin(math.pi * x) ** 1.4


def pv_kw(sim_hour: float) -> float:
    """Actual PV output after clouds."""
    return round(clear_sky_pv_kw(sim_hour) * (1.0 - 0.85 * cloud_cover(sim_hour)), 2)


def pv_day_total_kwh(cloudy: bool = True, step_h: float = 0.05) -> float:
    """Integrate the day's production (the 28.4→24.1 kWh forecast/actual)."""
    f = pv_kw if cloudy else clear_sky_pv_kw
    hours = int((22.0 - 6.0) / step_h)
    return round(sum(f(6.0 + i * step_h) for i in range(hours)) * step_h, 1)


def outdoor_temp_c(sim_hour: float) -> float:
    """Outdoor temperature: 19 °C at dawn rising to 31 °C mid-afternoon."""
    t = 25.0 + 6.0 * math.sin((sim_hour - 9.0) / 12.0 * math.pi)
    if CLOUD_FRONT_START < sim_hour < CLOUD_FRONT_END + 1.0:
        t -= 1.5 * _bump(sim_hour, CLOUD_FRONT_START, CLOUD_FRONT_PEAK, CLOUD_FRONT_END + 1.0)
    return round(t, 1)


def house_baseload_kw(sim_hour: float) -> float:
    """Household load excluding the big controllable appliances."""
    load = 0.35  # fridge, router, standby
    if 6.5 <= sim_hour < 8.0:
        load += 0.9  # breakfast
    if 12.0 <= sim_hour < 13.0:
        load += 0.5  # lunch
    if 18.0 <= sim_hour < 20.5:
        load += 1.6  # dinner + evening
    if 20.5 <= sim_hour < 22.0:
        load += 0.6  # TV, lights
    return round(load, 2)


def day_tariff() -> "list[tuple[float, float, float, str]]":
    """The demo day's grid tariff: (start_hour, end_hour, ct/kWh, label)."""
    return [
        (0.0, 6.0, 18.0, "off-peak"),
        (6.0, 17.0, 32.0, "standard"),
        (17.0, 21.0, 46.0, "peak"),
        (21.0, 24.0, 18.0, "off-peak"),
    ]


def tariff_ct_per_kwh(sim_hour: float) -> float:
    for start, end, ct, _ in day_tariff():
        if start <= sim_hour < end:
            return ct
    return day_tariff()[-1][2]


def ev_blue_is_home(sim_hour: float) -> bool:
    return not (EV_BLUE_DEPARTS <= sim_hour < EV_BLUE_RETURNS)


def ev_blue_soc_while_away(sim_hour: float, soc_at_departure: float) -> float:
    """SoC drains roughly linearly during the commute + workday."""
    if sim_hour <= EV_BLUE_DEPARTS:
        return soc_at_departure
    driven = min(sim_hour, EV_BLUE_RETURNS) - EV_BLUE_DEPARTS
    return max(5.0, soc_at_departure - 1.7 * driven)
