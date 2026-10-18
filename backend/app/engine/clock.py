"""Wall clock for production, accelerated simulated clock for replay demos."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone


class Clock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(max(0.0, seconds))

    async def sleep_until(self, t: datetime) -> None:
        await self.sleep((t - self.now()).total_seconds())

    @property
    def simulated(self) -> bool:
        return False


class SimClock(Clock):
    """Simulated time = start + elapsed real time x speed, frozen at `end`."""

    def __init__(self, start: datetime, speed: float, end: datetime | None = None):
        self.start = start
        self.speed = speed
        self.end = end
        self._t0 = time.monotonic()

    def now(self) -> datetime:
        t = self.start + timedelta(seconds=(time.monotonic() - self._t0) * self.speed)
        return min(t, self.end) if self.end else t

    def jump_to(self, t: datetime) -> None:
        """Continue a previous demo run instead of replaying the same days again."""
        self.start = t
        self._t0 = time.monotonic()

    async def sleep(self, seconds: float) -> None:
        # never spin: at least 0.5 s real time between wake-ups
        await asyncio.sleep(max(0.5, seconds / self.speed))

    @property
    def simulated(self) -> bool:
        return True
