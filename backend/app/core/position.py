"""Position helpers shared by the API and the Telegram bot (duck-typed over Signal rows)."""

from __future__ import annotations

from datetime import datetime


def targets_of(sig) -> list[tuple[float, float]]:
    """[(price, fraction of position)], TP1 first. Signals without a ladder have one target."""
    if getattr(sig, "targets", None):
        return [(float(p), float(z)) for p, z in sig.targets]
    return [(float(sig.take_profit), 1.0)]


def fills_of(sig) -> list[float]:
    """Fill price of every target reached so far."""
    return [float(px) for _, px in (getattr(sig, "fills", None) or [])]


def open_return(sig, live: float) -> float:
    """Return of the whole position before costs: closed targets plus the open rest at `live`."""
    targets, fills = targets_of(sig), fills_of(sig)
    done = sum(z * sig.side * (px / sig.entry_price - 1) for (_, z), px in zip(targets, fills, strict=False))
    rest = 1 - sum(z for _, z in targets[:len(fills)])
    return done + rest * sig.side * (live / sig.entry_price - 1)


def events(sig) -> list[tuple[str, datetime]]:
    """Target fills and the final stop / time exit, with their times (a TP exit is its last fill)."""
    fills = getattr(sig, "fills", None) or []
    out = [(f"TP{i + 1}", datetime.fromisoformat(t)) for i, (t, _) in enumerate(fills)]
    if not fills and sig.status == "CLOSED" and sig.exit_reason == "TP":
        out.append(("TP1", sig.exit_at))  # single-target signal from before the target ladder
    if sig.status == "CLOSED" and sig.exit_reason in ("SL", "BE", "TIME"):
        out.append((sig.exit_reason, sig.exit_at))
    return out
