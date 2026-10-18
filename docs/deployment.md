# SignalDesk: deployment and operations

SignalDesk runs the three validated 4H strategies (A `RGP-4H`, B `RSR-4H`, C `MLR-4H`, see
[the research report](crypto-signal-strategy-research.md)). It publishes every signal to the web
dashboard and Telegram, then tracks each one to its target, stop or time limit.

```
                 ┌───────────── docker compose ──────────────┐
 Binance REST ──▶│ engine ── evaluates every 4H close,       │──▶ Telegram Bot API
                 │           tracks TP/SL on 1m candles      │    (channel + DMs)
                 │   │                                        │
                 │   ▼                                        │
                 │ PostgreSQL ◀── api (FastAPI, SSE) ◀── web │◀── browsers
                 │                                (nginx)     │
                 └────────────────────────────────────────────┘
```

| Service | Role |
|---|---|
| `db` | PostgreSQL 16: candles, signals ledger, strategy state, Telegram outbox, events |
| `migrate` | One-shot `alembic upgrade head` before anything else starts |
| `engine` | Market data, signal evaluation, tracking, kill switch, Telegram delivery and bot commands |
| `api` | Read API, live event stream (SSE), admin console API |
| `web` | nginx: dashboard, `/api` proxy, security headers, search-engine blocking |
| `backup` | Daily `pg_dump` of the database into `./backups`, with retention |
| `caddy` | *optional* (`--profile tls`): automatic HTTPS with Let's Encrypt |

## 1. Server requirements

- Linux with Docker Engine 24+ and the Compose plugin.
- 2 vCPU, 2 GB RAM, 10 GB disk is enough for the 10-coin universe.
- Outbound HTTPS to Binance (`data-api.binance.vision`, `api.binance.com`) and `api.telegram.org`.
  Binance blocks some regions (e.g. the US) on `api.binance.com`; `data-api.binance.vision` (the default
  first host) is the public market-data mirror and works more widely. If you set
  `MARKET_DATA_SOURCE=binance_futures`, the server must be in a region allowed by Binance Futures.
- A domain name if you want HTTPS (recommended).

## 2. First deployment

```bash
git clone <repo> signaldesk && cd signaldesk
cp .env.example .env
openssl rand -hex 32                     # paste into SECRET_KEY
openssl rand -base64 24                  # paste into POSTGRES_PASSWORD
nano .env                                # ADMIN_PASSWORD, PUBLIC_BASE_URL, Telegram (section 3)
docker compose up -d --build
docker compose logs -f engine            # first start downloads ~9 years of 4H candles (2–4 min)
```

Open `http://<server>:8080` for the dashboard and `http://<server>:8080/admin` for the admin console.

**HTTPS with the bundled Caddy**: point a DNS A record at the server, set `DOMAIN`, `ACME_EMAIL` and
`WEB_BIND=127.0.0.1` in `.env`, open ports 80/443, then:

```bash
docker compose --profile tls up -d --build
```

**HTTPS with your own reverse proxy** (Traefik, nginx, a cloud load balancer): set
`WEB_BIND=127.0.0.1`, proxy `https://your-domain` to `127.0.0.1:${WEB_PORT}`, and disable response
buffering for `/api/stream` (Server-Sent Events).

Keep `COOKIE_SECURE=true` behind HTTPS. Set it to `false` only to test the admin console over plain HTTP.

## 3. Telegram with @BotFather

1. In Telegram, open **@BotFather** → `/newbot` → choose a name and a username ending in `bot`.
   BotFather replies with the **token** (`123456789:AA…`). Put it in `TELEGRAM_BOT_TOKEN`.
2. Optional polish in BotFather:
   - `/setdescription` and `/setabouttext`: what users see before pressing Start.
   - `/setuserpic`: the bot avatar.
   - The command list (`/signals`, `/stats`, `/regime`, `/subscribe`, `/unsubscribe`, `/help`) is
     registered automatically by the engine.
3. Create a **channel** (public or private) for the signal feed.
   - Channel settings → *Administrators* → add your bot with **Post messages** and **Edit messages
     of others**. Edit rights are how the engine stamps each signal with its final result.
