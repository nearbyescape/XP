"""Telegram delivery: outbox (persisted, retried, rate limited), bot commands, session messages.

Every message goes through the `telegram_outbox` table first, so a Telegram outage or an engine
restart never loses a signal; delivery resumes where it stopped. Channel posts are paced to
Telegram's ~20 messages/minute group limit; private chats to ~25 messages/second overall.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta

from sqlalchemy import desc, func, select, update

from .. import db
from ..config import Settings
from ..core import stats
from ..core.position import events
from ..core.risk import exposure
from ..engine.clock import Clock
from ..models import Signal, TelegramOutbox, TelegramSubscriber, utcnow
from ..services import control, repo
from . import formatting as fmt
from .client import TelegramClient, TelegramError

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 6
GROUP_GAP = 3.1      # seconds between messages to the same group/channel
PRIVATE_GAP = 0.05   # seconds between messages to the same private chat
GLOBAL_GAP = 0.04
ALERT_COOLDOWN = 1800  # seconds between two admin alerts of the same kind


def is_group(chat_id: str) -> bool:
    return chat_id.startswith(("-", "@"))


class TelegramService:
    def __init__(self, settings: Settings, clock: Clock, client: TelegramClient | None = None):
        self.settings = settings
        self.clock = clock
        self.client = client
        if self.client is None and settings.telegram_enabled:
            self.client = TelegramClient(settings.telegram_bot_token.get_secret_value(),
                                         settings.telegram_api_base)
        self._last_sent: dict[str, float] = {}
        self._last_global = 0.0
        self._alerted: dict[str, float] = {}
        self.bot_username: str | None = None
        self.style = fmt.Style.from_settings(settings)

    def _quiet(self, at: datetime) -> bool:
        """Updates for events outside the publishing session arrive without sound. Judged by when the
        event happened, so an update processed a little late keeps its daytime / night-time status."""
        return self.settings.overnight_updates == "silent" and not self.style.session.contains(at)

    @property
    def site_url(self) -> str | None:
        """Website address for "Open signal" buttons; none while the site is private (login only)."""
        return None if self.settings.site_private else self.settings.public_base_url

    @property
    def enabled(self) -> bool:
        return self.client is not None

    # ---------------------------------------------------------------- enqueue (engine side)
    async def _targets(self, s) -> list[str]:
        chats = []
        if self.settings.telegram_channel_id:
            chats.append(self.settings.telegram_channel_id)
        if self.settings.telegram_dm_enabled:
            rows = await s.scalars(select(TelegramSubscriber.chat_id).where(TelegramSubscriber.active.is_(True)))
            chats += [str(c) for c in rows.all()]
        return chats

    async def enqueue_signal_new(self, s, sig: Signal) -> None:
        if not self.enabled or not sig.published:
            return
        text = fmt.new_signal(sig, self.style)
        kb = fmt.signal_keyboard(self.site_url, sig.id)
        for chat in await self._targets(s):
            s.add(TelegramOutbox(chat_id=chat, kind="signal_new", signal_id=sig.id, text=text,
                                 reply_markup=kb, next_attempt_at=utcnow()))

    async def _follow_up(self, s, sig: Signal, kind: str, text: str, at: datetime) -> None:
        """Reply in every chat that received the original signal, and edit the original there."""
        if not self.enabled or not sig.published:
            return
        chats = (await s.scalars(select(TelegramOutbox.chat_id).where(
            TelegramOutbox.signal_id == sig.id, TelegramOutbox.kind == "signal_new",
            TelegramOutbox.status.in_(["sent", "pending"])))).all()
        kb = fmt.signal_keyboard(self.site_url, sig.id)
        silent = self._quiet(at)
        for chat in dict.fromkeys(chats):
            s.add(TelegramOutbox(chat_id=chat, kind="signal_edit", signal_id=sig.id,
                                 text=fmt.edited_original(sig, self.style),
                                 reply_markup=kb, next_attempt_at=utcnow()))
            s.add(TelegramOutbox(chat_id=chat, kind=kind, signal_id=sig.id, text=text, silent=silent,
                                 next_attempt_at=utcnow()))

    async def enqueue_signal_update(self, s, sig: Signal, hit_before: int) -> None:
        """TP1 / TP2 filled while part of the position is still open."""
        at = datetime.fromisoformat(sig.fills[-1][0]) if sig.fills else self.clock.now()
        await self._follow_up(s, sig, "signal_update", fmt.target_update(sig, hit_before), at)

    async def enqueue_signal_close(self, s, sig: Signal, hit_before: int | None = None) -> None:
        await self._follow_up(s, sig, "signal_close", fmt.close_signal(sig, hit_before),
                              sig.exit_at or self.clock.now())

    async def enqueue_notice(self, s, text: str, chat_id: str | None = None, kind: str = "notice") -> None:
        if not self.enabled:
            return
        chat = chat_id or self.settings.telegram_channel_id
        if chat:
            s.add(TelegramOutbox(chat_id=chat, kind=kind, text=text, next_attempt_at=utcnow()))

    async def enqueue_admin(self, s, text: str, key: str | None = None) -> bool:
        """Ops alert to TELEGRAM_ADMIN_CHAT_IDS. Alerts sharing a key are throttled."""
        if not self.enabled or not self.settings.admin_chats:
            return False
        now = time.monotonic()
        if key:
            if key in self._alerted and now - self._alerted[key] < ALERT_COOLDOWN:
                return False
            self._alerted[key] = now
        for chat in self.settings.admin_chats:
            s.add(TelegramOutbox(chat_id=chat, kind="alert", text=text, next_attempt_at=utcnow()))
        return True

    # ---------------------------------------------------------------- sender
    async def _pace(self, chat: str) -> None:
        gap = GROUP_GAP if is_group(chat) else PRIVATE_GAP
        wait = max(self._last_sent.get(chat, 0) + gap, self._last_global + GLOBAL_GAP) - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)

    async def _original_message_id(self, s, row: TelegramOutbox) -> int | None:
        return await s.scalar(select(TelegramOutbox.message_id).where(
            TelegramOutbox.signal_id == row.signal_id, TelegramOutbox.chat_id == row.chat_id,
            TelegramOutbox.kind == "signal_new", TelegramOutbox.status == "sent"))

    async def deliver(self, s, row: TelegramOutbox) -> None:
        await self._pace(row.chat_id)
        try:
            if row.kind in ("signal_edit", "signal_update", "signal_close"):
                original = await self._original_message_id(s, row)
                if original is None:
                    # the original is still queued: try again shortly (never reorder results first)
                    pending = await s.scalar(select(func.count()).select_from(TelegramOutbox).where(
                        TelegramOutbox.signal_id == row.signal_id, TelegramOutbox.chat_id == row.chat_id,
                        TelegramOutbox.kind == "signal_new", TelegramOutbox.status == "pending"))
                    if pending:
                        row.next_attempt_at = utcnow() + timedelta(seconds=5)
                        return
                if row.kind == "signal_edit":
                    if original is None:
                        row.status, row.error = "skipped", "original not delivered"
                        return
                    try:
                        await self.client.edit_message_text(row.chat_id, original, row.text, row.reply_markup)
                    except TelegramError as exc:
                        if not exc.not_modified:
                            raise
                    row.message_id = original
                else:
                    res = await self.client.send_message(row.chat_id, row.text, row.reply_markup, original,
                                                         silent=row.silent)
                    row.message_id = res["message_id"]
            else:
                res = await self.client.send_message(row.chat_id, row.text, row.reply_markup, silent=row.silent)
                row.message_id = res["message_id"]
            row.status, row.sent_at, row.error = "sent", utcnow(), None
            if row.kind == "rules":
                await self._pin(s, row)
        except TelegramError as exc:
            row.attempts += 1
            row.error = str(exc)[:500]
            if exc.blocked and not is_group(row.chat_id):
                row.status = "failed"
                await s.execute(update(TelegramSubscriber).where(
                    TelegramSubscriber.chat_id == int(row.chat_id)).values(active=False, updated_at=utcnow()))
            elif row.attempts >= MAX_ATTEMPTS or exc.code == 400:
                row.status = "failed"
                log.error("telegram delivery failed for outbox %s: %s", row.id, exc)
                if row.kind != "alert" and row.chat_id not in self.settings.admin_chats:
                    await self.enqueue_admin(s, fmt.alert(
                        self.settings.app_name, "error", "telegram.failed",
                        f"{row.kind} to {row.chat_id} failed after {row.attempts} attempt(s): {exc}"),
                        key=f"telegram.failed:{row.chat_id}")
            else:
                backoff = exc.retry_after or min(300, 2 ** row.attempts * 5)
                row.next_attempt_at = utcnow() + timedelta(seconds=backoff)
        finally:
            self._last_sent[row.chat_id] = time.monotonic()
            self._last_global = time.monotonic()

    async def _pin(self, s, row: TelegramOutbox) -> None:
        """Pin the member rules in the channel. The bot needs the 'pin messages' admin right; without it
        the rules stay posted and the administrators are told."""
        try:
            await self.client.pin_chat_message(row.chat_id, row.message_id)
        except TelegramError as exc:
            row.error = f"posted, not pinned: {exc}"[:500]
            await self.enqueue_admin(s, fmt.alert(
                self.settings.app_name, "warning", "telegram.pin",
                f"Rules posted in {row.chat_id} but not pinned ({exc}). In a channel the bot needs 'Edit "
                "messages of others' to pin (in a group: 'Pin messages'); or pin the message by hand."))

    async def sender_loop(self) -> None:
        while True:
            try:
                async with db.sessions()() as s:
                    rows = (await s.scalars(select(TelegramOutbox).where(
                        TelegramOutbox.status == "pending", TelegramOutbox.next_attempt_at <= utcnow())
                        .order_by(TelegramOutbox.id).limit(25))).all()
                    for row in rows:
                        await self.deliver(s, row)
                        await s.commit()
            except Exception:  # noqa: BLE001 - keep the loop alive, errors are logged
                log.exception("telegram sender loop error")
            await asyncio.sleep(1.0)

    # ---------------------------------------------------------------- bot commands
    async def handle_message(self, s, msg: dict) -> str | None:
        chat = msg.get("chat", {})
        text = (msg.get("text") or "").strip()
        if chat.get("type") != "private" or not text.startswith("/"):
            return None
        cmd = text.split()[0].split("@")[0].lower()
        chat_id = int(chat["id"])
        if cmd == "/id":
            return f"Your chat id: <code>{chat_id}</code>"
        admin = str(chat_id) in self.settings.admin_chats
        if cmd == "/status" and admin:
            return fmt.status(await repo.get_state(s, "heartbeat", {}), await repo.get_state(s, "last_eval", {}),
                              await repo.strategy_states(s), len(await repo.open_signals(s)),
                              await self.queue_health(s), await repo.publishing(s),
                              await repo.get_state(s, "risk_watch", {}), self.style.session)
        if cmd in ("/pause", "/resume") and admin:
            who = f"@{chat['username']}" if chat.get("username") else f"chat {chat_id}"
            changed = await control.set_publishing(s, self.settings, cmd == "/pause", who)
            await s.commit()
            if cmd == "/pause":
                return ("⏸️ New signals paused. Open signals are still tracked and updated. /resume to restart."
                        if changed else "New signals are already paused. /resume to restart.")
            return "▶️ New signals resumed from the next check." if changed else "New signals are not paused."
        if cmd == "/rules":
            return fmt.rules(self.style)
        sub = await s.get(TelegramSubscriber, chat_id)

        async def set_active(active: bool):
            nonlocal sub
            if sub is None:
                sub = TelegramSubscriber(chat_id=chat_id, username=chat.get("username"),
                                         first_name=chat.get("first_name"), active=active)
                s.add(sub)
            else:
                sub.active, sub.username = active, chat.get("username")
            await s.commit()

        if cmd == "/start":
            await set_active(self.settings.telegram_dm_enabled)
            ses, now = self.style.session, self.clock.now()
            hours = f"{ses.label(ses.next_start(now), False)} – {ses.label(ses.next_end(now), False)} {ses.tzname(now)}"
            return fmt.welcome(self.settings.app_name, self.settings.telegram_channel_url,
                               self.settings.telegram_dm_enabled, hours)
        if cmd == "/subscribe":
            if not self.settings.telegram_dm_enabled:
                return "Private delivery is disabled. Follow the channel for signals."
            await set_active(True)
            return "✅ Subscribed. New signals and their results will arrive in this chat."
        if cmd == "/unsubscribe":
            await set_active(False)
            return "Unsubscribed. Send /subscribe any time to resume."
        if cmd == "/signals":
            rows = [r for r in await repo.open_signals(s) if r.published]
            return fmt.open_signals(rows)
        if cmd == "/stats":
            now = self.clock.now()
            recent = await repo.closed_signals(s, since=now - timedelta(days=30))
            every = await repo.closed_signals(s)
            to_dict = lambda rows: [{"exit_at": r.exit_at, "pnl_net": r.pnl_net, "r_multiple": r.r_multiple,  # noqa: E731
                                     "exit_reason": r.exit_reason} for r in rows]
            return (fmt.kpi_block("Last 30 days", stats.kpis(to_dict(recent))) + "\n\n"
                    + fmt.kpi_block("All time", stats.kpis(to_dict(every))))
        if cmd == "/regime":
            return fmt.regime(await repo.get_state(s, "regime", {}))
        return fmt.HELP

    async def updates_loop(self) -> None:
        offset = None
        try:
            me = await self.client.get_me()
            self.bot_username = me.get("username")
            await self.client.set_my_commands(fmt.COMMANDS)
            async with db.sessions()() as s:
                await repo.set_state(s, "telegram", {"bot": self.bot_username, "ok": True, "at": utcnow().isoformat()})
                await s.commit()
        except TelegramError as exc:
            log.error("telegram bot init failed: %s", exc)
            async with db.sessions()() as s:
                await repo.set_state(s, "telegram", {"bot": None, "ok": False, "error": str(exc),
                                                     "at": utcnow().isoformat()})
                await s.commit()
        while True:
            try:
                updates = await self.client.get_updates(offset, timeout=25)
                for u in updates:
                    offset = u["update_id"] + 1
                    msg = u.get("message")
                    if not msg:
                        continue
                    async with db.sessions()() as s:
                        reply = await self.handle_message(s, msg)
                        if reply:
                            s.add(TelegramOutbox(chat_id=str(msg["chat"]["id"]), kind="reply", text=reply,
                                                 next_attempt_at=utcnow()))
                            await s.commit()
            except TelegramError as exc:
                log.warning("telegram getUpdates failed: %s", exc)
                await asyncio.sleep(exc.retry_after or 5)
            except Exception:  # noqa: BLE001
                log.exception("telegram updates loop error")
                await asyncio.sleep(5)

    # ---------------------------------------------------------------- session messages
    async def session_loop(self) -> None:
        """Greeting at the session start, summary at the session end (a boundary missed by more
        than 15 minutes, e.g. during a restart, is skipped rather than sent late)."""
        ses = self.style.session
        while True:
            now = self.clock.now()
            for kind, at in (("start", ses.last_start(now)), ("end", ses.last_end(now))):
                if now - at <= timedelta(minutes=15):
                    await self._session_message(kind, at)
            nxt = min(ses.next_start(now), ses.next_end(now))
            await self.clock.sleep_until(nxt + timedelta(seconds=1))

    async def _session_message(self, kind: str, at: datetime) -> None:
        try:
            async with db.sessions()() as s:
                sent = await repo.get_state(s, "session_messages", {})
                if sent.get(kind) == at.isoformat():
                    return  # already sent (restart inside the 15-minute window)
                text = await (self.session_start_text(s, at) if kind == "start" else self.session_end_text(s, at))
                await self.enqueue_notice(s, text, kind=f"session_{kind}")
                await repo.set_state(s, "session_messages", {**sent, kind: at.isoformat()})
                await s.commit()
        except Exception:  # noqa: BLE001
            log.exception("session %s message failed", kind)

    async def _window(self, s, since: datetime, until: datetime):
        """Published signals with activity in [since, until) and their target / stop events there."""
        rows = (await s.scalars(select(Signal).where(
            Signal.published.is_(True), Signal.entry_at < until,
            (Signal.status == "ACTIVE") | (Signal.exit_at >= since)).order_by(Signal.entry_at))).all()
        evs = sorted(((kind, t, r) for r in rows for kind, t in events(r) if since <= t < until),
                     key=lambda e: e[1])
        return rows, evs

    async def _k30(self, s, now: datetime) -> dict:
        recent = await repo.closed_signals(s, since=now - timedelta(days=30))
        return stats.kpis([{"exit_at": r.exit_at, "pnl_net": r.pnl_net, "r_multiple": r.r_multiple,
                            "exit_reason": r.exit_reason} for r in recent])

    async def session_start_text(self, s, now: datetime) -> str:
        ses = self.style.session
        rows, overnight = await self._window(s, ses.last_end(now), now)
        open_rows = [r for r in rows if r.status == "ACTIVE"]
        return fmt.session_start(now, self.style, await repo.get_state(s, "regime", {}), open_rows, overnight,
                                 await self._k30(s, now), exposure(open_rows, self.style.risk_pct),
                                 bool((await repo.publishing(s)).get("paused")))

    async def session_end_text(self, s, now: datetime) -> str:
        since = now - timedelta(days=1)  # the day since the previous summary
        rows, evs = await self._window(s, since, now)
        published = [r for r in rows if r.entry_at >= since]
        closed = sorted((r for r in rows if r.status == "CLOSED" and r.exit_at >= since), key=lambda r: r.exit_at)
        open_rows = [r for r in rows if r.status == "ACTIVE"]
        return fmt.session_end(now, self.style, published, evs, closed, open_rows, await self._k30(s, now),
                               exposure(open_rows, self.style.risk_pct),
                               bool((await repo.publishing(s)).get("paused")))

    async def queue_health(self, s) -> dict:
        pending = await s.scalar(select(func.count()).select_from(TelegramOutbox)
                                 .where(TelegramOutbox.status == "pending"))
        failed = await s.scalar(select(func.count()).select_from(TelegramOutbox)
                                .where(TelegramOutbox.status == "failed"))
        last = await s.scalar(select(TelegramOutbox.sent_at).where(TelegramOutbox.status == "sent")
                              .order_by(desc(TelegramOutbox.sent_at)).limit(1))
        return {"pending": pending, "failed": failed, "last_sent_at": last.isoformat() if last else None}
