# SK Hynix / SKHY OKX Pairs Dashboard — V1 Specification

## 1. Objective

Build a read-only web dashboard for monitoring the relative value between the SK hynix Korean ordinary-share perpetual and the SK hynix U.S. ADR perpetual on OKX.

V1 uses OKX for all perpetual-contract data and Yahoo Finance for delayed KOSPI and KOSDAQ index context. The dashboard uses **mark price as the sole contract price**. Last trade, bid, ask, and mid prices are intentionally excluded.

## 2. Instruments

| Role | OKX instrument | Reference index | Launch time |
|---|---|---|---|
| Korean ordinary share | `SKHYNIX-USDT-SWAP` | `SKHYNIX-USDT` | 2026-06-10 13:50 Beijing time |
| U.S. ADR | `SKHY-USDT-SWAP` | `SKHY-USDT` | 2026-07-11 00:10 Beijing time |

The paired dataset begins at **2026-07-11 00:10 Beijing time (UTC+8)**, when the ADR perpetual became live.

The ADR conversion ratio is fixed at **10 SKHY ADRs per one Korean ordinary share**. V1 treats this ratio as configuration so it can be changed if a corporate action alters it.

## 3. Market context

Korean cash-index context comes from Yahoo Finance's free, delayed intraday feed. SPY and QQQ remain OKX perpetual mark prices:

| Dashboard label | Source instrument | Interpretation |
|---|---|---|
| KOSPI | Yahoo Finance `^KS11` | Delayed KOSPI Composite Index quote |
| KOSDAQ | Yahoo Finance `^KQ11` | Delayed KOSDAQ Composite Index quote |
| SPY | OKX `SPY-USDT-SWAP` | S&P 500 ETF perpetual proxy |
| QQQ | OKX `QQQ-USDT-SWAP` | Nasdaq-100 ETF perpetual proxy |

Yahoo Finance index access requires no API key but is unofficial and may be delayed or rate-limited. A Yahoo outage must not prevent the OKX pair snapshot from loading; unavailable index cards display an explicit warning.

KOSPI and KOSDAQ percentage changes are calculated against Yahoo's previous close. SPY and QQQ use a rolling 24-hour change calculated from the current OKX mark versus the nearest five-minute OKX mark candle to exactly 24 hours earlier.

## 4. Core calculations

For timestamp `t`:

```text
adr_equivalent(t) = 10 × mark_SKHY(t)

spread_usdt(t) = adr_equivalent(t) − mark_SKHYNIX(t)

adr_premium_pct(t) =
    (adr_equivalent(t) / mark_SKHYNIX(t) − 1) × 100
```

Positive premium means the ADR perpetual is expensive relative to the Korean ordinary-share perpetual after ratio normalization. Negative premium means it is cheap.

The rolling z-score is:

```text
z(t) = (premium(t) − rolling_mean(premium))
       / rolling_stddev(premium)
```

Default z-score window: 288 five-minute observations, equivalent to 24 hours of a 24/7 market. The UI must state this explicitly and must not call it a trading-day window.

### Funding carry

With positive OKX funding, longs pay shorts. For equal normalized notional:

```text
long Korean / short ADR carry = funding_SKHY − funding_SKHYNIX
short Korean / long ADR carry = funding_SKHYNIX − funding_SKHY
```

The dashboard displays current funding, last settled funding, the countdown to collection of the current rate, and both directional net carry values. The countdown uses OKX `fundingTime`; `nextFundingTime` is retained only to describe the following funding cycle.

## 5. Dashboard layout

### Header

- Product title and OKX pair-data badge
- Overall feed status
- Last refresh time
- Manual refresh control

### Pair summary

- Korean mark price
- ADR mark price
- Ratio-adjusted ADR mark price
- Absolute spread in USDT
- ADR premium/discount percentage
- Rolling z-score
- Interpretation: ADR rich, balanced, or ADR cheap

### Reference and funding cards

For both pair contracts:

- Mark price
- Index price
- Mark-to-index basis percentage
- Current funding rate
- Last settled funding rate
- Countdown until the displayed current funding rate is collected, plus its Beijing-time collection time

### Historical section

- ADR premium/discount percentage chart with y-axis labels and hover values
- Combined SKHYNIX and SKHY settled-funding chart with distinct lines and point markers
- Funding history uses realized OKX collection events at 00:00, 08:00, and 16:00 Beijing time, yielding three observations per complete day
- Ranges: 1 day, 5 days, 1 month, all history
- Five-minute granularity for premium history; eight-hour event granularity for funding history

### Market context

- Delayed KOSPI index level and change from previous close
- Delayed KOSDAQ index level and change from previous close
- SPY mark price and Beijing day change
- QQQ mark price and Beijing day change
- Clear proxy and source labels

### Data quality

- Backfill progress
- Latest stored candle timestamp
- Stale-feed warning
- Missing or unaligned candle count

## 6. Data ingestion and storage

### Live data

- Refresh the backend snapshot from public OKX endpoints.
- Refresh the browser once per minute.
- Incrementally ingest the latest completed five-minute mark candles every five minutes and before serving history when the cache is stale.
- Incrementally ingest recent funding settlements alongside mark candles.
- Consider a mark price stale when its OKX timestamp is more than two minutes old.
- Require no OKX API key.

### Historical data

- Backfill five-minute mark-price candles for both pair instruments to 2026-07-11 00:10 Beijing time.
- Backfill funding history for both pair instruments.
- Align historical funding rates only at collection timestamps present for both contracts.
- Store data in SQLite for V1.
- Use idempotent upserts.
- Reconcile recent history on every startup.
- Never silently forward-fill a missing leg. Only aligned timestamps enter spread calculations.

## 7. Technical architecture

- Python 3.11+
- FastAPI backend
- `httpx` asynchronous OKX and Yahoo Finance clients
- SQLite persistence
- React/Vinext dashboard frontend
- HTML Canvas charts
- Pytest for calculations and storage behavior

The Python service owns OKX access, normalization, backfill, storage, and pair analytics. The web client is presentation-only.

## 8. API surface

```text
GET /health
GET /api/v1/snapshot
GET /api/v1/history?range=1d|5d|1m|all
GET /api/v1/backfill-status
POST /api/v1/backfill
```

`POST /api/v1/backfill` is an operational trigger only. V1 contains no order-entry or authenticated OKX functionality.

## 9. Acceptance criteria

- Uses mark price everywhere a contract price is displayed or analyzed.
- Does not display last trade, bid, ask, or mid price.
- Correctly applies the 10:1 ADR ratio.
- Shows both OKX index prices separately from mark prices.
- Shows current and last-settled funding for both contracts.
- Displays net funding carry for both pair directions.
- Displays both settled funding histories on one marked chart with three collection points per complete day.
- Provides aligned five-minute history back to the ADR-perp launch.
- Refreshes current data every 60 seconds.
- Shows KOSPI and KOSDAQ as delayed Yahoo Finance index quotes with clear source labels.
- Survives restart and resumes historical ingestion without duplicate rows.
- Shows visible stale-data and backend-disconnection states.
- Contains no trading or order-management capability.

## 10. Deferred beyond V1

- Licensed real-time KOSPI/KOSDAQ, Nasdaq, or consolidated U.S. market feeds
- Bid/ask, depth, slippage, and executable-spread calculations
- Alerts and notifications
- Position sizing and portfolio integration
- Automated trading
- Multi-user authentication
- Production-grade time-series database and long-term hosted collector
