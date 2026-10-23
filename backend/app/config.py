"""Runtime configuration (environment variables, see .env.example at the repo root)."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_UNIVERSE = ("BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT,"
                    "ADAUSDT,DOGEUSDT,AVAXUSDT,LINKUSDT,DOTUSDT")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # --- product ----------------------------------------------------------------------------
    app_name: str = "SignalDesk"
    environment: Literal["production", "staging", "development", "test"] = "production"
    public_base_url: str = "http://localhost:8080"
    log_level: str = "INFO"

    # --- storage ----------------------------------------------------------------------------
    database_url: str = "postgresql+asyncpg://signals:signals@db:5432/signals"

    # --- market data ------------------------------------------------------------------------
    # USDT-M futures by default: subscribers trade the perpetuals. The strategies were validated on
    # Binance spot candles, which the perpetuals track within a few basis points.
    market_data_source: Literal["binance_spot", "binance_futures", "replay"] = "binance_futures"
    binance_spot_urls: str = "https://data-api.binance.vision,https://api.binance.com,https://api1.binance.com"
    binance_futures_urls: str = "https://fapi.binance.com"
    universe: str = DEFAULT_UNIVERSE
    backfill_from: datetime = datetime(2017, 8, 1, tzinfo=timezone.utc)
    eval_delay_seconds: int = 5
    max_signal_latency_minutes: int = 15
    tracker_interval_seconds: int = 60
    price_interval_seconds: int = 15

    # replay (demo / staging): plays stored candles through the live engine on a simulated clock
    replay_data_dir: str = "/data/parquet"
    replay_start: datetime = datetime(2026, 8, 1, tzinfo=timezone.utc)
    replay_speed: float = 600.0  # simulated seconds per real second (600 => one 4h candle / 24 s)

    # --- strategies -------------------------------------------------------------------------
    model_path: str = "/app/models/mlr_4h_tp0.5_sl3.0_b24"
    strategy_modes: str = "RGP-4H=live,RSR-4H=live,MLR-4H=live"  # live | shadow | off
    default_risk_pct: float = 0.5
    cost_entry: float = 0.0007   # taker fee + slippage
    cost_tp: float = 0.0002      # maker fee (take-profit is a resting limit order)
    cost_exit: float = 0.0008    # taker fee + slippage on stops / time exits
    kill_switch_window: int = 150
    kill_switch_min_win_rate: float = 0.82
    kill_switch_min_profit_factor: float = 0.75
    kill_switch_resume_after: int = 50
    kill_switch_resume_profit_factor: float = 1.1

    # --- risk guard (warnings and member guidance; never changes which signals publish) -----
    max_open_risk_pct: float = 5.0         # member rule: total risk across signals still before TP1
    risk_note_signals: int = 10            # signal post notes high open risk from this many before TP1
    watch_drawdown_pct: float = 6.0        # admin alert: published book this far below its peak
    watch_drawdown_critical_pct: float = 10.7  # the worst in 2022-2026 testing
    watch_win_rate_window: int = 30
    watch_win_rate: float = 0.70           # admin alert: a strategy's last 30 signals below this
    watch_win_rate_critical: float = 0.55  # below the worst 30-signal stretch in testing (57%)
    watch_same_direction: int = 12         # admin alert: this many before TP1 in one direction

    # --- telegram (BotFather) ---------------------------------------------------------------
    telegram_bot_token: SecretStr | None = None
    telegram_channel_id: str | None = None      # "@channel" or "-100…"; bot must be a channel admin
    telegram_channel_url: str | None = None     # public invite link shown on the website
    telegram_dm_enabled: bool = False           # also deliver signals to users who /start the bot
    telegram_session_messages: bool = True      # greeting at session start, summary at session end
    # "Setup forming" note when the AI model is within watch_score_margin of a signal at an early check
    telegram_watch_messages: bool = True
    watch_score_margin: float = 0.005
    telegram_api_base: str = "https://api.telegram.org"
    # private chat ids (comma-separated) that receive ops alerts and may use /status; send /id to the bot
    telegram_admin_chat_ids: str = ""

    # --- publishing session ------------------------------------------------------------------
    # Signals whose 4H candle closes inside the session are published; the others are tracked
    # unpublished. Target / stop updates outside the session are sent without sound.
    session_tz: str = "Asia/Kolkata"
    session_start: str = "09:00"
    session_end: str = "23:00"
    entry_window_minutes: int = 15
    overnight_updates: Literal["silent", "loud"] = "silent"

    # --- security ---------------------------------------------------------------------------
    admin_username: str = "admin"
    admin_password: SecretStr | None = None
    secret_key: SecretStr = SecretStr("change-me")
    session_hours: int = 12
    cookie_secure: bool = True
    # false (default) | deindex | true — mirrors the nginx policy; anything but "true" adds noindex
    search_indexing: Literal["false", "deindex", "true"] = "false"
    # true (default): every page and API endpoint needs the admin login, and Telegram posts carry no
    # link to the website. false: the dashboard is readable by anyone with the address.
    site_private: bool = True

    @field_validator("session_start", "session_end")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        datetime.strptime(v, "%H:%M")
        return v

    @field_validator("session_tz")
    @classmethod
    def _tz(cls, v: str) -> str:
        ZoneInfo(v)
        return v

    @field_validator("backfill_from", "replay_start", mode="after")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)

    @property
    def symbols(self) -> list[str]:
        return [s.strip().upper() for s in self.universe.split(",") if s.strip()]

    @property
    def modes(self) -> dict[str, str]:
        out = {}
        for part in self.strategy_modes.split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                out[k.strip().upper()] = v.strip().lower()
        return out

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_bot_token.get_secret_value())

    @property
    def admin_chats(self) -> list[str]:
        return [c.strip() for c in self.telegram_admin_chat_ids.split(",") if c.strip()]

    @property
    def indexing_allowed(self) -> bool:
        return self.search_indexing == "true"

    @property
    def is_replay(self) -> bool:
        return self.market_data_source == "replay"


@lru_cache
def get_settings() -> Settings:
    return Settings()
