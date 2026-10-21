from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import select

from app import db
from app.engine.forming import STATE_KEY, review_forming
from app.models import TelegramOutbox
from app.services import repo

from .test_risk import guarded, ladder  # noqa: F401 - fixture

THR = 0.884
LIVE = SimpleNamespace(mode="live", auto_paused=False)
DAY = datetime(2026, 10, 19, tzinfo=timezone.utc)
AT_0930, AT_1330, AT_1730 = (DAY + timedelta(hours=h) for h in (4, 8, 12))  # 4H closes, in IST


def scores(best=0.880, side=-1):
    return [("XRPUSDT", side, best), ("SOLUSDT", 1, 0.70), ("DOTUSDT", -1, 0.85)]


async def notes(s) -> list[TelegramOutbox]:
    return (await s.scalars(select(TelegramOutbox).where(TelegramOutbox.kind == "watch"))).all()


async def test_setup_forming_note(guarded):  # noqa: F811
    settings, svc, _ = guarded
    session = svc.style.session

    async def review(s, at, sc=None, state=LIVE, cfg=settings):
        return await review_forming(s, cfg, session, svc, at, scores() if sc is None else sc, THR, state)

    async with db.sessions()() as s:
        assert not await review(s, AT_1330, scores(0.878))           # 0.006 below the threshold
        assert not await review(s, AT_1730)                           # too late: one check left today
        assert not await review(s, DAY)                               # 05:30 AM: outside the session
        assert not await review(s, AT_1330, state=SimpleNamespace(mode="shadow", auto_paused=False))
        assert not await review(s, AT_1330, state=SimpleNamespace(mode="live", auto_paused=True))
        assert not await review(s, AT_1330, cfg=settings.model_copy(update={"telegram_watch_messages": False}))
        await repo.set_state(s, "publishing", {"paused": True})
        assert not await review(s, AT_1330)
        await repo.set_state(s, "publishing", {"paused": False})
        assert await notes(s) == []

        assert await review(s, AT_1330)
        assert not await review(s, AT_1330, scores(0.95))              # once a day
        rows = await notes(s)
        assert len(rows) == 1 and rows[0].chat_id == "@signals" and rows[0].silent
        text = rows[0].text
        assert text.startswith("👀 <b>Setup forming</b>")
        assert "close to a signal after the 01:30 PM check, leaning <b>SHORT</b>" in text
        assert "Not a signal yet — please don't enter early." in text
        assert text.endswith("Next checks today: 05:30 PM · 09:30 PM")
        assert (await repo.get_state(s, STATE_KEY))["day"] == "2026-10-19"

        # next day: a signal already posted at 09:30 → no note at 13:30
        s.add(ladder(id=None, uid="RSR-4H:SOLUSDT:d2", entry_at=AT_0930 + timedelta(days=1)))
        await s.flush()
        assert not await review(s, AT_1330 + timedelta(days=1))
        # the day after: the 09:30 check qualifies, leaning LONG
        assert await review(s, AT_0930 + timedelta(days=2), scores(0.884, side=1))
        assert "after the 09:30 AM check, leaning <b>LONG</b>" in (await notes(s))[-1].text
        assert "Next checks today: 01:30 PM · 05:30 PM · 09:30 PM" in (await notes(s))[-1].text
