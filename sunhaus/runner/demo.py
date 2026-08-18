"""runner/demo.py — launch the whole house.

Spawns every device as its own OS process plus the home agent, all sharing one
simulated-day clock through the environment (a common epoch + speed). Each
process is a real ``DeviceRuntime``; discovery is real Zenoh D2D. This is the
honest version of the storyboard: no scripted timeline, just real processes
finding each other and a real agent orchestrating them.

Run:  python -m runner.demo               # 3-minute day (1x)
      python -m runner.demo --speed 6x    # 30-second smoke run
      python -m runner.demo --tail        # also stream the live event log
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

from sunhaus.simclock import DAY_SIM_HOURS, DEMO_DAY_SECONDS, parse_speed

DEVICES = [
    ("sunhaus.devices.inverter", []),
    ("sunhaus.devices.battery", []),
    ("sunhaus.devices.wallbox", []),
    ("sunhaus.devices.ev", ["ev-blue"]),
    ("sunhaus.devices.ev", ["ev-red"]),
    ("sunhaus.devices.heatpump", []),
    ("sunhaus.devices.hvac", []),
    ("sunhaus.devices.washer", []),
    ("sunhaus.devices.climate", []),
    ("sunhaus.devices.weather", []),
    ("sunhaus.devices.meter", []),
]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _spawn(module: str, args: list[str], env: dict, quiet: bool = True) -> subprocess.Popen:
    sink = subprocess.DEVNULL if quiet else None
    return subprocess.Popen(
        [sys.executable, "-m", module, *args],
        cwd=ROOT, env=env,
        stdout=sink, stderr=subprocess.DEVNULL,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Launch the SUNHAUS demo house.")
    ap.add_argument("--speed", default="1x", help="1x (180s day), 6x (30s), realtime")
    ap.add_argument("--tail", action="store_true", help="also stream the live event log")
    ap.add_argument("--boot", type=float, default=6.0, help="device boot lead time (s)")
    args = ap.parse_args()

    speed = parse_speed(args.speed)
    day_real_s = DEMO_DAY_SECONDS / speed

    env = os.environ.copy()
    env["DEVICE_CONNECT_ALLOW_INSECURE"] = "true"
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
    # Shared clock: epoch is when the *day* starts. Devices boot first, then the
    # simulated 06:00 begins after `--boot` seconds so discovery finishes first.
    env["SUNHAUS_SIM_EPOCH"] = repr(time.time() + args.boot)
    env["SUNHAUS_SIM_SPEED"] = repr(speed)

    print(f"SUNHAUS — launching {len(DEVICES)} devices + agent  "
          f"(speed {args.speed}, day ≈ {day_real_s:.0f}s)\n", flush=True)

    procs: list[subprocess.Popen] = []
    for module, dev_args in DEVICES:
        procs.append(_spawn(module, dev_args, env))
    print(f"· {len(procs)} device processes booting in Zenoh D2D mode "
          f"(peer scouting, no broker)…", flush=True)

    # Let devices announce before the agent tries to discover.
    time.sleep(args.boot)

    tail_proc = None
    if args.tail:
        tail_proc = _spawn("runner.tail", ["--quiet"], env, quiet=False)

    agent = subprocess.Popen(
        [sys.executable, "-m", "agent.home_agent"],
        cwd=ROOT, env=env,
    )

    try:
        # Run until the simulated day is over (plus a little slack), then stop.
        agent.wait(timeout=day_real_s + 20)
    except subprocess.TimeoutExpired:
        pass
    except KeyboardInterrupt:
        print("\n· interrupted — shutting the house down", flush=True)
    finally:
        for p in [agent, tail_proc, *procs]:
            if p and p.poll() is None:
                p.terminate()
        for p in [agent, tail_proc, *procs]:
            if p:
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()
    print("\nSUNHAUS — house stopped.", flush=True)


if __name__ == "__main__":
    main()
