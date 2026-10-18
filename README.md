# SignalDesk: crypto signals on validated 4H strategies

A web dashboard and Telegram bot that publish crypto trading signals from three strategies, each
validated out-of-sample on 2017–2026 Binance data, and track every signal to its result.

| | Strategy | Out-of-sample (2022 → Oct 2026) |
|---|---|---|
| A | **Regime Pullback** `RGP-4H`: RSI(2) washout inside a coin + BTC trend | 1,800 signals · 90.5% win rate · PF 1.30 |
| B | **Sweep Reversal** `RSR-4H`: failed breakdown/breakout of the 4-day range | 947 signals · 88.3% · PF 1.47 |
| C | **ML-Ranked** `MLR-4H`: LightGBM, top 5% confidence, retrained quarterly | 3,240 signals · 88.7% · PF 1.52 |
| | **Book A + B + C** | 5,829 signals · 89.1% · PF 1.42 · +0.33% net per signal |

## Repository

| Path | What |
|---|---|
| [`docs/crypto-signal-strategy-research.md`](docs/crypto-signal-strategy-research.md) | Research report: what was tested, what survived, why |
| [`docs/deployment.md`](docs/deployment.md) | Docker deployment, Telegram (@BotFather) setup, operations, security |
| `research/` | Backtesting harness, results, the production ML model |
| `backend/` | Python: signal engine, FastAPI API, Telegram bot, PostgreSQL schema (Alembic) |
| `frontend/` | React + TypeScript dashboard, served by nginx |
| `docker-compose.yml` | Production stack (db, migrate, api, engine, web, daily backups, optional Caddy TLS) |
| `.github/workflows/ci.yml` | CI: lint, tests, migrations, frontend build, Docker build and a search-blocking smoke test |

## Quick start

```bash
cp .env.example .env        # set POSTGRES_PASSWORD, SECRET_KEY, ADMIN_PASSWORD, Telegram
docker compose up -d --build
open http://localhost:8080
```

Search engines are blocked by default (robots.txt + `X-Robots-Tag` + meta tag). See
[deployment §4](docs/deployment.md#4-search-engine-blocking-default).

## Development

```bash
# backend
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
python -m pytest            # unit, API, Telegram; parity + engine E2E tests run when research data exists
ruff check .

# frontend (proxies /api to 127.0.0.1:8000)
cd frontend && npm ci && npm run dev
```

CI runs on every push. The parity and engine E2E tests need the research candles
(`python research/data/fetch_klines.py`, ~90 MB), so CI skips them; run them locally before
changing anything in `backend/app/core` or `backend/app/engine`.

The engine's signals are tested against the research harness:
- `backend/tests/test_parity.py` checks rules, all 48 ML features and model scores, and that a
  replay reproduces every research trade.
- `backend/tests/test_engine_replay.py` drives the real engine candle by candle and compares its
  signals with that replay.

*Research and education only, not investment advice.*
