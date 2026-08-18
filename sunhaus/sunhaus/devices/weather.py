"""weather-01 — the weather station.

Real device. Fuses its own mast sensors (a local irradiance reading derived
from the sky) with an internet forecast/radar nowcast. It detects the
afternoon cloud front the way real systems do — its own irradiance drops and
the nowcast agrees — and emits ``nowcast_updated``. No sky camera required.
"""

from __future__ import annotations

from device_connect_edge.drivers import emit, periodic, rpc
from device_connect_edge.types import DeviceIdentity, DeviceStatus

from .. import scenario
from ..models import WeatherReport, to_payload
from ..runtime import SunhausDriver, run_device

DEVICE_ID = "weather-01"


class WeatherStationDriver(SunhausDriver):
    device_type = "weather_station"
    labels = {"category": "sensor", "location": "roof", "vendor": "sunhaus",
              "modality": "weather"}

    def __init__(self) -> None:
        super().__init__()
        self._fired = set()

    @property
    def identity(self) -> DeviceIdentity:
        return DeviceIdentity(
            device_type="weather_station", manufacturer="SUNHAUS", model="SkyMast-2",
            firmware_version="1.0.0", description="Mast weather station + internet nowcast fusion",
        )

    @property
    def status(self) -> DeviceStatus:
        return DeviceStatus(location="roof", availability="available")

    def _fire_once(self, key: str) -> bool:
        if key in self._fired:
            return False
        self._fired.add(key)
        return True

    def _report(self) -> WeatherReport:
        h = self.clock.sim_hour()
        cover = scenario.cloud_cover(h)
        cond = ("night" if h < 6.5 or h > 20.5
                else "overcast" if cover > 0.5
                else "clouding" if cover > 0.2
                else "sunny")
        return WeatherReport(
            condition=cond, temp_c=scenario.outdoor_temp_c(h), max_temp_c=31.0,
            cloud_cover=round(cover, 2),
            pv_estimate_kwh=scenario.pv_day_total_kwh(cloudy=cover > 0.3),
        )

    @rpc(labels={"direction": "read"})
    async def get_current(self) -> dict:
        """Return the current fused weather observation."""
        return to_payload(self._report())

    @rpc(labels={"direction": "read"})
    async def get_forecast(self) -> dict:
        """Return today's fused forecast (condition, temps, PV estimate)."""
        return to_payload(self._report())

    @emit()
    async def wx_forecast(self, condition: str, temp_c: float, max_temp_c: float,
                          cloud_cover: float, pv_estimate_kwh: float):
        """Morning day-ahead forecast."""

    @emit()
    async def nowcast_updated(self, condition: str, cloud_cover: float, irradiance_drop_pct: float):
        """Own irradiance + internet nowcast agree a front is inbound."""

    @emit()
    async def wx_update(self, condition: str, cloud_cover: float, temp_c: float):
        """Periodic / event-driven weather update."""

    @periodic(interval=3.0)
    async def observe(self):
        h = self.clock.sim_hour()
        r = self._report()

        if h >= 6.5 and self._fire_once("forecast"):
            await self.wx_forecast(condition=r.condition, temp_c=r.temp_c,
                                   max_temp_c=r.max_temp_c, cloud_cover=r.cloud_cover,
                                   pv_estimate_kwh=r.pv_estimate_kwh)

        # Front inbound: own irradiance drops and the nowcast agrees. Keep
        # broadcasting the alert for the duration of the front so the agent
        # reliably picks it up over best-effort D2D.
        if scenario.cloud_cover(h) > 0.35 and h < scenario.CLOUD_FRONT_END:
            drop = round(100.0 * 0.85 * scenario.cloud_cover(h), 0)
            await self.nowcast_updated(condition="clouding",
                                       cloud_cover=r.cloud_cover, irradiance_drop_pct=drop)

        # Front passed.
        if h > scenario.CLOUD_FRONT_END and self._fire_once("cleared"):
            await self.wx_update(condition="clearing", cloud_cover=r.cloud_cover, temp_c=r.temp_c)

        await self.wx_update(condition=r.condition, cloud_cover=r.cloud_cover, temp_c=r.temp_c)


if __name__ == "__main__":
    run_device(WeatherStationDriver(), DEVICE_ID)
