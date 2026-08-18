"""heatpump-01 — the heat pump + domestic hot water (DHW) tank.

Real device. It *asks* for a cheap energy window (``window_request``) rather
than deciding when to run; the agent answers with ``grant_window`` and later
invokes ``start_dhw``. Demonstrates the request/grant idiom: the device states
a need, the agent owns the schedule.
"""

from __future__ import annotations

from device_connect_edge.drivers import emit, periodic, rpc
from device_connect_edge.types import DeviceIdentity, DeviceStatus

from ..runtime import SunhausDriver, run_device

DEVICE_ID = "heatpump-01"


class HeatPumpDriver(SunhausDriver):
    device_type = "heat_pump"
    labels = {"category": "heating", "location": "basement", "vendor": "sunhaus"}

    def __init__(self) -> None:
        super().__init__()
        self._state = "standby"  # standby | scheduled | heating_dhw | night_setback
        self._setpoint_c = 21.0
        self._tank_c = 48.0
        self._window: tuple[float, float, float] | None = None
        self._fired = set()

    @property
    def identity(self) -> DeviceIdentity:
        return DeviceIdentity(
            device_type="heat_pump", manufacturer="SUNHAUS", model="AquaTherm-DHW",
            firmware_version="1.0.0", description="Air-source heat pump with DHW tank",
        )

    @property
    def status(self) -> DeviceStatus:
        return DeviceStatus(location="basement",
                            availability="busy" if self._state == "heating_dhw" else "available")

    def _fire_once(self, key: str) -> bool:
        if key in self._fired:
            return False
        self._fired.add(key)
        return True

    # -- RPCs --------------------------------------------------------------

    @rpc(labels={"direction": "write", "safety": "informational"})
    async def grant_window(self, start_hour: float, end_hour: float, kwh: float) -> dict:
        """Agent grants a cheap-energy window for the DHW load.

        Args:
            start_hour: Window start (simulated hour).
            end_hour: Window end (simulated hour).
            kwh: Energy granted for the window.
        """
        self._window = (start_hour, end_hour, kwh)
        self._state = "scheduled"
        return {"ok": True, "window": {"start": start_hour, "end": end_hour, "kwh": kwh}}

    @rpc(labels={"direction": "write"})
    async def start_dhw(self) -> dict:
        """Start heating domestic hot water now."""
        self._state = "heating_dhw"
        return {"ok": True, "state": self._state}

    @rpc(labels={"direction": "write"})
    async def set_setpoint(self, c: float) -> dict:
        """Set the space-heating setpoint in Celsius.

        Args:
            c: Target temperature in Celsius.
        """
        self._setpoint_c = c
        return {"ok": True, "setpoint_c": c}

    @rpc(labels={"direction": "read"})
    async def get_state(self) -> dict:
        """Return heat-pump state, setpoint and tank temperature."""
        return {"state": self._state, "setpoint_c": self._setpoint_c,
                "tank_c": round(self._tank_c, 1)}

    # -- events ------------------------------------------------------------

    @emit()
    async def window_request(self, load_kwh: float, deadline_hour: float):
        """The heat pump asks the agent for a cheap-energy window."""

    @emit()
    async def dhw_done(self, tank_c: float):
        """Hot water is up to temperature."""

    @emit()
    async def setback_entered(self, setpoint_c: float):
        """Night setback engaged."""

    @emit()
    async def tank(self, tank_c: float, state: str):
        """Periodic tank-temperature telemetry."""

    # -- loop --------------------------------------------------------------

    @periodic(interval=2.0)
    async def report(self):
        h = self.clock.sim_hour()

        # Ask for a 3 kWh DHW window before the day's peak, and keep asking
        # until the agent grants one (reliable over best-effort D2D).
        if 8.4 <= h < 15.0 and self._window is None and self._state == "standby":
            await self.window_request(load_kwh=3.0, deadline_hour=15.0)

        if self._state == "heating_dhw":
            self._tank_c = min(60.0, self._tank_c + 0.4)
            if self._tank_c >= 55.0 and self._fire_once("dhw_done"):
                self._state = "standby"
                await self.dhw_done(tank_c=round(self._tank_c, 1))
        else:
            self._tank_c = max(40.0, self._tank_c - 0.05)

        if h >= 21.0 and self._fire_once("setback"):
            self._state = "night_setback"
            self._setpoint_c = 19.0
            await self.setback_entered(setpoint_c=self._setpoint_c)

        await self.tank(tank_c=round(self._tank_c, 1), state=self._state)


if __name__ == "__main__":
    run_device(HeatPumpDriver(), DEVICE_ID)
