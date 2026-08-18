"""wallbox-01 — the EV charger.

Real device. Tracks the plug state and an energy-metered charge session. The
agent starts/stops charging via RPC. The wallbox does not know which car is
plugged in — the EV announces itself; the wallbox just reports the plug event
and meters energy. Plug state is driven by ev-blue's home/away schedule.
"""

from __future__ import annotations

import time

from device_connect_edge.drivers import emit, periodic, rpc
from device_connect_edge.types import DeviceIdentity, DeviceStatus

from .. import scenario
from ..runtime import SunhausDriver, run_device

DEVICE_ID = "wallbox-01"


class EvChargerDriver(SunhausDriver):
    device_type = "ev_charger"
    labels = {"category": "ev", "location": "carport", "vendor": "sunhaus"}

    def __init__(self, max_kw: float = scenario.WALLBOX_MAX_KW) -> None:
        super().__init__()
        self.max_kw = max_kw
        self._plugged = True  # ev-blue starts the day plugged in at home
        self._charging = False
        self._kw = 0.0
        self._session_kwh = 0.0
        self._last_wall = time.monotonic()
        self._reserved_for: str | None = None
        self._last_plugged_state = True

    @property
    def identity(self) -> DeviceIdentity:
        return DeviceIdentity(
            device_type="ev_charger", manufacturer="SUNHAUS", model="Wallbox-11k",
            firmware_version="1.0.0", description=f"{self.max_kw} kW AC wallbox",
        )

    @property
    def status(self) -> DeviceStatus:
        return DeviceStatus(location="carport",
                            availability="busy" if self._charging else "available")

    # -- metering ----------------------------------------------------------

    def _meter(self) -> None:
        now = time.monotonic()
        sim_hours = (now - self._last_wall) * self.clock.rate / 3600.0
        self._last_wall = now
        if self._charging:
            self._session_kwh += self._kw * sim_hours

    # -- RPCs --------------------------------------------------------------

    @rpc(labels={"direction": "write", "safety": "informational"})
    async def start_charge(self, kw: float) -> dict:
        """Begin charging at ``kw`` (clamped to the wallbox max).

        Args:
            kw: Requested charge power in kW.
        """
        if not self._plugged:
            return {"ok": False, "error": "no vehicle plugged in"}
        self._meter()
        self._charging = True
        self._kw = min(kw, self.max_kw)
        return {"ok": True, "kw": self._kw}

    @rpc(labels={"direction": "write"})
    async def stop_charge(self) -> dict:
        """Pause the active charge session."""
        self._meter()
        self._charging = False
        self._kw = 0.0
        return {"ok": True}

    @rpc(labels={"direction": "read"})
    async def get_session(self) -> dict:
        """Return the current session: plugged, charging, kW, energy so far."""
        self._meter()
        return {"plugged": self._plugged, "charging": self._charging,
                "kw": round(self._kw, 2), "session_kwh": round(self._session_kwh, 2),
                "reserved_for": self._reserved_for}

    @rpc(labels={"direction": "write"})
    async def reserve(self, vehicle_id: str) -> dict:
        """Reserve the wallbox for an inbound vehicle (agent pre-planning).

        Args:
            vehicle_id: The vehicle the agent expects to arrive.
        """
        self._reserved_for = vehicle_id
        return {"ok": True, "reserved_for": vehicle_id}

    # -- events ------------------------------------------------------------

    @emit()
    async def plug_connected(self, session_kwh: float):
        """A vehicle was plugged in."""

    @emit()
    async def plug_disconnected(self):
        """The vehicle was unplugged."""

    @emit()
    async def session(self, charging: bool, kw: float, session_kwh: float):
        """Periodic charge-session telemetry."""

    @emit()
    async def session_complete(self, session_kwh: float):
        """The charge session finished."""

    # -- loops -------------------------------------------------------------

    @periodic(interval=2.0)
    async def report(self):
        # Plug state follows ev-blue's schedule (the car is the ground truth
        # for presence; the wallbox merely senses the plug).
        self._plugged = scenario.ev_blue_is_home(self.clock.sim_hour())
        if self._plugged != self._last_plugged_state:
            self._last_plugged_state = self._plugged
            if self._plugged:
                self._session_kwh = 0.0
                await self.plug_connected(session_kwh=0.0)
            else:
                if self._charging:
                    self._charging, self._kw = False, 0.0
                await self.plug_disconnected()
                self._reserved_for = None

        self._meter()
        await self.session(charging=self._charging, kw=round(self._kw, 2),
                           session_kwh=round(self._session_kwh, 2))


if __name__ == "__main__":
    run_device(EvChargerDriver(), DEVICE_ID)
