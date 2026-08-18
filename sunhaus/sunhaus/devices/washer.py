"""washer-01 — the washing machine.

Real device. The owner loads it in the morning and sets a deadline ("done by
17:30"); the machine emits ``job_queued`` with the program, estimated energy
and the ``ready_by`` hour. The agent schedules the start into the solar peak
and invokes ``start_cycle``. The machine reports ``cycle_complete`` when done —
the everyday appliance that benefits from a shared device bus.
"""

from __future__ import annotations

import time

from device_connect_edge.drivers import emit, periodic, rpc
from device_connect_edge.types import DeviceIdentity, DeviceStatus

from .. import scenario
from ..models import WasherJob, to_payload
from ..runtime import SunhausDriver, run_device

DEVICE_ID = "washer-01"


class WashingMachineDriver(SunhausDriver):
    device_type = "washing_machine"
    labels = {"category": "appliance", "location": "utility", "vendor": "sunhaus"}

    def __init__(self) -> None:
        super().__init__()
        self._state = "idle"  # idle | loaded | queued | running | done
        self._job = WasherJob(program="eco40", est_kwh=scenario.WASHER_EST_KWH,
                              duration_h=scenario.WASHER_DURATION_H,
                              ready_by_hour=scenario.WASHER_READY_BY)
        self._started_sim_h: float | None = None
        self._fired = set()

    @property
    def identity(self) -> DeviceIdentity:
        return DeviceIdentity(
            device_type="washing_machine", manufacturer="SUNHAUS", model="EcoWash-7",
            firmware_version="1.0.0", description="Front-load washing machine",
        )

    @property
    def status(self) -> DeviceStatus:
        return DeviceStatus(location="utility",
                            availability="busy" if self._state == "running" else "available")

    def _fire_once(self, key: str) -> bool:
        if key in self._fired:
            return False
        self._fired.add(key)
        return True

    @rpc(labels={"direction": "read"})
    async def get_job(self) -> dict:
        """Return the queued laundry job and current machine state."""
        return {"state": self._state, "job": to_payload(self._job)}

    @rpc(labels={"direction": "write", "safety": "informational"})
    async def start_cycle(self) -> dict:
        """Start the wash cycle now (agent decides when)."""
        if self._state not in ("loaded", "queued"):
            return {"ok": False, "error": f"cannot start from {self._state}"}
        self._state = "running"
        self._started_sim_h = self.clock.sim_hour()
        await self.cycle_started(program=self._job.program, est_kwh=self._job.est_kwh)
        return {"ok": True, "state": self._state}

    @emit()
    async def job_queued(self, program: str, est_kwh: float, duration_h: float, ready_by_hour: float):
        """The owner loaded a job with a completion deadline."""

    @emit()
    async def cycle_started(self, program: str, est_kwh: float):
        """The wash cycle started."""

    @emit()
    async def cycle_complete(self, program: str, finished_hour: float):
        """The wash cycle finished."""

    @periodic(interval=2.0)
    async def report(self):
        h = self.clock.sim_hour()

        if self._state == "idle" and h >= scenario.WASHER_LOADED:
            self._state = "loaded"

        # Advertise the pending job until the agent starts it. Repeating the
        # request makes it reliable over best-effort D2D pub/sub — the machine
        # keeps announcing its need until served.
        if self._state == "loaded":
            await self.job_queued(program=self._job.program, est_kwh=self._job.est_kwh,
                                  duration_h=self._job.duration_h,
                                  ready_by_hour=self._job.ready_by_hour)

        if self._state == "running" and self._started_sim_h is not None:
            if h - self._started_sim_h >= self._job.duration_h and self._fire_once("done"):
                self._state = "done"
                await self.cycle_complete(program=self._job.program, finished_hour=round(h, 2))


if __name__ == "__main__":
    run_device(WashingMachineDriver(), DEVICE_ID)
