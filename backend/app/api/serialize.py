"""Response shaping. Percent fields (suffix _pct) are percentages; R values are multiples."""

from __future__ import annotations

from ..core.catalog import STRATEGIES
from ..models import Signal
from ..core.position import fills_of, open_return, targets_of


def _pct(x: float | None) -> float | None:
    return None if x is None else round(x * 100, 4)


def signal_out(s: Signal) -> dict:
    tp_pct = abs(s.take_profit / s.entry_price - 1)
    sl_pct = abs(s.stop_loss / s.entry_price - 1)
    live = s.exit_price if s.status == "CLOSED" else (s.last_price or s.entry_price)
    unreal = open_return(s, live) if live else None
    targets, fills = targets_of(s), (s.fills or [])
    # position of the live price on the SL (0) → entry → last target (1) scale
    span = targets[-1][0] - s.stop_loss
    progress = None if not span or live is None else max(0.0, min(1.0, (live - s.stop_loss) / span))
    spec = STRATEGIES.get(s.strategy)
    hit_prices = fills_of(s)
    return {
        "id": s.id, "uid": s.uid, "origin": s.origin, "strategy": s.strategy,
        "strategy_name": spec.name if spec else s.strategy,
        "symbol": s.symbol, "side": "LONG" if s.side == 1 else "SHORT",
        "status": s.status, "published": s.published, "mode": s.mode,
        "signal_open_at": s.signal_open_at, "entry_at": s.entry_at, "expires_at": s.expires_at,
        "entry_price": s.entry_price, "take_profit": s.take_profit, "stop_loss": s.stop_loss,
        "stop_current": s.stop_current or s.stop_loss, "breakeven": bool(s.breakeven),
        "targets": [{"n": i + 1, "price": p, "size_pct": round(z * 100, 2),
                     "pct": _pct(abs(p / s.entry_price - 1)),
                     "hit_at": fills[i][0] if i < len(fills) else None,
                     "fill_price": hit_prices[i] if i < len(hit_prices) else None}
                    for i, (p, z) in enumerate(targets)],
        "targets_hit": s.targets_hit or 0, "tp1_at": s.tp1_at,
        "take_profit_2": targets[1][0] if len(targets) > 1 else None,
        "take_profit_3": targets[2][0] if len(targets) > 2 else None,
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
    for key in ("win_rate", "breakeven_win_rate", "avg_win", "avg_loss", "expectancy", "tp1_rate", "tp2_rate",
                "tp3_rate"):
        out[key] = _pct(k.get(key))
    return out


CSV_COLUMNS = ["id", "uid", "origin", "strategy", "symbol", "side", "status", "signal_open_at", "entry_at",
               "expires_at", "entry_price", "take_profit", "take_profit_2", "take_profit_3", "stop_loss", "tp_pct",
               "sl_pct", "model_prob", "targets_hit", "exit_reason", "exit_price", "exit_at", "pnl_gross_pct",
               "pnl_net_pct", "r_multiple", "mfe_pct", "mae_pct"]