4. Set the channel in `.env`:
   - Public channel: `TELEGRAM_CHANNEL_ID=@yourchannel`
   - Private channel: the numeric id, e.g. `-1001234567890`. To find it, post any message in the
     channel, open `https://api.telegram.org/bot<TOKEN>/getUpdates` while the engine is *stopped*,
     and read `channel_post.chat.id`. Alternatively, forward a channel post to a bot such as
     @JsonDumpBot.
   - `TELEGRAM_CHANNEL_URL=https://t.me/yourchannel` (or the invite link) shows a Telegram button on
     the website.
5. `docker compose up -d engine` (restart to pick up the env), then send a test message:
   - from the admin console → *Telegram → Test*, or
   - `docker compose exec engine python -m app.cli telegram-test`.

What gets sent:

| Event | Channel | Subscribers (DM) |
|---|---|---|
| New signal: entry, target (limit), stop, expiry, risk-based size, regime, backtest reference, "Open signal" button | ✓ | ✓ |
| Signal closed: reply to the original with exit, net %, R and holding time; the original message is edited with the result | ✓ | ✓ |
| Daily summary at 00:05 UTC (yesterday's results + 30-day stats) | ✓ | |
| Strategy auto-paused / resumed by the kill switch | ✓ | |
| Ops alerts (see below) | | admins only |

**Ops alerts for you.** Press Start on your bot, send `/id`, and put the number it replies with in
`TELEGRAM_ADMIN_CHAT_IDS` (comma-separate several admins). Those chats then receive:

- engine started (after every deploy or restart);
- Binance unreachable for 5 minutes, and recovered;
- a 4H candle still missing after retries, or a loop error (e.g. the tracker);
- a strategy auto-paused or resumed by the kill switch, with the numbers that triggered it;
- a Telegram delivery that failed permanently (e.g. the bot lost its channel admin rights).

Alerts of the same kind are sent at most once every 30 minutes. Admins can also send `/status` to
the bot for the engine clock, the last evaluation, open signals, the Telegram queue and the
strategy modes.

Users subscribe by pressing **Start** on the bot (or `/subscribe`). If a user blocks the bot, they
are unsubscribed automatically. Delivery goes through a database outbox, paced to Telegram's
limits (≈20 messages/min per channel, ≈25/s overall) and retried with backoff, so nothing is lost
during a Telegram outage or an engine restart.

## 4. Search-engine blocking (default)

`SEARCH_INDEXING=false` (the default) applies four layers:

1. `robots.txt` → `Disallow: /` for every crawler, with AI/dataset crawlers (GPTBot, CCBot,
   ClaudeBot, Google-Extended, …) also named explicitly.
2. `X-Robots-Tag: noindex, nofollow, noarchive, nosnippet, noimageindex, notranslate` on **every**
   response: pages, assets, API, errors.
3. `<meta name="robots" content="noindex, nofollow, noarchive">` and a googlebot meta tag in the HTML.
4. The API adds the same header itself, so it is also covered if accessed without nginx.

Verify after deploying:

```bash
curl -sI https://your-domain/ | grep -i x-robots-tag
curl -s https://your-domain/robots.txt
```

If the domain was **already indexed** before, set `SEARCH_INDEXING=deindex` for a few weeks.
Pages then stay `noindex` but become crawlable, so search engines can see the noindex and drop
them (a crawler blocked by robots.txt never sees the header). Switch back to `false` afterwards.
Set `SEARCH_INDEXING=true` only when you want the site public in search results.

## 5. Strategy controls and the kill switch

The admin console (`/admin`) shows, for each strategy, its mode and rolling health:

- **Live**: signals are published (web + Telegram).
- **Shadow**: signals are generated and tracked but not published. Use this to paper-trade a
  strategy, e.g. MLR-4H for its first weeks.
- **Off**: not evaluated.

The **kill switch** auto-pauses a live strategy when its last 150 closed signals fall below an 82%
win rate or a 0.75 profit factor. While paused, the strategy keeps running unpublished. It
resumes automatically after 50 paper signals with profit factor > 1.1. You can also resume it
manually. Thresholds are set in `.env` (`KILL_SWITCH_*`).

`STRATEGY_MODES` in `.env` only seeds the initial modes. After the first start, the admin console
is the source of truth.

## 6. Operations

| Task | Command |
|---|---|
| Status | `docker compose ps` (engine, api and web report *healthy*) · `docker compose exec engine python -m app.cli status` · `/status` to the bot |
| Logs (JSON) | `docker compose logs -f engine api` |
| Health | `curl -s http://127.0.0.1:8080/api/health` (`engine_alive` turns false if the engine misses heartbeats for 90 s) |
| Update | `git pull && docker compose up -d --build` (migrations run automatically) |
| Backup now | `docker compose exec -T db pg_dump -U signals -Fc signals > signals-$(date +%F).dump` |
| Restore | `docker compose exec -T db pg_restore -U signals -d signals --clean < backups/signals-YYYYMMDDTHHMMZ.dump` |

**Backups are automatic.** The `backup` service writes `./backups/signals-<UTC time>.dump` every
`BACKUP_INTERVAL_HOURS` (24) and deletes dumps older than `BACKUP_KEEP_DAYS` (14). The signal
ledger is the product's track record, so also copy `./backups` off the server, for example with a
nightly `rclone copy` or `rsync` to object storage. `docker compose logs backup` shows each run.

**Health checks.** The engine container turns *unhealthy* when its heartbeat (written every 15 s
after a successful database write) is older than 90 seconds; the first start allows 10 minutes
for the candle backfill. `engine_alive` in `/api/health` reports the same from the API side.

**Restarts are safe.**
- Signal ids are idempotent (`strategy:symbol:candle`), so a restart within the same 4H candle
  never duplicates a signal.
- Open signals resume tracking from the last processed minute.
- A candle missed by more than `MAX_SIGNAL_LATENCY_MINUTES` (default 15) is skipped and logged
  rather than published late.

**Retraining strategy C** (quarterly): on a workstation with the research environment,

```bash
python research/data/fetch_klines.py
python research/meta_label.py --tf 4h --tp 0.5 --sl 3.0 --bars 24 --export
```

Commit the new `research/results/models/mlr_4h_tp0.5_sl3.0_b24.{txt,json}`, then redeploy.
The model version is shown in the footer and the admin console.

## 7. Demo / staging on historical data

The engine can replay stored candles on an accelerated clock: it runs the same code, and every
signal is tagged `origin=demo` with a banner on the site. Use a separate database.

```bash
python research/data/fetch_klines.py               # once, ~200 MB into research/data/parquet
POSTGRES_DB=signals_demo docker compose -f docker-compose.yml -f deploy/docker-compose.demo.yml up -d --build
```

`REPLAY_START` (default 2026-08-01) and `REPLAY_SPEED` (default 600: one 4H candle every 24 s)
control the replay. Strategy C uses the production model, which was trained on data up to its
`trained_through` date (2026-10-12). Its demo results on 2026 data are therefore in-sample and
optimistic. The research report's walk-forward numbers are the honest reference for C. To seed a production ledger with *clearly labelled* history, use
`python -m app.cli backfill-ledger --since 2026-01-01`. Those rows are `origin=backfill`, never
published, and excluded from live statistics unless "+ Backfill" is selected.

## 8. Security checklist

- [ ] `SECRET_KEY` is 32+ random characters. The API refuses to start in production with the default.
- [ ] `ADMIN_PASSWORD` is long and unique. Failed logins are rate limited (8 per 15 min per IP) and logged.
- [ ] HTTPS is in front of the site and `COOKIE_SECURE=true`.
- [ ] PostgreSQL is not published to the host (the compose file does not expose port 5432).
- [ ] `.env` is not committed (it is in `.gitignore`).
- [ ] `./backups` fills daily (`ls backups/`) and is copied off the server.
- [ ] `TELEGRAM_ADMIN_CHAT_IDS` is set, so outages reach you on Telegram.

The admin session is an httpOnly, SameSite=Strict cookie. Mutating requests also require an
`X-Requested-With` header. nginx sends a strict Content-Security-Policy (no inline scripts, no
third-party origins; fonts are self-hosted), `X-Frame-Options: DENY`, `nosniff` and a restrictive
Permissions-Policy.

## 9. Troubleshooting

| Symptom | Check |
|---|---|
| "Engine offline" badge | `docker compose logs engine`. Usually Binance is unreachable from the server's region (see §1); with admin alerts on you get a `market.down` message after 5 minutes. |
| No signals for days | Normal in neutral regimes (BTC without a clear trend). See the regime card. `app.cli status` shows the last evaluated candle. |
| Telegram test never arrives | Admin console → Telegram: bot error text; is the bot an admin of the channel; is `TELEGRAM_CHANNEL_ID` right (`@name` or `-100…`)? |
| Admin login fails over HTTP | Set `COOKIE_SECURE=false` for plain-HTTP testing only. |
| Dashboard not updating live | A proxy in front of nginx is buffering `/api/stream`. Disable buffering for that path. |
