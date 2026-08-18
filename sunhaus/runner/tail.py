"""runner/tail.py — the live message log.

`subscribe("event(*)")` on the real bus and print every event as it happens.
This is what the storyboard's log pane shows, except here it is not scripted —
it is genuine Zenoh D2D traffic from the running devices. Proof that nothing is
faked.

Run:  python -m runner.tail
"""

from __future__ import annotations

import time

from device_connect_agent_tools import connect, subscribe

_COLOR = {
    "pv_forecast": "\033[33m", "production": "\033[33m", "pv_curtailed": "\033[33m",
    "soc": "\033[32m", "mode_changed": "\033[32m", "soc_threshold": "\033[32m",
    "plug_connected": "\033[33m", "plug_disconnected": "\033[33m", "session": "\033[33m",
    "window_request": "\033[31m", "dhw_done": "\033[31m", "setback_entered": "\033[31m",
    "tariff_changed": "\033[35m", "peak_warning": "\033[35m", "power": "\033[35m",
    "wx_forecast": "\033[36m", "nowcast_updated": "\033[36m", "wx_update": "\033[36m",
    "climate": "\033[36m", "job_queued": "\033[36m", "cycle_complete": "\033[36m",
    "heading_home": "\033[36m", "arrived": "\033[36m", "departed": "\033[36m",
}
_RESET = "\033[0m"
_DIM = "\033[2m"


def _device_from_subject(subject: str) -> str:
    toks = subject.replace(".", "/").split("/")
    try:
        return toks[toks.index("event") - 1]
    except ValueError:
        return "?"


def _fmt_payload(p: dict) -> str:
    skip = {"event_id", "ts", "traceparent", "_trace_id"}
    return "  ".join(f"{k}={v}" for k, v in p.items() if k not in skip)


def main(quiet_telemetry: bool = False) -> None:
    connect()
    sub = subscribe("event(*)")
    print(f'$ python -m runner.tail   ·   subscribe("event(*)")  —  live Zenoh D2D bus\n')
    telemetry = {"production", "soc", "session", "power", "climate", "tank", "wx_update"}
    try:
        while True:
            for msg in sub.read():
                dev = _device_from_subject(msg.get("_subject", ""))
                event = msg.get("method", "?")
                payload = msg.get("params", {})
                if quiet_telemetry and event in telemetry:
                    continue
                ts = payload.get("ts", "")[11:19]
                col = _COLOR.get(event, "")
                dim = _DIM if event in telemetry else ""
                print(f"{dim}{ts} {col}{dev:13}{_RESET}{dim} {event:18} "
                      f"{_fmt_payload(payload)}{_RESET}", flush=True)
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    import sys
    main(quiet_telemetry="--quiet" in sys.argv)
