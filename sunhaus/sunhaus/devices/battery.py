"""battery-01 — the home battery.

Real device. The agent sets the mode (charge / discharge / hold) via RPC; the
battery integrates its own state of charge from that mode and the locally
estimated house surplus (PV minus baseload). Emits SoC telemetry and a
threshold event when it crosses 80 %.
"""

from __future__ import annotations

import time

from device_connect_edge.drivers import emit, periodic, rpc
from device_connect_edge.types import DeviceIdentity, DeviceStatus

from .. import scenario
from ..runtime import SunhausDriver, run_device

DEVICE_ID = "battery-01"


class HomeBatteryDriver(SunhausDriver):
    device_type = "home_battery"
    labels = {"category": "storage", "location": "basement", "vendor": "sunhaus"}

    def __init__(self, capacity_kwh: float = scenario.BATTERY_KWH, soc0: float = 35.0) -> None:
        super().__init__()
        self.capacity_kwh = capacity_kwh
        self._soc = soc0
        self._mode = "hold"  # charge | discharge | hold
        self._mode_kw = 0.0
        self._reserve_kwh = 0.0
        self._last_wall = time.monotonic()
        self._crossed_80 = False

    @property
    def identity(self) -> DeviceIdentity:
        return DeviceIdentity(
            device_type="home_battery", manufacturer="SUNHAUS", model="PowerVault-12",
            firmware_version="1.0.0", description=f"{self.capacity_kwh} kWh home battery",
        )

    @property
    def status(self) -> DeviceStatus:
        return DeviceStatus(location="basement", availability="available",
                            battery=int(max(0, min(100, self._soc))))

    # -- integration -------------------------------------------------------

    def _integrate(self) -> None:
        """Advance SoC by the sim-time elapsed since the last tick."""
        now = time.monotonic()
        real_dt = now - self._last_wall
        self._last_wall = now
        sim_hours = real_dt * self.clock.rate / 3600.0

        if self._mode == "charge":
            power = self._mode_kw
        elif self._mode == "discharge":
            power = -self._mode_kw
        else:
            power = 0.0

        self._soc += power * sim_hours / self.capacity_kwh * 100.0
        self._soc = max(0.0, min(100.0, self._soc))

    # -- RPCs --------------------------------------------------------------

    @rpc(labels={"direction": "read"})
    async def get_soc(self) -> dict:
        """Return state of charge (percent) and mode."""
        return {"soc_pct": round(self._soc, 1), "mode": self._mode,
                "reserve_kwh": self._reserve_kwh}

    @rpc(labels={"direction": "write", "safety": "informational"})
    async def set_mode(self, mode: str, kw: float = 2.0) -> dict:
        """Set the battery mode.

        Args:
            mode: One of "charge", "discharge", "hold".
            kw: Power setpoint in kW for charge/discharge.
        """
        if mode not in ("charge", "discharge", "hold"):
            return {"ok": False, "error": f"bad mode {mode!r}"}
        self._integrate()
        self._mode, self._mode_kw = mode, kw
        await self.mode_changed(mode=mode, kw=kw)
        return {"ok": True, "mode": mode, "kw": kw}

    @rpc(labels={"direction": "write"})
    async def reserve(self, kwh: float) -> dict:
        """Reserve ``kwh`` of capacity (a discharge guard band).

        Args:
            kwh: Energy to hold in reserve.
        """
        self._reserve_kwh = kwh
        return {"ok": True, "reserve_kwh": kwh}

    # -- events ------------------------------------------------------------

    @emit()
    async def soc(self, soc_pct: float, mode: str):
        """Periodic state-of-charge telemetry."""

    @emit()
    async def mode_changed(self, mode: str, kw: float):
        """The agent changed the battery mode."""

    @emit()
    async def soc_threshold(self, soc_pct: float, threshold: int):
        """SoC crossed a notable threshold."""

    # -- loops -------------------------------------------------------------

    @periodic(interval=2.0)
    async def report(self):
        self._integrate()
        if not self._crossed_80 and self._soc >= 80.0:
            self._crossed_80 = True
            await self.soc_threshold(soc_pct=round(self._soc, 1), threshold=80)
        await self.soc(soc_pct=round(self._soc, 1), mode=self._mode)


if __name__ == "__main__":
    run_device(HomeBatteryDriver(), DEVICE_ID)
