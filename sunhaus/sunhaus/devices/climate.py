"""climate-01 — the indoor climate sensor.

Real device, and the most ordinary one in the house. It has no actuators; it
observes. Its room model tracks outdoor temperature and cools when it hears
the AC run — coupling that flows over the *real bus* (``@on`` the AC's
``mode_changed``), never through shared memory, exactly as a real sensor gets
its coupling from the real air.
"""

from __future__ import annotations

from device_connect_edge.drivers import emit, on, periodic, rpc
from device_connect_edge.types import DeviceIdentity, DeviceStatus

from .. import scenario
from ..runtime import SunhausDriver, run_device

DEVICE_ID = "climate-01"
COMFORT_MAX_C = 25.0


class ClimateSensorDriver(SunhausDriver):
    device_type = "climate_sensor"
    labels = {"category": "sensor", "location": "living-room", "vendor": "sunhaus",
              "modality": "temperature"}

    def __init__(self) -> None:
        super().__init__()
        self._room_c = 21.4
        self._humidity = 45.0
        self._ac_power = 0.0
        self._warned = False

    @property
    def identity(self) -> DeviceIdentity:
        return DeviceIdentity(
            device_type="climate_sensor", manufacturer="SUNHAUS", model="RoomSense-1",
            firmware_version="1.0.0", description="Indoor temperature & humidity sensor",
        )

    @property
    def status(self) -> DeviceStatus:
        return DeviceStatus(location="living-room", availability="available")

    @rpc(labels={"direction": "read"})
    async def get_climate(self) -> dict:
        """Return indoor temperature (C) and relative humidity (%)."""
        return {"room_c": round(self._room_c, 1), "humidity_pct": round(self._humidity, 1)}

    @on(device_id="hvac-01", event_name="mode_changed")
    async def _on_ac(self, device_id: str, event_name: str, payload: dict):
        """Track the AC's cooling power so the room model stays consistent."""
        self._ac_power = payload.get("power_kw", 0.0)

    @emit()
    async def climate(self, room_c: float, humidity_pct: float):
        """Periodic indoor climate telemetry."""

    @emit()
    async def comfort_alert(self, room_c: float, limit_c: float):
        """Room temperature exceeded the comfort limit."""

    @periodic(interval=2.0)
    async def report(self):
        h = self.clock.sim_hour()
        # Room drifts toward a value a few degrees under outdoors, pulled down
        # further by active AC cooling.
        target = scenario.outdoor_temp_c(h) - 4.0 - self._ac_power * 1.6
        self._room_c += (target - self._room_c) * 0.15
        self._humidity = 42.0 + 8.0 * scenario.cloud_cover(h)

        if self._room_c > COMFORT_MAX_C and not self._warned:
            self._warned = True
            await self.comfort_alert(room_c=round(self._room_c, 1), limit_c=COMFORT_MAX_C)
        elif self._room_c < COMFORT_MAX_C - 0.5:
            self._warned = False

        await self.climate(room_c=round(self._room_c, 1), humidity_pct=round(self._humidity, 1))


if __name__ == "__main__":
    run_device(ClimateSensorDriver(), DEVICE_ID)
