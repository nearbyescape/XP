"""Runtime configuration (environment variables, see .env.example at the repo root)."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from typing import Literal

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
    # binance_spot is the default because every strategy was validated on Binance spot candles.
    market_data_source: Literal["binance_spot", "binance_futures", "replay"] = "binance_spot"
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

    # --- telegram (BotFather) ---------------------------------------------------------------
    telegram_bot_token: SecretStr | None = None
    telegram_channel_id: str | None = None      # "@channel" or "-100…"; bot must be a channel admin
    telegram_channel_url: str | None = None     # public invite link shown on the website
    telegram_dm_enabled: bool = True            # subscribers get signals in a private chat
    telegram_daily_digest: bool = True
    telegram_api_base: str = "https://api.telegram.org"
    # private chat ids (comma-separated) that receive ops alerts and may use /status; send /id to the bot
    telegram_admin_chat_ids: str = ""

    # --- security ---------------------------------------------------------------------------
    admin_username: str = "admin"
    admin_password: SecretStr | None = None
    secret_key: SecretStr = SecretStr("change-me")
    session_hours: int = 12
    cookie_secure: bool = True
    # false (default) | deindex | true — mirrors the nginx policy; anything but "true" adds noindex
    search_indexing: Literal["false", "deindex", "true"] = "false"

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
