"""Per-driver unit tests — no bus, no runtime.

Drivers are plain objects: instantiate one, await a decorated method, assert on
the result. Events are captured through ``set_event_callback`` (the same hook
``DeviceRuntime`` uses), so we can verify a device emits what it should without
ever opening a Zenoh session.
"""

from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("SUNHAUS_SIM_EPOCH", repr(time.time()))
os.environ.setdefault("SUNHAUS_SIM_SPEED", "1.0")

from sunhaus.devices.battery import HomeBatteryDriver
from sunhaus.devices.heatpump import HeatPumpDriver
from sunhaus.devices.hvac import AirConditionerDriver
from sunhaus.devices.inverter import PvInverterDriver
from sunhaus.devices.meter import GridMeterDriver
from sunhaus.devices.pool import PoolDriver
from sunhaus.devices.wallbox import EvChargerDriver
from sunhaus.devices.washer import WashingMachineDriver


class EventSink:
    """Collects (event_name, payload) emitted by a driver under test."""

    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    async def __call__(self, event_name: str, payload: dict):
        self.events.append((event_name, payload))

    def names(self) -> list[str]:
        return [n for n, _ in self.events]


def _attach(driver):
    sink = EventSink()
    driver.set_event_callback(sink)
    return sink


async def test_inverter_production_and_forecast():
    d = PvInverterDriver()
    prod = await d.get_production()
    assert prod["kw"] >= 0.0
    fc = await d.get_forecast()
    assert fc["peak_kw"] > 0 and fc["total_kwh"] > 0


async def test_battery_charge_raises_soc():
    d = HomeBatteryDriver(soc0=50.0)
    sink = _attach(d)
    res = await d.set_mode("charge", kw=3.0)
    assert res["ok"] and "mode_changed" in sink.names()
    d._last_wall -= 3600  # pretend an hour of real time passed
    d._integrate()
    assert (await d.get_soc())["soc_pct"] > 50.0


async def test_battery_rejects_bad_mode():
    d = HomeBatteryDriver()
    assert (await d.set_mode("turbo"))["ok"] is False


async def test_wallbox_meters_energy_only_when_charging():
    d = EvChargerDriver()
    d._plugged = True
    assert (await d.start_charge(kw=7.0))["kw"] == 7.0
    d._last_wall -= 3600
    d._meter()
    s = await d.get_session()
    assert s["session_kwh"] > 0 and s["charging"] is True
    await d.stop_charge()
    assert (await d.get_session())["charging"] is False


async def test_wallbox_refuses_charge_when_unplugged():
    d = EvChargerDriver()
    d._plugged = False
    assert (await d.start_charge(kw=7.0))["ok"] is False


async def test_heatpump_request_grant_start():
    d = HeatPumpDriver()
    sink = _attach(d)
    g = await d.grant_window(11.5, 13.0, 3.0)
    assert g["ok"] and (await d.get_state())["state"] == "scheduled"
    await d.start_dhw()
    assert (await d.get_state())["state"] == "heating_dhw"


async def test_pool_filter_heat_cover_and_temperature_sensor():
    d = PoolDriver()
    sink = _attach(d)
    state = await d.get_state()
    assert state["volume_l"] == 8_000
    assert (await d.set_heating(True))["ok"] is False
    assert (await d.set_cover("open"))["ok"]
    assert (await d.set_filter(True))["ok"]
    assert (await d.set_heating(True))["ok"]
    before = (await d.get_state())["temp_c"]
    d._integrate(1.0, 12.5)
    assert (await d.get_state())["temp_c"] > before
    assert "state_changed" in sink.names()
    d._water_temp_c = d._target_temp_c
    await d.report()
    state = await d.get_state()
    assert state["filter_on"] is False
    assert state["heating_on"] is False
    assert state["cover"] == "closed"
    assert "target_reached" in sink.names()


async def test_pool_requests_solar_heating_window():
    d = PoolDriver()
    sink = _attach(d)
    d.clock = type("Clock", (), {"sim_hour": lambda self: 9.0})()
    d._last_hour = 9.0
    await d.report()
    assert "pool_heating_request" in sink.names()
    assert "water_temperature" in sink.names()


async def test_hvac_modes():
    d = AirConditionerDriver()
    sink = _attach(d)
    assert (await d.set_mode("pre_cool"))["ok"]
    assert (await d.get_state())["power_kw"] > 0
    assert (await d.set_mode("nope"))["ok"] is False
    assert "mode_changed" in sink.names()


async def test_washer_start_only_when_loaded():
    d = WashingMachineDriver()
    _attach(d)
    assert (await d.start_cycle())["ok"] is False  # still idle
    d._state = "loaded"
    assert (await d.start_cycle())["ok"] is True
    assert (await d.get_job())["state"] == "running"


async def test_meter_tariff_schedule():
    d = GridMeterDriver()
    t = await d.get_tariff()
    assert t["ct_per_kwh"] > 0 and len(t["schedule"]) == 4
