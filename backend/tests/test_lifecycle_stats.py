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


def ladder(side=1, entry=100.0, bars=12):
    # TP1/TP2/TP3 at 1/2/3 points, 50/30/20%, stop 6 points, stop to entry after TP1
    targets = tuple(entry + side * k for k in (1, 2, 3))
    return TradeState(side, entry, targets[0], entry - side * 6, T0, T0 + bars * H4,
                      targets=targets, sizes=(0.5, 0.3, 0.2), breakeven=True)


def test_ladder_fills_targets_in_order_and_moves_stop_next_bar():
    st = ladder()
    assert not step(st, bar(0, 100, 101.5, 99.5, 101.2))          # TP1
    assert st.targets_hit == 1 and st.fills[0] == (T0 + H4, 101) and st.stop_loss == 100
    assert st.initial_stop == 94 and st.remaining == pytest.approx(0.5)
    assert not step(st, bar(1, 101.2, 102.2, 100.6, 102))          # TP2, stop at entry untouched
    assert st.targets_hit == 2
    assert step(st, bar(2, 102, 103.4, 101.8, 103.1))               # TP3: fully closed
    assert (st.exit_reason, st.exit_price, st.exit_at) == ("TP", 103, T0 + 3 * H4)
    r = pnl(st, Costs())
    gross = 0.5 * 0.01 + 0.3 * 0.02 + 0.2 * 0.03
    assert r["gross"] == pytest.approx(gross)
    assert r["net"] == pytest.approx(gross - 0.0007 - 0.0002)
    assert r["r"] == pytest.approx(r["net"] / 0.06)


def test_ladder_break_even_exit_after_tp1_is_a_small_win():
    st = ladder()
    step(st, bar(0, 100, 101.2, 99.8, 100.9))                       # TP1
    assert step(st, bar(1, 100.9, 101.5, 99.7, 99.9))               # back to entry
    assert st.exit_reason == "BE" and st.exit_price == 100 and st.targets_hit == 1
    r = pnl(st, Costs())
    assert r["net"] == pytest.approx(0.5 * 0.01 - 0.0007 - 0.5 * 0.0002 - 0.5 * 0.0008) and r["net"] > 0


def test_ladder_stop_first_and_original_stop_inside_the_tp1_bar():
    st = ladder()
    assert step(st, bar(0, 100, 101.5, 93.5, 100))                  # stop and TP1 in one bar: stop first
    assert st.exit_reason == "SL" and st.targets_hit == 0 and pnl(st, Costs())["r"] < -0.99


def test_ladder_gap_fills_targets_at_the_open_and_time_exit_closes_the_rest():
    st = ladder(bars=3)
    step(st, bar(0, 100, 100.5, 99.5, 100.2))
    assert not step(st, bar(1, 102.4, 102.6, 101.9, 102.1))         # opens above TP1 and TP2
    assert [px for _, px in st.fills] == [102.4, 102.4] and st.stop_loss == 100
    assert step(st, bar(2, 102.1, 102.5, 101.5, 101.8))             # TP3 not reached: time exit
    assert st.exit_reason == "TIME" and st.exit_price == 101.8
    assert pnl(st, Costs())["gross"] == pytest.approx(0.8 * 0.024 + 0.2 * 0.018)


def test_ladder_short_mirrors_long():
    st = ladder(side=-1)
    assert not step(st, bar(0, 100, 100.2, 98.6, 98.8))             # TP1 (99)
    assert st.targets_hit == 1 and st.stop_loss == 100
    assert step(st, bar(1, 98.8, 100.3, 98.5, 100.1))               # back above entry
    assert st.exit_reason == "BE"


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
