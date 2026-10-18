"""The production engine must reproduce the validated research exactly."""

import numpy as np
import pandas as pd
import pytest

from app.core import indicators as ta
from app.core.catalog import MLR, RGP, RSR
from app.core.lifecycle import Costs
from app.core.ml import MLModel, universe_features
from app.core.replay import replay
from app.core.rules import btc_trend_for, regime_pullback, sweep_reversal

from .conftest import MODEL, RESEARCH, SYMBOLS, needs_data

pytestmark = needs_data

RGP_PARAMS = {"rsi_n": 2, "rsi_lo": 5, "trend_n": 200, "sides": "both",
              "tp_atr": 0.5, "sl_atr": 4.0, "max_bars": 48}
RSR_PARAMS = {"lookback": 24, "loc": 0.5, "min_sweep_atr": None, "trend_n": 200, "regime": True,
              "tp_atr": 0.5, "sl_atr": 3.0, "max_bars": 24}


@pytest.mark.parametrize("symbol", SYMBOLS)
def test_rule_signals_match_research(frames, research_modules, symbol):
    rs = research_modules["strategies"]
    df, btc = frames[symbol], frames["BTCUSDT"]
    f = rs.Features(df, btc if symbol != "BTCUSDT" else None)
    coin_tr = ta.trend(df["close"])
    btc_tr = btc_trend_for(df, None if symbol == "BTCUSDT" else btc)
    np.testing.assert_array_equal(regime_pullback(df, coin_tr, btc_tr),
                                  rs.regime_gated_pullback(f, RGP_PARAMS)["side"])
    np.testing.assert_array_equal(sweep_reversal(df, coin_tr, btc_tr),
                                  rs.liquidity_sweep(f, RSR_PARAMS)["side"])


def test_ml_features_match_research(frames, research_modules):
    ours = universe_features(frames, SYMBOLS)
    theirs = research_modules["meta_label"].load("4h")
    for s in SYMBOLS:
        X = theirs[s][1]
        pd.testing.assert_frame_equal(ours[s][X.columns], X, check_dtype=False)


def test_model_scores_match_reference(frames):
    model = MLModel(MODEL)
    t = pd.Timestamp("2026-09-26 16:00", tz="UTC")
    got = {(s.symbol, s.side): s.prob for s in model.score(frames, t)}
    # reference values printed by research/latest_signals.py for this candle
    assert got[("BNBUSDT", -1)] == pytest.approx(0.8957, abs=1e-4)
    assert got[("ETHUSDT", -1)] == pytest.approx(0.8951, abs=1e-4)
    assert got[("BTCUSDT", -1)] == pytest.approx(0.8855, abs=1e-4)


@pytest.mark.parametrize("spec,csv", [(RGP, "A_4h_regime_pullback_trades.csv"),
                                      (RSR, "B_4h_regime_sweep_trades.csv")])
def test_replay_reproduces_research_trades(frames, spec, csv):
    ref = pd.read_csv(RESEARCH / "results" / "candidates" / csv, parse_dates=["entry_time", "exit_time"])
    start, end = pd.Timestamp("2021-12-20", tz="UTC"), pd.Timestamp("2026-10-17", tz="UTC")
    ref = ref[(ref.entry_time >= "2022-01-01") & (ref.reason != "eod")]
    trades = replay(frames, SYMBOLS, {spec.code}, None, start, end, Costs())
    got = pd.DataFrame([{
        "symbol": t.candidate.symbol, "entry_time": t.state.entry_at, "side": t.state.side,
        "reason": t.state.exit_reason.lower(), "pnl": t.result["net"]}
        for t in trades if t.state.closed and t.state.entry_at >= pd.Timestamp("2022-01-01", tz="UTC")])
    m = ref.merge(got, on=["symbol", "entry_time", "side"], how="outer", indicator=True,
                  suffixes=("_ref", "_got"))
    both = m[m._merge == "both"]
    assert (m._merge == "both").mean() > 0.995, m[m._merge != "both"].head(10)
    assert (both.reason_ref == both.reason_got).mean() > 0.995
    np.testing.assert_allclose(both.pnl_got, both.pnl_ref, atol=1e-9)


def test_replay_mlr_quality(frames):
    """MLR replay with the production model (trained through 2026-10) on its own training
    window is in-sample, so only sanity-check direction and volume here."""
    model = MLModel(MODEL)
    start, end = pd.Timestamp("2026-04-01", tz="UTC"), pd.Timestamp("2026-10-10", tz="UTC")
    trades = [t for t in replay(frames, SYMBOLS, {MLR.code}, model, start, end) if t.state.closed]
    assert len(trades) > 50
    assert np.mean([t.result["net"] > 0 for t in trades]) > 0.8
    assert all(t.candidate.model_prob >= model.threshold for t in trades)
