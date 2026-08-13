"""Shared simulated-day clock for SUNHAUS.

Every SUNHAUS process (device or agent) computes simulated time locally from
two values shared through the environment: a common epoch and a speed factor.
No clock topic, no coordinator — processes that agree on
``SUNHAUS_SIM_EPOCH`` and ``SUNHAUS_SIM_SPEED`` agree on the time of day.

The canonical demo day runs 06:00-22:00 (16 h) compressed into 180 real
seconds. Speeds are expressed relative to that: ``--speed 1x`` is the
3-minute demo, ``6x`` a 30-second smoke run, and ``realtime`` maps one
simulated second to one wall second for soak tests.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field

DAY_START_H = 6.0  # 06:00
DAY_END_H = 22.0  # 22:00
DAY_SIM_HOURS = DAY_END_H - DAY_START_H  # 16 h
DEMO_DAY_SECONDS = 180.0  # real seconds for one full day at speed 1x

ENV_EPOCH = "SUNHAUS_SIM_EPOCH"
ENV_SPEED = "SUNHAUS_SIM_SPEED"

#: simulated seconds that elapse per real second at demo speed 1x
DEMO_RATE = DAY_SIM_HOURS * 3600.0 / DEMO_DAY_SECONDS  # 320 sim-s / real-s


def parse_speed(text: str) -> float:
    """Parse a speed argument into a demo-speed multiplier.

    ``"1x"``/``"1"`` → 1.0 (180 s day), ``"6x"`` → 6.0 (30 s day),
    ``"realtime"`` → the multiplier at which sim time == wall time.
    """
    text = text.strip().lower()
    if text in ("realtime", "wall", "1:1"):
        return 1.0 / DEMO_RATE
    return float(text.rstrip("x"))


@dataclass
class SimClock:
    """Maps wall-clock time onto the simulated 06:00-22:00 day.

    ``epoch`` is the wall time (``time.time()``) at which the simulated day
    began; ``speed`` is the demo-speed multiplier (see :func:`parse_speed`).
    """

    epoch: float = field(default_factory=time.time)
    speed: float = 1.0

    # -- construction -----------------------------------------------------

    @classmethod
    def from_env(cls) -> "SimClock":
        """Build a clock from the shared environment (runner sets it)."""
        epoch = float(os.environ.get(ENV_EPOCH, time.time()))
        speed = float(os.environ.get(ENV_SPEED, "1.0"))
        return cls(epoch=epoch, speed=speed)

    def to_env(self) -> dict[str, str]:
        """Environment entries child processes need to share this clock."""
        return {ENV_EPOCH: repr(self.epoch), ENV_SPEED: repr(self.speed)}

    # -- time queries ------------------------------------------------------

    @property
    def rate(self) -> float:
        """Simulated seconds per real second."""
        return DEMO_RATE * self.speed

    def elapsed(self) -> float:
        """Real seconds since the day began (clamped at 0)."""
        return max(0.0, time.time() - self.epoch)

    def sim_seconds(self) -> float:
        """Simulated seconds since 06:00 (clamped to the 16 h day)."""
        return min(self.elapsed() * self.rate, DAY_SIM_HOURS * 3600.0)

    def sim_hour(self) -> float:
        """Simulated hour of day as a float, e.g. 12.5 == 12:30."""
        return DAY_START_H + self.sim_seconds() / 3600.0

    def hhmm(self) -> str:
        """Simulated time of day as ``"HH:MM"``."""
        h = self.sim_hour()
        return f"{int(h):02d}:{int((h - int(h)) * 60):02d}"

    def day_done(self) -> bool:
        """True once the simulated day has reached 22:00."""
        return self.sim_seconds() >= DAY_SIM_HOURS * 3600.0

    # -- waiting -----------------------------------------------------------

    def real_seconds_until(self, sim_hour: float) -> float:
        """Real seconds until the given simulated hour (0 if already past)."""
        remaining_sim = (sim_hour - self.sim_hour()) * 3600.0
        return max(0.0, remaining_sim / self.rate)

    async def wait_until(self, sim_hour: float) -> None:
        """Sleep (asyncio) until the simulated clock reaches ``sim_hour``."""
        await asyncio.sleep(self.real_seconds_until(sim_hour))

    def sim_interval(self, sim_seconds: float, *, floor: float = 0.05) -> float:
        """Real-second interval for a loop that ticks every ``sim_seconds``."""
        return max(floor, sim_seconds / self.rate)
