"""Admin console API: engine health, strategy modes, Telegram, events, unpublished signals."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings, get_settings
from ..core import stats
from ..core.catalog import STRATEGIES
from ..db import get_session
from ..models import EngineEvent, Signal, StrategyState, TelegramOutbox, TelegramSubscriber, utcnow
from ..services import control, repo
from ..telegram import formatting as fmt
from . import auth
from .public import heartbeat_alive
from .serialize import kpis_out, signal_out

router = APIRouter(prefix="/api/admin")


class Login(BaseModel):
    username: str = Field(max_length=128)
    password: str = Field(max_length=256)


@router.post("/login", status_code=204)
async def login(body: Login, request: Request, response: Response, settings: Settings = Depends(get_settings),
                s: AsyncSession = Depends(get_session)):
    ip = auth.client_ip(request)
    auth.check_rate(ip)
    if not auth.verify_password(settings, body.username, body.password):
        auth.record_failure(ip)
        await repo.log_event(s, "warning", "admin.login_failed", f"failed admin login from {ip}")
        await s.commit()
        raise HTTPException(401, "invalid credentials")
    auth.issue(response, settings, body.username)
    await repo.log_event(s, "info", "admin.login", f"admin signed in from {ip}")
    await s.commit()


@router.post("/logout", status_code=204)
async def logout(response: Response, settings: Settings = Depends(get_settings)):
    auth.clear(response, settings)


@router.get("/me")
async def me(user: str = Depends(auth.require_admin)):
    return {"username": user}


@router.get("/overview")
async def overview(user: str = Depends(auth.require_admin), s: AsyncSession = Depends(get_session),
                   settings: Settings = Depends(get_settings)):
    hb = await repo.get_state(s, "heartbeat") or {}
    alive, age = heartbeat_alive(hb)
    states = await repo.strategy_states(s)
    strategies = []
    for code, spec in STRATEGIES.items():
        st = states.get(code)
        last = (await s.scalars(select(Signal).where(Signal.strategy == code, Signal.status == "CLOSED",
                                                     Signal.origin != "backfill")
                                .order_by(desc(Signal.exit_at)).limit(settings.kill_switch_window))).all()
        health = stats.rolling_health([{"exit_at": r.exit_at, "pnl_net": r.pnl_net, "r_multiple": r.r_multiple,
                                        "exit_reason": r.exit_reason} for r in last])
        counts = dict((await s.execute(select(Signal.status, func.count()).where(Signal.strategy == code)
                                       .group_by(Signal.status))).all())
        strategies.append({
            "code": code, "name": spec.name, "mode": st.mode if st else None,
            "auto_paused": bool(st and st.auto_paused), "pause_reason": st.pause_reason if st else None,
            "paused_at": st.paused_at if st else None,
            "rolling": {**health, "win_rate": None if health["win_rate"] is None else health["win_rate"] * 100,
                        "window": settings.kill_switch_window,
                        "min_win_rate": settings.kill_switch_min_win_rate * 100,
                        "min_profit_factor": settings.kill_switch_min_profit_factor},
            "active": counts.get("ACTIVE", 0), "closed": counts.get("CLOSED", 0),
        })
    subs = await s.scalar(select(func.count()).select_from(TelegramSubscriber)
                          .where(TelegramSubscriber.active.is_(True)))
    queue = dict((await s.execute(select(TelegramOutbox.status, func.count())
                                  .group_by(TelegramOutbox.status))).all())
    events = (await s.scalars(select(EngineEvent).order_by(desc(EngineEvent.id)).limit(60))).all()
    return {
        "engine": {"alive": alive, "heartbeat_age_s": age, **hb},
        "last_eval": await repo.get_state(s, "last_eval"),
        "strategies": strategies,
        "telegram": {"enabled": settings.telegram_enabled, "channel_id": settings.telegram_channel_id,
                     "channel_url": settings.telegram_channel_url, "dm_enabled": settings.telegram_dm_enabled,
                     "bot": await repo.get_state(s, "telegram"), "subscribers": subs, "queue": queue,
                     "admin_chats": len(settings.admin_chats)},
        "events": [{"id": e.id, "ts": e.ts, "level": e.level, "kind": e.kind, "message": e.message}
                   for e in events],
        "publishing": await repo.publishing(s),
        "risk_watch": await repo.get_state(s, "risk_watch") or {},
        "config": {"source": settings.market_data_source, "universe": settings.symbols,
                   "risk_pct": settings.default_risk_pct, "search_indexing": settings.indexing_allowed,
                   "public_base_url": settings.public_base_url},
    }


class StrategyUpdate(BaseModel):
    mode: Literal["live", "shadow", "off"] | None = None
    resume: bool = False  # clear an automatic pause


@router.put("/strategies/{code}")
async def update_strategy(code: str, body: StrategyUpdate, user: str = Depends(auth.require_admin),
                          s: AsyncSession = Depends(get_session)):
    st = await s.get(StrategyState, code.upper())
    if st is None:
        raise HTTPException(404, "unknown strategy")
    changes = []
    if body.mode and body.mode != st.mode:
        changes.append(f"mode {st.mode} → {body.mode}")
        st.mode = body.mode
    if body.resume and st.auto_paused:
        changes.append("automatic pause cleared")
        st.auto_paused, st.pause_reason, st.paused_at = False, None, None
    st.updated_at = utcnow()
    if changes:
        await repo.log_event(s, "warning", "strategy.updated", f"{st.code}: {', '.join(changes)} (by {user})")
    await s.commit()
    return {"code": st.code, "mode": st.mode, "auto_paused": st.auto_paused}


class Publishing(BaseModel):
    paused: bool


@router.put("/publishing")
async def update_publishing(body: Publishing, user: str = Depends(auth.require_admin),
                            s: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)):
    """Pause or resume all new signals (open signals keep their updates)."""
    changed = await control.set_publishing(s, settings, body.paused, user)
    await s.commit()
    return {**(await repo.publishing(s)), "changed": changed}


@router.post("/telegram/rules", status_code=202)
async def telegram_rules(user: str = Depends(auth.require_admin), s: AsyncSession = Depends(get_session),
                         settings: Settings = Depends(get_settings)):
    """Post the member rules in the channel and pin them."""
    if not settings.telegram_enabled:
        raise HTTPException(409, "TELEGRAM_BOT_TOKEN is not configured")
    if not settings.telegram_channel_id:
        raise HTTPException(400, "TELEGRAM_CHANNEL_ID is not set")
    s.add(TelegramOutbox(chat_id=settings.telegram_channel_id, kind="rules", next_attempt_at=utcnow(),
                         text=fmt.rules(fmt.Style.from_settings(settings))))
    await repo.log_event(s, "info", "telegram.rules", f"member rules posted to the channel (by {user})")
    await s.commit()
    return {"queued": True, "chat_id": settings.telegram_channel_id}


class TelegramTest(BaseModel):
    chat_id: str | None = Field(None, max_length=64)


@router.post("/telegram/test", status_code=202)
async def telegram_test(body: TelegramTest, user: str = Depends(auth.require_admin),
                        s: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)):
    if not settings.telegram_enabled:
        raise HTTPException(409, "TELEGRAM_BOT_TOKEN is not configured")
    chat = body.chat_id or settings.telegram_channel_id
    if not chat:
        raise HTTPException(400, "no chat id given and TELEGRAM_CHANNEL_ID is not set")
    s.add(TelegramOutbox(chat_id=chat, kind="test", next_attempt_at=utcnow(),
                         text=f"✅ <b>{settings.app_name}</b> test message — delivery works (sent by {user})."))
    await s.commit()
    return {"queued": True, "chat_id": chat}


@router.get("/signals")
async def all_signals(status: Literal["active", "closed", "all"] = "all", published: bool | None = None,
                      limit: int = Query(100, ge=1, le=500), user: str = Depends(auth.require_admin),
                      s: AsyncSession = Depends(get_session)):
    q = select(Signal)
    if status != "all":
        q = q.where(Signal.status == status.upper())
    if published is not None:
        q = q.where(Signal.published.is_(published))
    rows = (await s.scalars(q.order_by(desc(Signal.id)).limit(limit))).all()
    return [signal_out(r) for r in rows]


@router.get("/stats/shadow")
async def shadow_stats(user: str = Depends(auth.require_admin), s: AsyncSession = Depends(get_session)):
    """Performance of signals that were generated but not published (shadow / paused)."""
    rows = (await s.scalars(select(Signal).where(Signal.status == "CLOSED", Signal.published.is_(False),
                                                 Signal.origin != "backfill"))).all()
    out = {}
    for code in STRATEGIES:
        sel = [{"exit_at": r.exit_at, "pnl_net": r.pnl_net, "r_multiple": r.r_multiple, "exit_reason": r.exit_reason}
               for r in rows if r.strategy == code]
        out[code] = kpis_out(stats.kpis(sel))
    return out
