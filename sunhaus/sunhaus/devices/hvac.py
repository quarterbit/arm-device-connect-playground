"""hvac-01 — the air conditioner.

Real device. The agent sets mode (cool / eco / off) and setpoint via RPC. It
emits ``mode_changed`` when the agent steers it, ``comfort_violation`` if the
room drifts out of band, and power telemetry. The indoor climate sensor
listens to ``mode_changed`` to keep its room model consistent.
"""

from __future__ import annotations

from device_connect_edge.drivers import emit, periodic, rpc
from device_connect_edge.types import DeviceIdentity, DeviceStatus

from ..runtime import SunhausDriver, run_device

DEVICE_ID = "hvac-01"
_POWER = {"off": 0.0, "eco": 0.6, "cool": 1.8, "pre_cool": 2.2}


class AirConditionerDriver(SunhausDriver):
    device_type = "air_conditioner"
    labels = {"category": "cooling", "location": "living-room", "vendor": "sunhaus"}

    def __init__(self) -> None:
        super().__init__()
        self._mode = "off"
        self._setpoint_c = 24.0

    @property
    def identity(self) -> DeviceIdentity:
        return DeviceIdentity(
            device_type="air_conditioner", manufacturer="SUNHAUS", model="CoolBreeze-3",
            firmware_version="1.0.0", description="Inverter split air conditioner",
        )

    @property
    def status(self) -> DeviceStatus:
        return DeviceStatus(location="living-room",
                            availability="busy" if self._mode in ("cool", "pre_cool") else "available")

    @rpc(labels={"direction": "write", "safety": "informational"})
    async def set_mode(self, mode: str) -> dict:
        """Set AC mode.

        Args:
            mode: One of "cool", "eco", "off", "pre_cool".
        """
        if mode not in _POWER:
            return {"ok": False, "error": f"bad mode {mode!r}"}
        self._mode = mode
        await self.mode_changed(mode=mode, power_kw=_POWER[mode])
        return {"ok": True, "mode": mode}

    @rpc(labels={"direction": "write"})
    async def set_setpoint(self, c: float) -> dict:
        """Set the target room temperature in Celsius.

        Args:
            c: Target temperature in Celsius.
        """
        self._setpoint_c = c
        return {"ok": True, "setpoint_c": c}

    @rpc(labels={"direction": "read"})
    async def get_state(self) -> dict:
        """Return AC mode, setpoint and power draw."""
        return {"mode": self._mode, "setpoint_c": self._setpoint_c, "power_kw": _POWER[self._mode]}

    @emit()
    async def mode_changed(self, mode: str, power_kw: float):
        """The agent changed the AC mode or setpoint."""

    @emit()
    async def comfort_violation(self, room_c: float, setpoint_c: float):
        """The room drifted outside the comfort band."""

    @emit()
    async def power(self, mode: str, power_kw: float):
        """Periodic AC power telemetry."""

    @periodic(interval=2.0)
    async def report(self):
        await self.power(mode=self._mode, power_kw=_POWER[self._mode])


if __name__ == "__main__":
    run_device(AirConditionerDriver(), DEVICE_ID)
