from datetime import datetime, timedelta, timezone

import pytest

from app.core import stats
from app.core.lifecycle import Bar, Costs, TradeState, levels, pnl, step

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
H4 = timedelta(hours=4)


def bar(i, o, h, l, c):
    return Bar(T0 + i * H4, T0 + (i + 1) * H4, o, h, l, c)


def trade(side=1, entry=100.0, tp=None, sl=None, bars=6):
    tp = tp if tp is not None else entry + side * 1
    sl = sl if sl is not None else entry - side * 6
    return TradeState(side, entry, tp, sl, T0, T0 + bars * H4)


def test_levels():
    assert levels(1, 100, 2, 0.5, 4) == (101, 92)
    assert levels(-1, 100, 2, 0.5, 3) == (99, 106)


def test_long_take_profit():
    st = trade()
    assert not step(st, bar(0, 100, 100.8, 99, 100.5))
    assert step(st, bar(1, 100.5, 101.5, 100, 101.2))
    assert (st.exit_reason, st.exit_price, st.exit_at) == ("TP", 101, T0 + 2 * H4)
    r = pnl(st, Costs())
    assert r["gross"] == pytest.approx(0.01)
    assert r["net"] == pytest.approx(0.01 - 0.0007 - 0.0002)
    assert r["r"] == pytest.approx(r["net"] / 0.06)


def test_stop_wins_when_both_levels_inside_one_bar():
    st = trade()
    assert step(st, bar(0, 100, 102, 93, 100))
    assert st.exit_reason == "SL" and st.exit_price == 94


def test_gap_through_stop_fills_at_open_after_entry_bar():
    st = trade()
    step(st, bar(0, 100, 100.5, 99, 99.5))
    assert step(st, bar(1, 90, 91, 89, 90))
    assert st.exit_reason == "SL" and st.exit_price == 90


def test_time_exit_at_last_bar_close():
    st = trade(bars=3)
    for i in range(2):
        assert not step(st, bar(i, 100, 100.5, 99.5, 100))
    assert step(st, bar(2, 100, 100.4, 99.6, 99.8))
    assert st.exit_reason == "TIME" and st.exit_price == 99.8 and st.exit_at == T0 + 3 * H4


def test_short_mirrors_long():
    st = trade(side=-1)
    assert step(st, bar(0, 100, 100.5, 98.9, 99.2))
    assert st.exit_reason == "TP" and st.exit_price == 99
    st = trade(side=-1)
    assert step(st, bar(0, 100, 106.5, 98.5, 100))
    assert st.exit_reason == "SL" and st.exit_price == 106


def test_bars_are_processed_once():
    st = trade()
    b = bar(0, 100, 100.8, 99, 100.5)
    step(st, b)
    mfe = st.mfe
    st.mfe = 0.0
    step(st, b)  # duplicate delivery of the same bar is ignored
    assert st.mfe == 0.0 and mfe == pytest.approx(0.008)


def rows(nets):
    return [{"exit_at": T0 + i * H4, "pnl_net": x, "r_multiple": x / 0.05, "exit_reason": "TP" if x > 0 else "SL"}
            for i, x in enumerate(nets)]


def test_kpis():
    k = stats.kpis(rows([0.01, 0.01, 0.01, -0.05]), days=2)
    assert k["signals"] == 4 and k["wins"] == 3
    assert k["win_rate"] == pytest.approx(0.75)
    assert k["profit_factor"] == pytest.approx(0.03 / 0.05)
    assert k["breakeven_win_rate"] == pytest.approx(0.05 / 0.06)
    assert k["expectancy"] == pytest.approx(-0.005)
    assert k["max_consecutive_losses"] == 1
    assert k["signals_per_day"] == 2
    assert stats.kpis([])["win_rate"] is None


def test_equity_and_drawdown():
    curve = stats.equity_curve(rows([0.05, -0.05, -0.05, 0.05]), risk=0.01)
    assert curve["points"][0]["equity"] == pytest.approx(1.01)
    assert curve["max_drawdown"] == pytest.approx(1 - 0.99 * 0.99)
    assert [m["month"] for m in stats.monthly(rows([0.01]))] == ["2026-01"]
