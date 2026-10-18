"""Administrator controls shared by the admin console API and the bot's admin commands."""

from __future__ import annotations

from ..config import Settings
from ..models import TelegramOutbox, utcnow
from ..telegram import formatting as fmt
from . import repo


async def set_publishing(s, settings: Settings, paused: bool, by: str) -> bool:
    """Pause or resume all new signals. Open signals keep being tracked and keep their target and
    stop updates. Returns False when nothing changed. Every admin chat is told."""
    if bool((await repo.publishing(s)).get("paused")) == paused:
        return False
    await repo.set_state(s, "publishing", {"paused": paused, "by": by, "at": utcnow().isoformat()})
    kind = "publishing.paused" if paused else "publishing.resumed"
    msg = (f"New signals paused by {by}. Open signals are still tracked and updated." if paused
           else f"New signals resumed by {by}.")
    await repo.log_event(s, "warning" if paused else "info", kind, msg)
    if settings.telegram_enabled:
        for chat in settings.admin_chats:
            s.add(TelegramOutbox(chat_id=chat, kind="alert", next_attempt_at=utcnow(),
                                 text=fmt.alert(settings.app_name, "warning" if paused else "info", kind, msg)))
    return True
