"""meter-01 — the grid meter at the property boundary.

Real device. Reports instantaneous import/export power and the current tariff,
emits a ``tariff_changed`` event when the price band changes and a
``peak_warning`` when the expensive evening band opens. Net power is the local
balance of PV against the ambient house baseload (the meter senses the whole
house, so it may subscribe to production telemetry to refine that).
"""

from __future__ import annotations

from device_connect_edge.drivers import emit, on, periodic, rpc
from device_connect_edge.types import DeviceIdentity, DeviceStatus

from .. import scenario
from ..runtime import SunhausDriver, run_device

DEVICE_ID = "meter-01"


class GridMeterDriver(SunhausDriver):
    device_type = "grid_meter"
    labels = {"category": "grid", "location": "boundary", "vendor": "sunhaus"}

    def __init__(self) -> None:
        super().__init__()
        self._pv_kw = 0.0
        self._band = ""
        self._import_kwh = 0.0
        self._export_kwh = 0.0
        self._peak_warned = False

    @property
    def identity(self) -> DeviceIdentity:
        return DeviceIdentity(
            device_type="grid_meter", manufacturer="SUNHAUS", model="GridEye-3ph",
            firmware_version="1.0.0", description="Bidirectional grid meter",
        )

    @property
    def status(self) -> DeviceStatus:
        return DeviceStatus(location="boundary", availability="available")

    def _net_kw(self) -> float:
        """Positive = importing, negative = exporting."""
        h = self.clock.sim_hour()
        return round(scenario.house_baseload_kw(h) - self._pv_kw, 2)

    @on(device_id="inverter-01", event_name="production")
    async def _on_production(self, device_id: str, event_name: str, payload: dict):
        self._pv_kw = payload.get("kw", 0.0)

    @rpc(labels={"direction": "read"})
    async def get_power(self) -> dict:
        """Return net grid power (kW; positive=import) and PV seen."""
        net = self._net_kw()
        return {"net_kw": net, "importing": net > 0, "pv_kw": round(self._pv_kw, 2)}

    @rpc(labels={"direction": "read"})
    async def get_tariff(self) -> dict:
        """Return the current tariff band and the day's schedule."""
        h = self.clock.sim_hour()
        return {"ct_per_kwh": scenario.tariff_ct_per_kwh(h),
                "schedule": [{"start_hour": s, "end_hour": e, "ct_per_kwh": c, "label": lb}
                             for s, e, c, lb in scenario.day_tariff()]}

    @emit()
    async def power(self, net_kw: float, importing: bool, ct_per_kwh: float):
        """Periodic grid power + price telemetry."""

    @emit()
    async def tariff_changed(self, ct_per_kwh: float, label: str):
        """The grid tariff band changed."""

    @emit()
    async def peak_warning(self, ct_per_kwh: float):
        """The expensive evening peak band opened."""

    @periodic(interval=2.0)
    async def report(self):
        h = self.clock.sim_hour()
        for start, end, ct, label in scenario.day_tariff():
            if start <= h < end:
                if label != self._band:
                    self._band = label
                    await self.tariff_changed(ct_per_kwh=ct, label=label)
                    if label == "peak" and not self._peak_warned:
                        self._peak_warned = True
                        await self.peak_warning(ct_per_kwh=ct)
                break
        await self.power(net_kw=self._net_kw(), importing=self._net_kw() > 0,
                         ct_per_kwh=scenario.tariff_ct_per_kwh(h))


if __name__ == "__main__":
    run_device(GridMeterDriver(), DEVICE_ID)
