"""Publishing session, e.g. 09:00-23:00 IST.

Signals are published only when their 4H candle closes inside the session; the bot greets the
channel at the session start and sums up the day at the session end.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .catalog import BAR_SECONDS


def _hhmm(v: str) -> time:
    return datetime.strptime(v, "%H:%M").time()


@dataclass(frozen=True)
class Session:
    tz: ZoneInfo
    start: time
    end: time

    @classmethod
    def from_settings(cls, settings) -> Session:
        return cls(ZoneInfo(settings.session_tz), _hhmm(settings.session_start), _hhmm(settings.session_end))

    def local(self, t: datetime) -> datetime:
        return t.astimezone(self.tz)

    def contains(self, t: datetime) -> bool:
        lt = self.local(t).time()
        if self.start <= self.end:
            return self.start <= lt < self.end
        return lt >= self.start or lt < self.end  # a session that runs past midnight

    def _occurrences(self, hm: time, around: datetime) -> list[datetime]:
        d = self.local(around).date()
        return [datetime.combine(d + timedelta(days=k), hm, self.tz).astimezone(timezone.utc)
                for k in (-2, -1, 0, 1, 2)]

    def next_start(self, t: datetime) -> datetime:
        return min(x for x in self._occurrences(self.start, t) if x > t)

    def next_end(self, t: datetime) -> datetime:
        return min(x for x in self._occurrences(self.end, t) if x > t)

    def last_start(self, t: datetime) -> datetime:
        return max(x for x in self._occurrences(self.start, t) if x <= t)

    def last_end(self, t: datetime) -> datetime:
        return max(x for x in self._occurrences(self.end, t) if x <= t)

    def checks(self, day: date | None = None) -> list[datetime]:
        """4H candle closes that fall inside the session on a local day, in session order."""
        day = day or datetime.now(self.tz).date()
        opened = datetime.combine(day, self.start, self.tz).astimezone(timezone.utc)
        length = (self.next_end(opened) - opened)
        first = opened.replace(minute=0, second=0, microsecond=0)
        first -= timedelta(hours=first.hour % (BAR_SECONDS // 3600))
        out, t = [], first
        while t < opened + length:
            if t >= opened:
                out.append(t)
            t += timedelta(seconds=BAR_SECONDS)
        return out

    def label(self, t: datetime, with_date: bool = True) -> str:
        """18 Oct 2026, 09:30 AM IST"""
        lt = self.local(t)
        return f"{lt:%d %b %Y, %I:%M %p} {lt.tzname()}" if with_date else f"{lt:%I:%M %p}"

    def tzname(self, t: datetime | None = None) -> str:
        return self.local(t or datetime.now(timezone.utc)).tzname() or str(self.tz)
