"""ORM models. Monetary values are floats (prices); returns are stored as fractions."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (JSON, BigInteger, Boolean, Double, ForeignKey, Index, Integer, SmallInteger,
                        String, Text)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, UTCDateTime

BigId = BigInteger().with_variant(Integer, "sqlite")  # SQLite autoincrements INTEGER only


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Candle(Base):
    __tablename__ = "candles"

    symbol: Mapped[str] = mapped_column(String(24), primary_key=True)
    interval: Mapped[str] = mapped_column(String(8), primary_key=True)
    open_time: Mapped[datetime] = mapped_column(UTCDateTime, primary_key=True)
    open: Mapped[float] = mapped_column(Double)
    high: Mapped[float] = mapped_column(Double)
    low: Mapped[float] = mapped_column(Double)
    close: Mapped[float] = mapped_column(Double)
    volume: Mapped[float] = mapped_column(Double)
    quote_volume: Mapped[float] = mapped_column(Double)
    trades: Mapped[int] = mapped_column(BigInteger)
    taker_buy_base: Mapped[float] = mapped_column(Double)
    taker_buy_quote: Mapped[float] = mapped_column(Double)


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (
        Index("ix_signals_status_strategy_symbol", "status", "strategy", "symbol"),
        Index("ix_signals_exit_at", "exit_at"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    uid: Mapped[str] = mapped_column(String(80), unique=True)  # strategy:symbol:signal-candle-open
    origin: Mapped[str] = mapped_column(String(10), default="live")  # live | demo | backfill
    strategy: Mapped[str] = mapped_column(String(16), index=True)
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    side: Mapped[int] = mapped_column(SmallInteger)  # +1 long, -1 short

    signal_open_at: Mapped[datetime] = mapped_column(UTCDateTime)
    entry_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)  # signal candle close
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    entry_price: Mapped[float] = mapped_column(Double)
    take_profit: Mapped[float] = mapped_column(Double)
    stop_loss: Mapped[float] = mapped_column(Double)
    atr: Mapped[float] = mapped_column(Double)
    tp_atr: Mapped[float] = mapped_column(Double)
    sl_atr: Mapped[float] = mapped_column(Double)
    max_bars: Mapped[int] = mapped_column(Integer)
    regime_coin: Mapped[int] = mapped_column(SmallInteger)
    regime_btc: Mapped[int] = mapped_column(SmallInteger)
    model_prob: Mapped[float | None] = mapped_column(Double, nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(40), nullable=True)

    mode: Mapped[str] = mapped_column(String(8))           # strategy mode at creation
    published: Mapped[bool] = mapped_column(Boolean, index=True)  # pushed to Telegram / live book

    status: Mapped[str] = mapped_column(String(8), default="ACTIVE")  # ACTIVE | CLOSED
    exit_reason: Mapped[str | None] = mapped_column(String(8), nullable=True)  # TP | SL | TIME
    exit_price: Mapped[float | None] = mapped_column(Double, nullable=True)
    exit_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    pnl_gross: Mapped[float | None] = mapped_column(Double, nullable=True)
    pnl_net: Mapped[float | None] = mapped_column(Double, nullable=True)
    r_multiple: Mapped[float | None] = mapped_column(Double, nullable=True)
    mfe: Mapped[float] = mapped_column(Double, default=0.0)
    mae: Mapped[float] = mapped_column(Double, default=0.0)
    last_price: Mapped[float | None] = mapped_column(Double, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, index=True)


class StrategyState(Base):
    __tablename__ = "strategy_state"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    mode: Mapped[str] = mapped_column(String(8))  # live | shadow | off
    auto_paused: Mapped[bool] = mapped_column(Boolean, default=False)
    pause_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class SystemState(Base):
    __tablename__ = "system_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class EngineEvent(Base):
    __tablename__ = "engine_events"

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    level: Mapped[str] = mapped_column(String(8))
    kind: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class TelegramSubscriber(Base):
    __tablename__ = "telegram_subscribers"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class TelegramOutbox(Base):
    __tablename__ = "telegram_outbox"
    __table_args__ = (Index("ix_telegram_outbox_status_next", "status", "next_attempt_at"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    chat_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))  # signal_new | signal_close | digest | notice | test
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id", ondelete="SET NULL"),
                                                  nullable=True, index=True)
    text: Mapped[str] = mapped_column(Text)
    reply_markup: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(8), default="pending")  # pending | sent | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
