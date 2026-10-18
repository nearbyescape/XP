"""Minimal async client for the Telegram Bot API (token from @BotFather)."""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)


class TelegramError(Exception):
    def __init__(self, code: int, description: str, retry_after: int | None = None):
        super().__init__(f"{code}: {description}")
        self.code = code
        self.description = description
        self.retry_after = retry_after

    @property
    def blocked(self) -> bool:
        """The user blocked the bot / chat is gone: stop sending there."""
        return self.code == 403 or "chat not found" in self.description.lower()

    @property
    def not_modified(self) -> bool:
        return "message is not modified" in self.description.lower()


class TelegramClient:
    def __init__(self, token: str, base_url: str = "https://api.telegram.org",
                 http: httpx.AsyncClient | None = None):
        self._url = f"{base_url.rstrip('/')}/bot{token}/"
        self.http = http or httpx.AsyncClient(timeout=httpx.Timeout(40.0, connect=10.0))

    async def close(self) -> None:
        await self.http.aclose()

    async def call(self, method: str, **params):
        payload = {k: v for k, v in params.items() if v is not None}
        try:
            r = await self.http.post(self._url + method, json=payload)
        except httpx.HTTPError as exc:
            raise TelegramError(0, f"network: {exc.__class__.__name__}") from exc
        try:
            body = r.json()
        except ValueError:
            raise TelegramError(r.status_code, r.text[:200]) from None
        if not body.get("ok"):
            retry = (body.get("parameters") or {}).get("retry_after")
            raise TelegramError(body.get("error_code", r.status_code), body.get("description", ""), retry)
        return body["result"]

    async def get_me(self) -> dict:
        return await self.call("getMe")

    async def send_message(self, chat_id: str | int, text: str, reply_markup: dict | None = None,
                           reply_to_message_id: int | None = None) -> dict:
        reply = ({"message_id": reply_to_message_id, "allow_sending_without_reply": True}
                 if reply_to_message_id else None)
        return await self.call("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML",
                               reply_markup=reply_markup, reply_parameters=reply,
                               link_preview_options={"is_disabled": True})

    async def edit_message_text(self, chat_id: str | int, message_id: int, text: str,
                                reply_markup: dict | None = None) -> dict:
        return await self.call("editMessageText", chat_id=chat_id, message_id=message_id, text=text,
                               parse_mode="HTML", reply_markup=reply_markup,
                               link_preview_options={"is_disabled": True})

    async def get_updates(self, offset: int | None, timeout: int = 25) -> list[dict]:
        return await self.call("getUpdates", offset=offset, timeout=timeout,
                               allowed_updates=["message"])

    async def set_my_commands(self, commands: list[tuple[str, str]]) -> None:
        await self.call("setMyCommands",
                        commands=[{"command": c, "description": d} for c, d in commands])
