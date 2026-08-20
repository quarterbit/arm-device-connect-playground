"""pool-01 — 8,000 litre pool, filter, heat pump, cover and sensor."""

from __future__ import annotations

from device_connect_edge.drivers import emit, periodic, rpc
from device_connect_edge.types import DeviceIdentity, DeviceStatus

from .. import scenario
from ..runtime import SunhausDriver, run_device

DEVICE_ID = "pool-01"


class PoolDriver(SunhausDriver):
    device_type = "pool_system"
    labels = {"category": "pool", "location": "garden", "vendor": "sunhaus"}

    def __init__(self) -> None:
        super().__init__()
        self._water_temp_c = scenario.POOL_INITIAL_TEMP_C
        self._target_temp_c = scenario.POOL_TARGET_TEMP_C
        self._filter_on = False
        self._heating_on = False
        self._cover = "closed"
        self._window: tuple[float, float] | None = None
        self._last_hour = self.clock.sim_hour()
        self._target_reported = False

    @property
    def identity(self) -> DeviceIdentity:
        return DeviceIdentity(
            device_type=self.device_type,
            manufacturer="SUNHAUS",
            model="AquaGarden-8000",
            firmware_version="1.0.0",
            description="8,000 L pool with filter, heat pump, cover and water sensor",
        )

    @property
    def status(self) -> DeviceStatus:
        active = self._filter_on or self._heating_on
        return DeviceStatus(location="garden", availability="busy" if active else "available")

    @rpc(labels={"direction": "write", "safety": "informational"})
    async def grant_heating_window(self, start_hour: float, end_hour: float) -> dict:
        """Grant the pool a solar-powered heating window."""
        if end_hour <= start_hour:
            return {"ok": False, "error": "end_hour must be after start_hour"}
        self._window = (start_hour, end_hour)
        return {"ok": True, "window": {"start": start_hour, "end": end_hour}}

    @rpc(labels={"direction": "write"})
    async def set_filter(self, enabled: bool) -> dict:
        """Start or stop pool-water filtration."""
        self._filter_on = enabled
        if not enabled:
            self._heating_on = False
        await self.state_changed(**self._state_payload())
        return {"ok": True, **self._state_payload()}

    @rpc(labels={"direction": "write"})
    async def set_heating(self, enabled: bool) -> dict:
        """Start or stop the pool heat pump; circulation must be running."""
        if enabled and not self._filter_on:
            return {"ok": False, "error": "filter must be running before heating"}
        self._heating_on = enabled
        await self.state_changed(**self._state_payload())
        return {"ok": True, **self._state_payload()}

    @rpc(labels={"direction": "write"})
    async def set_cover(self, position: str) -> dict:
        """Set the automatic pool cover to ``open`` or ``closed``."""
        if position not in {"open", "closed"}:
            return {"ok": False, "error": "position must be open or closed"}
        self._cover = position
        await self.state_changed(**self._state_payload())
        return {"ok": True, **self._state_payload()}

    @rpc(labels={"direction": "read"})
    async def get_state(self) -> dict:
        """Return pool equipment and water-temperature state."""
        return self._state_payload()

    @emit()
    async def pool_heating_request(self, current_c: float, target_c: float,
                                   deadline_hour: float, estimated_kwh: float):
        """Ask the agent to schedule pool heating on available solar power."""

    @emit()
    async def water_temperature(self, temp_c: float, target_c: float,
                                filter_on: bool, heating_on: bool, cover: str):
        """Periodic water-temperature and equipment telemetry."""

    @emit()
    async def state_changed(self, volume_l: int, temp_c: float, target_c: float,
                            filter_on: bool, heating_on: bool, cover: str,
                            power_kw: float):
        """Pool equipment state changed."""

    @emit()
    async def target_reached(self, temp_c: float):
        """Pool water reached its target temperature."""

    def _state_payload(self) -> dict:
        power = (0.45 if self._filter_on else 0.0)
        if self._heating_on:
            power += scenario.POOL_HEATER_KW
        return {
            "volume_l": scenario.POOL_VOLUME_L,
            "temp_c": round(self._water_temp_c, 1),
            "target_c": self._target_temp_c,
            "filter_on": self._filter_on,
            "heating_on": self._heating_on,
            "cover": self._cover,
            "power_kw": round(power, 2),
        }

    def _integrate(self, elapsed_h: float, sim_hour: float | None = None) -> None:
        """Advance the deterministic pool-water model."""
        if elapsed_h <= 0:
            return
        if self._heating_on:
            thermal_kwh_per_c = scenario.POOL_VOLUME_L * 4.186 / 3600.0
            thermal_kw = scenario.POOL_HEATER_KW * scenario.POOL_HEATER_COP
            self._water_temp_c += thermal_kw * elapsed_h / thermal_kwh_per_c
        else:
            ambient = scenario.outdoor_temp_c(
                self.clock.sim_hour() if sim_hour is None else sim_hour
            )
            loss_rate = 0.012 if self._cover == "closed" else 0.035
            self._water_temp_c += (ambient - self._water_temp_c) * loss_rate * elapsed_h
        self._water_temp_c = min(self._water_temp_c, self._target_temp_c)

    @periodic(interval=2.0)
    async def report(self):
        h = self.clock.sim_hour()
        self._integrate(max(0.0, h - self._last_hour), h)
        self._last_hour = h

        if (8.5 <= h < scenario.POOL_HEAT_DEADLINE
                and self._window is None
                and self._water_temp_c < self._target_temp_c):
            await self.pool_heating_request(
                current_c=round(self._water_temp_c, 1),
                target_c=self._target_temp_c,
                deadline_hour=scenario.POOL_HEAT_DEADLINE,
                estimated_kwh=scenario.pool_heat_demand_kwh(self._water_temp_c),
            )

        if self._window and h >= self._window[1] and (self._filter_on or self._heating_on):
            self._heating_on = False
            self._filter_on = False
            self._cover = "closed"
            await self.state_changed(**self._state_payload())

        if self._water_temp_c >= self._target_temp_c and not self._target_reported:
            self._target_reported = True
            equipment_changed = self._heating_on or self._filter_on or self._cover != "closed"
            self._heating_on = False
            self._filter_on = False
            self._cover = "closed"
            if equipment_changed:
                await self.state_changed(**self._state_payload())
            await self.target_reached(temp_c=round(self._water_temp_c, 1))

        await self.water_temperature(
            temp_c=round(self._water_temp_c, 1),
            target_c=self._target_temp_c,
            filter_on=self._filter_on,
            heating_on=self._heating_on,
            cover=self._cover,
        )


if __name__ == "__main__":
    run_device(PoolDriver(), DEVICE_ID)
