"""inverter-01 — the PV inverter.

Real Device Connect device: answers production/forecast RPCs, emits a day
forecast at sunrise, re-forecasts when a cloud front is detected, and streams
production telemetry. PV output is a deterministic function of the simulated
sun and sky (``sunhaus.scenario``).
"""

from __future__ import annotations

from device_connect_edge.drivers import emit, periodic, rpc
from device_connect_edge.types import DeviceIdentity, DeviceStatus

from .. import scenario
from ..models import SolarForecast, to_payload
from ..runtime import SunhausDriver, run_device

DEVICE_ID = "inverter-01"


class PvInverterDriver(SunhausDriver):
    device_type = "pv_inverter"
    labels = {"category": "generation", "location": "roof", "vendor": "sunhaus"}

    def __init__(self) -> None:
        super().__init__()
        self._export_limit_kw: float | None = None
        self._revision = 0
        self._announced_forecast = False
        self._reforecast_done = False

    @property
    def identity(self) -> DeviceIdentity:
        return DeviceIdentity(
            device_type="pv_inverter",
            manufacturer="SUNHAUS",
            model="SolarEdge-9k6",
            firmware_version="1.0.0",
            description=f"{scenario.PV_KWP} kWp rooftop PV inverter",
        )

    @property
    def status(self) -> DeviceStatus:
        return DeviceStatus(location="roof", availability="available")

    # -- physics -----------------------------------------------------------

    def _production_kw(self) -> float:
        kw = scenario.pv_kw(self.clock.sim_hour())
        if self._export_limit_kw is not None:
            kw = min(kw, self._export_limit_kw)
        return round(kw, 2)

    def _forecast(self) -> SolarForecast:
        cloudy = self._reforecast_done
        return SolarForecast(
            total_kwh=scenario.pv_day_total_kwh(cloudy=cloudy),
            peak_kw=scenario.PV_PEAK_KW * (0.82 if cloudy else 1.0),
            peak_hour=12.5,
            revision=self._revision,
        )

    # -- RPCs --------------------------------------------------------------

    @rpc(labels={"direction": "read"})
    async def get_production(self) -> dict:
        """Return instantaneous PV production in kW."""
        return {"kw": self._production_kw(), "sim_hour": round(self.clock.sim_hour(), 2)}

    @rpc(labels={"direction": "read"})
    async def get_forecast(self) -> dict:
        """Return today's PV forecast (kWh, peak kW, peak hour)."""
        return to_payload(self._forecast())

    @rpc(labels={"direction": "write", "safety": "informational"})
    async def set_export_limit(self, kw: float) -> dict:
        """Clamp grid export to at most ``kw`` kilowatts.

        Args:
            kw: Maximum export power in kW.
        """
        self._export_limit_kw = kw
        return {"ok": True, "export_limit_kw": kw}

    # -- events ------------------------------------------------------------

    @emit()
    async def pv_forecast(self, total_kwh: float, peak_kw: float, peak_hour: float, revision: int):
        """Day-ahead PV forecast, re-emitted on each revision."""

    @emit()
    async def production(self, kw: float):
        """Periodic PV production telemetry."""

    @emit()
    async def pv_curtailed(self, cloud_cover: float, kw: float):
        """Production dropped because clouds arrived."""

    # -- loops -------------------------------------------------------------

    @periodic(interval=2.0)
    async def report(self):
        h = self.clock.sim_hour()

        if not self._announced_forecast and h >= 7.0:
            self._announced_forecast = True
            f = self._forecast()
            await self.pv_forecast(
                total_kwh=f.total_kwh, peak_kw=f.peak_kw,
                peak_hour=f.peak_hour, revision=f.revision,
            )

        # Cloud front: the inverter revises its day forecast down once the
        # front is measurably reducing output.
        if not self._reforecast_done and scenario.cloud_cover(h) > 0.4:
            self._reforecast_done = True
            self._revision = 2
            f = self._forecast()
            await self.pv_forecast(
                total_kwh=f.total_kwh, peak_kw=f.peak_kw,
                peak_hour=f.peak_hour, revision=f.revision,
            )
            await self.pv_curtailed(cloud_cover=round(scenario.cloud_cover(h), 2),
                                    kw=self._production_kw())

        await self.production(kw=self._production_kw())


if __name__ == "__main__":
    run_device(PvInverterDriver(), DEVICE_ID)
