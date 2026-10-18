"""Build the engine's collaborators from settings."""

from __future__ import annotations

from ..config import Settings
from ..core.ml import MLModel
from ..market.binance import BinanceMarketData
from ..market.replay import ReplayMarketData
from ..telegram.service import TelegramService
from .clock import Clock, SimClock
from .runner import Engine


def build_engine(settings: Settings) -> Engine:
    model = MLModel.try_load(settings.model_path)
    universe = sorted(set(settings.symbols) | {"BTCUSDT"} | (set(model.symbols) if model else set()))
    if settings.is_replay:
        probe = ReplayMarketData(settings.replay_data_dir, Clock(), universe)
        clock: Clock = SimClock(settings.replay_start, settings.replay_speed, end=probe.end_of_data())
        market = ReplayMarketData(settings.replay_data_dir, clock, universe)
    else:
        clock = Clock()
        kind = "futures" if settings.market_data_source == "binance_futures" else "spot"
        urls = settings.binance_futures_urls if kind == "futures" else settings.binance_spot_urls
        market = BinanceMarketData([u.strip() for u in urls.split(",") if u.strip()], kind)
    telegram = TelegramService(settings, clock) if settings.telegram_enabled else None
    return Engine(settings, market, clock, model, telegram)
