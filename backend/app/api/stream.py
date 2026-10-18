"""Server-Sent Events: one DB poller per API process fans changes out to every connected client.

Events: `signal` (a published signal was created or changed), `prices`, `heartbeat`, `regime`.
Polling the database (every 2 s) keeps the API stateless and works on any SQL backend.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from .. import db
from ..models import Signal, SystemState
from .serialize import signal_out

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _json(obj) -> str:
    return json.dumps(obj, default=lambda o: o.isoformat() if isinstance(o, datetime) else str(o))


class Broadcaster:
    def __init__(self, interval: float = 2.0):
        self.interval = interval
        self.clients: set[asyncio.Queue] = set()
        self._task: asyncio.Task | None = None
        self._cursor = datetime.now(timezone.utc)
        self._state_seen: dict[str, datetime] = {}

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self.clients.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.clients.discard(q)

    def publish(self, event: str, data) -> None:
        msg = f"event: {event}\ndata: {_json(data)}\n\n"
        for q in list(self.clients):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:  # slow client: drop it, the browser reconnects
                self.clients.discard(q)

    async def _run(self) -> None:
        while True:
            try:
                if self.clients:
                    await self._poll()
            except Exception:  # noqa: BLE001
                log.exception("stream poll failed")
            await asyncio.sleep(self.interval)

    async def _poll(self) -> None:
        async with db.sessions()() as s:
            rows = (await s.scalars(select(Signal).where(Signal.updated_at > self._cursor,
                                                         Signal.published.is_(True))
                                    .order_by(Signal.updated_at).limit(200))).all()
            for r in rows:
                self.publish("signal", signal_out(r))
                self._cursor = max(self._cursor, r.updated_at)
            states = (await s.scalars(select(SystemState).where(
                SystemState.key.in_(["prices", "heartbeat", "regime"])))).all()
            for st in states:
                if self._state_seen.get(st.key) != st.updated_at:
                    self._state_seen[st.key] = st.updated_at
                    self.publish(st.key, st.value)


broadcaster = Broadcaster()


@router.get("/stream")
async def stream(request: Request):
    q = broadcaster.subscribe()

    async def gen():
        try:
            yield "retry: 5000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    yield await asyncio.wait_for(q.get(), timeout=20)
                except TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            broadcaster.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
