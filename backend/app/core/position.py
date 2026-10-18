"""Position helpers shared by the API and the Telegram bot (duck-typed over Signal rows)."""

from __future__ import annotations


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
