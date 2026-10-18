from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.core.session import Session

IST = Session(ZoneInfo("Asia/Kolkata"), time(9), time(23))


def utc(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


@pytest.mark.parametrize("t,inside", [("2026-10-18T03:29", False), ("2026-10-18T03:30", True),  # 08:59 / 09:00 IST
                                      ("2026-10-18T17:29", True), ("2026-10-18T17:30", False)])  # 22:59 / 23:00 IST
def test_session_boundaries(t, inside):
    assert IST.contains(utc(t)) is inside


def test_publishing_candles_are_the_four_inside_closes():
    closes = IST.checks(date(2026, 10, 18))
    assert [IST.label(t, with_date=False) for t in closes] == ["09:30 AM", "01:30 PM", "05:30 PM", "09:30 PM"]
    assert not IST.contains(utc("2026-10-18T20:00")) and not IST.contains(utc("2026-10-19T00:00"))  # 01:30, 05:30


def test_next_and_last_boundaries():
    noon = utc("2026-10-18T06:30")  # 12:00 IST
    assert IST.last_start(noon) == utc("2026-10-18T03:30") and IST.next_end(noon) == utc("2026-10-18T17:30")
    assert IST.next_start(noon) == utc("2026-10-19T03:30") and IST.last_end(noon) == utc("2026-10-17T17:30")
    assert IST.label(noon) == "18 Oct 2026, 12:00 PM IST"


def test_overnight_session_and_settings():
    night = Session(ZoneInfo("UTC"), time(22), time(6))
    assert night.contains(utc("2026-10-18T23:00")) and night.contains(utc("2026-10-19T05:59"))
    assert not night.contains(utc("2026-10-19T06:00"))
    with pytest.raises(ValueError):
        Settings(session_start="9am", environment="test")
    assert Session.from_settings(Settings(environment="test")) == IST
