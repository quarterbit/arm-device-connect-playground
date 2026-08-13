"""Shared value types passed between SUNHAUS devices and the home agent.

Everything here is plain data — devices answer RPCs with dicts produced by
``dataclasses.asdict`` so payloads stay JSON-serializable on the bus, and the
agent may rehydrate them with the ``from_dict`` helpers. Devices never import
each other; this module is the only shared vocabulary.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def to_payload(obj: Any) -> dict[str, Any]:
    """Dataclass → JSON-safe dict for RPC replies and event payloads."""
    return asdict(obj)


@dataclass
class SolarForecast:
    """Inverter's expectation for the day, revised as conditions change."""

    total_kwh: float
    peak_kw: float
    peak_hour: float  # simulated hour of day, e.g. 12.5
    revision: int = 0  # bumped on every re-forecast (e.g. cloud front)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SolarForecast":
        return cls(**d)


@dataclass
class WeatherReport:
    """Fused view from mast sensors + internet feed (+ sky camera)."""

    condition: str  # "sunny" | "clouding" | "overcast" | "clearing" | "night"
    temp_c: float
    max_temp_c: float
    cloud_cover: float  # 0.0-1.0
    pv_estimate_kwh: float

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WeatherReport":
        return cls(**d)


@dataclass
class TariffWindow:
    """One price band on the grid meter's tariff schedule."""

    start_hour: float
    end_hour: float
    ct_per_kwh: float
    label: str = ""  # "off-peak" | "standard" | "peak"


@dataclass
class Tariff:
    """Grid tariff for the day, owned by meter-01."""

    windows: list[TariffWindow] = field(default_factory=list)

    def price_at(self, sim_hour: float) -> float:
        for w in self.windows:
            if w.start_hour <= sim_hour < w.end_hour:
                return w.ct_per_kwh
        return self.windows[-1].ct_per_kwh if self.windows else 0.0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Tariff":
        return cls(windows=[TariffWindow(**w) for w in d.get("windows", [])])


@dataclass
class ChargeRequest:
    """An EV's ask: reach ``target_pct`` by simulated hour ``by_hour``."""

    vehicle_id: str
    target_pct: float
    by_hour: float
    battery_kwh: float
    current_pct: float

    @property
    def needed_kwh(self) -> float:
        return max(0.0, (self.target_pct - self.current_pct) / 100.0 * self.battery_kwh)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ChargeRequest":
        return cls(**{k: d[k] for k in
                      ("vehicle_id", "target_pct", "by_hour", "battery_kwh", "current_pct")})


@dataclass
class ChargeSlot:
    """One scheduled slice of a charge plan."""

    start_hour: float
    end_hour: float
    kw: float
    source: str  # "pv_surplus" | "off_peak" | "battery"


@dataclass
class ChargePlan:
    """The agent's answer to a ChargeRequest: when, how fast, from what."""

    vehicle_id: str
    slots: list[ChargeSlot] = field(default_factory=list)
    rationale: str = ""

    @property
    def total_kwh(self) -> float:
        return sum(s.kw * (s.end_hour - s.start_hour) for s in self.slots)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ChargePlan":
        return cls(
            vehicle_id=d["vehicle_id"],
            slots=[ChargeSlot(**s) for s in d.get("slots", [])],
            rationale=d.get("rationale", ""),
        )


@dataclass
class HeadingHome:
    """EV's announcement from the road: ETA plus the energy it intends to charge."""

    vehicle_id: str
    eta_hour: float
    target_pct: float
    by_hour: float
    needed_kwh: float

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "HeadingHome":
        return cls(**{k: d[k] for k in
                      ("vehicle_id", "eta_hour", "target_pct", "by_hour", "needed_kwh")})


@dataclass
class WasherJob:
    """A loaded drum with a deadline: the owner wants it done by ``ready_by_hour``."""

    program: str  # e.g. "eco40"
    est_kwh: float
    duration_h: float
    ready_by_hour: float

    def latest_start(self) -> float:
        return self.ready_by_hour - self.duration_h

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WasherJob":
        return cls(**{k: d[k] for k in
                      ("program", "est_kwh", "duration_h", "ready_by_hour")})


@dataclass
class EnergyWindow:
    """Agent's reply to heatpump's request_window: a cheap-energy slot."""

    start_hour: float
    end_hour: float
    kwh: float
    reason: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EnergyWindow":
        return cls(**d)


@dataclass
class DayStats:
    """End-of-day summary the agent publishes at 21:55."""

    pv_kwh: float
    self_consumption_pct: float
    grid_import_kwh: float
    grid_export_kwh: float
    battery_soc_pct: float
