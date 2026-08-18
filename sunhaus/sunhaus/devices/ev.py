"""ev-blue / ev-red — the two electric vehicles.

Real device, parameterized by which car. ev-blue commutes: it emits ``departed``
when it leaves, ``heading_home`` from the road (ETA + the energy it intends to
charge) so the agent can pre-plan, then ``arrived``. ev-red stays home and
emits a ``charge_requested`` for an evening top-up. SoC rises by listening to
the wallbox's real session telemetry (``@on``) — the car doesn't trust a
number, it measures what actually flowed.

Run as:  python -m sunhaus.devices.ev ev-blue
         python -m sunhaus.devices.ev ev-red
"""

from __future__ import annotations

import sys
import time

from device_connect_edge.drivers import emit, on, periodic, rpc
from device_connect_edge.types import DeviceIdentity, DeviceStatus

from .. import scenario
from ..models import ChargeRequest, to_payload
from ..runtime import SunhausDriver, run_device

BATTERY_KWH = 60.0


class ElectricVehicleDriver(SunhausDriver):
    device_type = "electric_vehicle"

    def __init__(self, vehicle_id: str) -> None:
        super().__init__()
        self.vehicle_id = vehicle_id
        self.is_commuter = vehicle_id == "ev-blue"
        self._soc = 41.0 if self.is_commuter else 63.0
        self._soc_at_departure = self._soc
        self._last_wall = time.monotonic()
        self.labels = {"category": "ev", "location": "carport",
                       "vendor": "sunhaus", "color": vehicle_id.split("-")[-1]}
        # one-shot flags
        self._fired = set()

    @property
    def identity(self) -> DeviceIdentity:
        return DeviceIdentity(
            device_type="electric_vehicle", manufacturer="SUNHAUS", model="Volt-e60",
            firmware_version="1.0.0", description=f"{BATTERY_KWH} kWh EV ({self.vehicle_id})",
        )

    @property
    def status(self) -> DeviceStatus:
        home = (not self.is_commuter) or scenario.ev_blue_is_home(self.clock.sim_hour())
        return DeviceStatus(location="carport" if home else "away",
                            availability="available", battery=int(self._soc))

    # -- RPCs --------------------------------------------------------------

    @rpc(labels={"direction": "read"})
    async def get_soc(self) -> dict:
        """Return the vehicle's state of charge (percent)."""
        return {"vehicle_id": self.vehicle_id, "soc_pct": round(self._soc, 1),
                "battery_kwh": BATTERY_KWH}

    @rpc(labels={"direction": "write"})
    async def request_charge(self, target_pct: float, by_hour: float) -> dict:
        """Ask to reach ``target_pct`` by simulated hour ``by_hour``.

        Args:
            target_pct: Desired final state of charge (percent).
            by_hour: Simulated hour by which the target is needed.
        """
        req = ChargeRequest(vehicle_id=self.vehicle_id, target_pct=target_pct,
                            by_hour=by_hour, battery_kwh=BATTERY_KWH, current_pct=self._soc)
        await self.charge_requested(**to_payload(req))
        return {"ok": True, "needed_kwh": round(req.needed_kwh, 1)}

    @rpc(labels={"direction": "write"})
    async def precondition(self, temp_c: float) -> dict:
        """Pre-condition the cabin to ``temp_c`` before departure.

        Args:
            temp_c: Target cabin temperature in Celsius.
        """
        return {"ok": True, "cabin_c": temp_c}

    # -- events ------------------------------------------------------------

    @emit()
    async def departed(self, vehicle_id: str, soc_pct: float):
        """The vehicle left home."""

    @emit()
    async def heading_home(self, vehicle_id: str, eta_hour: float, target_pct: float,
                           by_hour: float, needed_kwh: float):
        """Announced from the road: ETA and the charge it will need."""

    @emit()
    async def arrived(self, vehicle_id: str, soc_pct: float):
        """The vehicle arrived home."""

    @emit()
    async def charge_requested(self, vehicle_id: str, target_pct: float, by_hour: float,
                               battery_kwh: float, current_pct: float):
        """An at-home charge request (evening top-up)."""

    @emit()
    async def target_reached(self, vehicle_id: str, soc_pct: float):
        """The charge target was reached."""

    # -- listen to the wallbox (simulator coupling via the real bus) -------

    @on(device_id="wallbox-01", event_name="session")
    async def _on_wallbox_session(self, device_id: str, event_name: str, payload: dict):
        """Raise our SoC by whatever the wallbox reports actually flowing."""
        if not payload.get("charging"):
            return
        home = (not self.is_commuter) or scenario.ev_blue_is_home(self.clock.sim_hour())
        if not home:
            return
        # payload carries instantaneous kW; integrate against sim time.
        now = time.monotonic()
        sim_hours = (now - self._last_wall) * self.clock.rate / 3600.0
        self._last_wall = now
        gained = payload.get("kw", 0.0) * sim_hours / BATTERY_KWH * 100.0
        before = self._soc
        self._soc = min(100.0, self._soc + gained)
        if before < 60.0 <= self._soc:
            await self.target_reached(vehicle_id=self.vehicle_id, soc_pct=round(self._soc, 1))

    # -- lifecycle loop ----------------------------------------------------

    def _fire_once(self, key: str) -> bool:
        if key in self._fired:
            return False
        self._fired.add(key)
        return True

    @periodic(interval=1.0)
    async def drive(self):
        self._last_wall = time.monotonic()  # keep coupling integrator fresh
        h = self.clock.sim_hour()

        if not self.is_commuter:
            # ev-red: keep advertising the evening top-up over a short window
            # so the agent reliably receives it (best-effort D2D).
            if scenario.EV_RED_REQUESTS <= h < scenario.EV_RED_REQUESTS + 1.0:
                await self.request_charge(target_pct=78.0, by_hour=7.0)
            return

        # ev-blue commute lifecycle
        if h >= scenario.EV_BLUE_DEPARTS and self._fire_once("depart"):
            self._soc_at_departure = self._soc
            await self.departed(vehicle_id=self.vehicle_id, soc_pct=round(self._soc, 1))

        if scenario.EV_BLUE_DEPARTS <= h < scenario.EV_BLUE_RETURNS:
            self._soc = scenario.ev_blue_soc_while_away(h, self._soc_at_departure)

        # Announce from the road, repeatedly until arrival, so the agent can
        # pre-plan the charge even if a single announcement is dropped.
        if scenario.EV_BLUE_ANNOUNCES <= h < scenario.EV_BLUE_RETURNS:
            needed = max(0.0, (60.0 - self._soc) / 100.0 * BATTERY_KWH)
            await self.heading_home(vehicle_id=self.vehicle_id,
                                    eta_hour=scenario.EV_BLUE_RETURNS, target_pct=60.0,
                                    by_hour=7.0, needed_kwh=round(needed, 1))

        if h >= scenario.EV_BLUE_RETURNS and self._fire_once("arrive"):
            await self.arrived(vehicle_id=self.vehicle_id, soc_pct=round(self._soc, 1))


def main() -> None:
    vehicle_id = sys.argv[1] if len(sys.argv) > 1 else "ev-blue"
    run_device(ElectricVehicleDriver(vehicle_id), vehicle_id)


if __name__ == "__main__":
    main()
