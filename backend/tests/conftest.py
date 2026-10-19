import os
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]
RESEARCH = REPO / "research"
DATA = RESEARCH / "data" / "parquet"
MODEL = RESEARCH / "results" / "models" / "mlr_4h_tp0.5_sl3.0_b24"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
           "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT"]

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SITE_PRIVATE", "false")  # tests opt in to the private site where they test it
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-at-least-32-characters")

needs_data = pytest.mark.skipif(not (DATA / "BTCUSDT_4h.parquet").exists(),
                                reason="research data not downloaded (python research/data/fetch_klines.py)")


@pytest.fixture(scope="session")
def frames() -> dict[str, pd.DataFrame]:
    return {s: pd.read_parquet(DATA / f"{s}_4h.parquet") for s in SYMBOLS}


@pytest.fixture(scope="session")
def research_modules():
    """Import the research harness (it expects to run from research/)."""
    sys.path.insert(0, str(RESEARCH))
    cwd = os.getcwd()
    os.chdir(RESEARCH)
    try:
        import meta_label  # noqa: F401
        from backtest import strategies  # noqa: F401
        import latest_signals  # noqa: F401
        yield {"meta_label": meta_label, "strategies": strategies, "latest_signals": latest_signals}
    finally:
        os.chdir(cwd)
