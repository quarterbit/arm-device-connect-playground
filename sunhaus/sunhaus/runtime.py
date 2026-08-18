"""Common process entrypoint and base driver for every SUNHAUS device.

Each ``sunhaus.devices.<name>`` module defines a ``DeviceDriver`` subclass and
calls :func:`run_device` in its ``__main__``. This module owns the two things
every device shares: a :class:`SunhausDriver` base that carries the simulated
clock, and a Windows-safe run loop around ``DeviceRuntime``.

Nothing here fakes the bus. ``DeviceRuntime`` with no ``messaging_urls`` starts
a real Zenoh peer in D2D mode; discovery is real multicast/gossip presence.
"""

from __future__ import annotations

import asyncio
import os
import signal

from device_connect_edge import DeviceRuntime
from device_connect_edge.drivers import DeviceDriver

from .simclock import SimClock


class SunhausDriver(DeviceDriver):
    """Base for SUNHAUS device drivers — adds the shared simulated clock.

    Subclasses set ``device_type`` and implement ``@rpc`` / ``@emit`` /
    ``@periodic`` / ``@on`` behaviors. Read the current simulated hour with
    ``self.clock.sim_hour()`` inside any of them.
    """

    def __init__(self) -> None:
        super().__init__()
        self.clock = SimClock.from_env()


def run_device(driver: DeviceDriver, device_id: str) -> None:
    """Run one device process until interrupted. Blocks.

    Selects Zenoh D2D automatically (no ``messaging_urls``); honors
    ``ZENOH_CONNECT`` + ``DEVICE_CONNECT_DISCOVERY_MODE=d2d`` for the
    local-router fallback on locked-down networks.
    """
    os.environ.setdefault("DEVICE_CONNECT_ALLOW_INSECURE", "true")

    async def _main() -> None:
        runtime = DeviceRuntime(driver=driver, device_id=device_id, allow_insecure=True)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        try:
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows ProactorEventLoop
            signal.signal(signal.SIGINT, lambda *_: stop.set())

        task = asyncio.create_task(runtime.run())
        try:
            # On Windows, Ctrl+C sometimes only wakes the loop on the next
            # timer tick, so poll rather than bare `await stop.wait()`.
            while not stop.is_set() and not task.done():
                await asyncio.sleep(0.2)
        finally:
            await runtime.stop()
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
