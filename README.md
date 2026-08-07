# Hynix Basis

An OKX pairs-trading research dashboard for the relative value between:

- `SKHYNIX-USDT-SWAP` — Korean ordinary-share reference
- `SKHY-USDT-SWAP` — U.S. ADR reference

The application uses OKX **mark price only** for contract prices. It separately displays OKX index prices and funding rates. KOSPI and KOSDAQ context comes from Yahoo Finance's free delayed index feed; SPY and QQQ remain OKX perpetual marks. Historical pair data is aligned at five-minute intervals and normalized using the 10 ADRs-to-1 ordinary-share ratio. All displayed timestamps use Beijing time (UTC+8).

See [spec.md](spec.md) for the complete V1 specification.

The current mean-reversion research, strategy rules, limitations, and reproducible
backtest are in [research/strategy_report.md](research/strategy_report.md).

## Local setup

Requires Python 3.11+, Node.js 22+, and npm.

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
npm install
```

Run the API and dashboard in separate terminals:

```bash
.venv/bin/uvicorn backend.main:app --reload --port 8010
```

```bash
npm run dev
```

Then open `http://localhost:3000`.

Alternatively:

```bash
chmod +x scripts/dev.sh
./scripts/dev.sh
```

The combined launcher supervises the frontend and API as one unit. If either
service exits, it stops the other so a stale dashboard cannot remain connected
to a dead API. Combined startup and runtime diagnostics are written to the
rotating `logs/error.log` file (up to 5 MB plus three backups). When the API is
run separately, caught backend errors are written to the same file. Running
`./scripts/dev.sh` a second time reports the existing dashboard instead of
starting duplicates; an orphaned dashboard process from an interrupted launcher
is cleaned up automatically.

## Tests

```bash
.venv/bin/pytest
npm run build
```

## API

- `GET /health`
- `GET /api/v1/snapshot`
- `GET /api/v1/history?range=1d|5d|1m|all`
- `GET /api/v1/backfill-status`
- `POST /api/v1/backfill`

The initial backfill runs in the background when the Python service starts. A continuous collector then ingests newly completed five-minute mark candles and recent funding settlements every five minutes; history requests also trigger a refresh when that cache is stale. SQLite data is stored in `data/hynix_basis.sqlite3` and is ignored by Git. Historical funding is aligned at the shared OKX settlement events (00:00, 08:00, and 16:00 Beijing time) and displayed as three points per complete day.

## Market-context caveat

KOSPI (`^KS11`) and KOSDAQ (`^KQ11`) use Yahoo Finance's delayed quote feed without an API key and show change from the previous close. This is an unofficial endpoint and may be delayed or rate-limited. SPY and QQQ continue to use OKX perpetual mark prices and show rolling 24-hour change.

All four market-context cards show regular cash-session status and a live countdown to the next open/close transition. SPY and QQQ session status describes the U.S. cash market rather than the continuously traded OKX perpetuals.

This application is read-only and does not submit orders.
