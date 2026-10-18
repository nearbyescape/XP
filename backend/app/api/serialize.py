"""Response shaping. Percent fields (suffix _pct) are percentages; R values are multiples."""

from __future__ import annotations

from ..core.catalog import STRATEGIES
from ..models import Signal


def _pct(x: float | None) -> float | None:
    return None if x is None else round(x * 100, 4)


def signal_out(s: Signal) -> dict:
    tp_pct = abs(s.take_profit / s.entry_price - 1)
    sl_pct = abs(s.stop_loss / s.entry_price - 1)
    live = s.exit_price if s.status == "CLOSED" else (s.last_price or s.entry_price)
    unreal = s.side * (live / s.entry_price - 1) if live else None
    # position of the live price on the SL (0) → entry → TP (1) scale
    span = s.take_profit - s.stop_loss
    progress = None if not span or live is None else max(0.0, min(1.0, (live - s.stop_loss) / span))
    spec = STRATEGIES.get(s.strategy)
    return {
        "id": s.id, "uid": s.uid, "origin": s.origin, "strategy": s.strategy,
        "strategy_name": spec.name if spec else s.strategy,
        "symbol": s.symbol, "side": "LONG" if s.side == 1 else "SHORT",
        "status": s.status, "published": s.published, "mode": s.mode,
        "signal_open_at": s.signal_open_at, "entry_at": s.entry_at, "expires_at": s.expires_at,
        "entry_price": s.entry_price, "take_profit": s.take_profit, "stop_loss": s.stop_loss,
        "atr": s.atr, "tp_atr": s.tp_atr, "sl_atr": s.sl_atr, "max_bars": s.max_bars,
        "tp_pct": _pct(tp_pct), "sl_pct": _pct(sl_pct), "reward_risk": round(tp_pct / sl_pct, 3) if sl_pct else None,
        "regime_coin": s.regime_coin, "regime_btc": s.regime_btc,
        "model_prob": s.model_prob, "model_version": s.model_version,
        "exit_reason": s.exit_reason, "exit_price": s.exit_price, "exit_at": s.exit_at,
        "pnl_gross_pct": _pct(s.pnl_gross), "pnl_net_pct": _pct(s.pnl_net), "r_multiple": s.r_multiple,
        "mfe_pct": _pct(s.mfe), "mae_pct": _pct(s.mae),
        "last_price": live, "unrealized_pct": _pct(unreal) if s.status == "ACTIVE" else None,
        "progress": progress, "last_checked_at": s.last_checked_at,
        "created_at": s.created_at, "updated_at": s.updated_at,
    }


def kpis_out(k: dict) -> dict:
    out = dict(k)
    for key in ("win_rate", "breakeven_win_rate", "avg_win", "avg_loss", "expectancy"):
        out[key] = _pct(k.get(key))
    return out


CSV_COLUMNS = ["id", "uid", "origin", "strategy", "symbol", "side", "status", "signal_open_at", "entry_at",
               "expires_at", "entry_price", "take_profit", "stop_loss", "tp_pct", "sl_pct", "model_prob",
               "exit_reason", "exit_price", "exit_at", "pnl_gross_pct", "pnl_net_pct", "r_multiple",
               "mfe_pct", "mae_pct"]
