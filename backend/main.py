from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .analytics import funding_carry, pair_metrics, rolling_zscores
from .config import (
    ADR,
    CONTEXT_INSTRUMENTS,
    DATABASE_PATH,
    DEFAULT_Z_WINDOW,
    KOREA_INDEXES,
    KOREAN,
    PAIR_INSTRUMENTS,
    PAIR_START_MS,
)
from .logging_config import configure_application_logging
from .okx import OkxClient
from .storage import Store
from .yahoo import YahooClient

logger = configure_application_logging()
store = Store(DATABASE_PATH)
okx = OkxClient()
yahoo = YahooClient()
backfill_state = {
    "running": False,
    "completed": False,
    "error": None,
    "rows_processed": 0,
    "started_at": None,
    "finished_at": None,
}
recent_history_lock = asyncio.Lock()
recent_history_state = {
    "last_attempt": None,
    "last_success": None,
    "error": None,
    "rows_processed": 0,
}


async def refresh_recent_history(*, force: bool = False) -> None:
    now_ms = int(time.time() * 1000)
    last_attempt = recent_history_state["last_attempt"]
    if not force and last_attempt is not None and now_ms - last_attempt < 60_000:
        return

    async with recent_history_lock:
        now_ms = int(time.time() * 1000)
        last_attempt = recent_history_state["last_attempt"]
        if not force and last_attempt is not None and now_ms - last_attempt < 60_000:
            return
        recent_history_state.update(last_attempt=now_ms, error=None, rows_processed=0)
        try:
            candle_pages, funding_pages = await asyncio.gather(
                asyncio.gather(
                    *(
                        okx.mark_candles(
                            instrument.inst_id, bar="5m", limit=100, history=False
                        )
                        for instrument in PAIR_INSTRUMENTS
                    )
                ),
                asyncio.gather(
                    *(
                        okx.funding_history(instrument.inst_id, limit=10)
                        for instrument in PAIR_INSTRUMENTS
                    )
                ),
            )
            candle_counts = await asyncio.gather(
                *(
                    asyncio.to_thread(store.upsert_candles, instrument.inst_id, rows)
                    for instrument, rows in zip(PAIR_INSTRUMENTS, candle_pages, strict=True)
                )
            )
            funding_counts = await asyncio.gather(
                *(
                    asyncio.to_thread(store.upsert_funding, instrument.inst_id, rows)
                    for instrument, rows in zip(PAIR_INSTRUMENTS, funding_pages, strict=True)
                )
            )
            recent_history_state.update(
                last_success=int(time.time() * 1000),
                rows_processed=sum(candle_counts) + sum(funding_counts),
            )
        except Exception as exc:
            recent_history_state["error"] = str(exc)
            logger.exception("Recent OKX history refresh failed")


async def recent_history_loop() -> None:
    while True:
        await refresh_recent_history(force=True)
        await asyncio.sleep(300)


async def backfill() -> None:
    if backfill_state["running"]:
        return
    backfill_state.update(
        running=True,
        error=None,
        rows_processed=0,
        started_at=int(time.time() * 1000),
        finished_at=None,
    )
    try:
        for instrument in PAIR_INSTRUMENTS:
            async def save_candles(rows, inst_id=instrument.inst_id):
                return await asyncio.to_thread(store.upsert_candles, inst_id, rows)

            async def save_funding(rows, inst_id=instrument.inst_id):
                return await asyncio.to_thread(store.upsert_funding, inst_id, rows)

            candle_count = await okx.backfill_mark_candles(
                instrument.inst_id, PAIR_START_MS, save_candles
            )
            funding_count = await okx.backfill_funding(
                instrument.inst_id, PAIR_START_MS, save_funding
            )
            backfill_state["rows_processed"] += candle_count + funding_count
        backfill_state["completed"] = True
    except Exception as exc:
        backfill_state["error"] = str(exc)
        logger.exception("Initial OKX history backfill failed")
    finally:
        backfill_state["running"] = False
        backfill_state["finished_at"] = int(time.time() * 1000)


@asynccontextmanager
async def lifespan(_: FastAPI):
    backfill_task = asyncio.create_task(backfill())
    recent_task = asyncio.create_task(recent_history_loop())
    yield
    for task in (backfill_task, recent_task):
        if not task.done():
            task.cancel()
    await asyncio.gather(backfill_task, recent_task, return_exceptions=True)
    await okx.close()
    await yahoo.close()


app = FastAPI(title="Hynix Basis API", version="0.1.0", lifespan=lifespan)
configured_origin = os.getenv("DASHBOARD_ORIGIN")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[configured_origin] if configured_origin else [],
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):\d+$",
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


async def pair_leg(instrument) -> dict:
    mark, index, funding = await asyncio.gather(
        okx.mark_price(instrument.inst_id),
        okx.index_price(instrument.index_id),
        okx.funding_rate(instrument.inst_id),
    )
    return {
        "key": instrument.key,
        "label": instrument.label,
        "inst_id": instrument.inst_id,
        "mark": mark["mark"],
        "index": index["index"],
        "basis_pct": (mark["mark"] / index["index"] - 1.0) * 100.0,
        "funding": funding,
        "ts": min(mark["ts"], index["ts"], funding["ts"]),
        "stale": int(time.time() * 1000) - mark["ts"] > 120_000,
    }


async def context_market(instrument) -> dict:
    mark_result, yahoo_result = await asyncio.gather(
        okx.mark_price(instrument.inst_id),
        yahoo.index_quote(instrument.label),
        return_exceptions=True,
    )
    if isinstance(mark_result, BaseException):
        raise mark_result
    mark = mark_result
    session = None if isinstance(yahoo_result, BaseException) else yahoo_result["session"]
    try:
        change = await okx.trailing_24h_change(
            instrument.inst_id, mark["mark"], mark["ts"]
        )
    except Exception:  # noqa: BLE001 - context change is optional
        change = None
    return {
        "key": instrument.key,
        "label": instrument.label,
        "inst_id": instrument.inst_id,
        "mark": mark["mark"],
        "change_pct": change,
        "proxy_note": "OKX mark · U.S. cash session via Yahoo Finance",
        "ts": mark["ts"],
        "stale": int(time.time() * 1000) - mark["ts"] > 120_000,
        "session": session,
    }


async def korea_index_market(instrument) -> dict:
    try:
        quote = await yahoo.index_quote(instrument.symbol)
        return {
            "key": instrument.key,
            "label": instrument.label,
            "inst_id": instrument.symbol,
            "mark": quote["mark"],
            "change_pct": quote["change_pct"],
            "proxy_note": f"Yahoo Finance · delayed quote · {instrument.symbol}",
            "ts": quote["ts"],
            "stale": False,
            "session": quote["session"],
        }
    except Exception:  # noqa: BLE001 - external index context must not take down the pair feed
        return {
            "key": instrument.key,
            "label": instrument.label,
            "inst_id": instrument.symbol,
            "mark": None,
            "change_pct": None,
            "proxy_note": "Yahoo Finance index temporarily unavailable",
            "ts": 0,
            "stale": True,
            "session": None,
        }


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "hynix-basis-api"}


@app.get("/api/v1/snapshot")
async def snapshot() -> dict:
    try:
        korean, adr, *context = await asyncio.gather(
            pair_leg(KOREAN),
            pair_leg(ADR),
            *(korea_index_market(instrument) for instrument in KOREA_INDEXES),
            *(context_market(instrument) for instrument in CONTEXT_INSTRUMENTS),
        )
    except Exception as exc:
        logger.exception("Live snapshot failed because required OKX data was unavailable")
        raise HTTPException(status_code=502, detail=f"OKX data unavailable: {exc}") from exc

    metrics = pair_metrics(korean["mark"], adr["mark"])
    carry = funding_carry(
        korean["funding"]["current"], adr["funding"]["current"]
    )
    return {
        "as_of": int(time.time() * 1000),
        "source": "OKX + Yahoo Finance",
        "price_type": "mark",
        "pair": {"korean": korean, "adr": adr, **metrics, "funding_carry": carry},
        "context": context,
        "backfill": dict(backfill_state),
    }


RANGE_MS = {
    "1d": 24 * 60 * 60 * 1000,
    "5d": 5 * 24 * 60 * 60 * 1000,
    "1m": 31 * 24 * 60 * 60 * 1000,
}


@app.get("/api/v1/history")
async def history(range_: str = Query("5d", alias="range")) -> dict:
    if range_ not in {*RANGE_MS, "all"}:
        raise HTTPException(status_code=400, detail="range must be 1d, 5d, 1m, or all")
    await refresh_recent_history()
    now_ms = int(time.time() * 1000)
    since_ms = PAIR_START_MS if range_ == "all" else max(PAIR_START_MS, now_ms - RANGE_MS[range_])
    aligned = await asyncio.to_thread(
        store.aligned_closes, KOREAN.inst_id, ADR.inst_id, since_ms
    )
    funding_points = await asyncio.to_thread(
        store.aligned_funding, KOREAN.inst_id, ADR.inst_id, since_ms
    )

    premiums: list[float] = []
    points: list[dict] = []
    for row in aligned:
        metrics = pair_metrics(row["korean_mark"], row["adr_mark"])
        premiums.append(metrics["premium_pct"])
        points.append({**row, **metrics})
    zscores = rolling_zscores(premiums, DEFAULT_Z_WINDOW)
    for point, zscore in zip(points, zscores, strict=True):
        point["zscore"] = zscore

    bounds = {
        instrument.key: dict(zip(("minimum", "maximum", "count"), store.bounds(instrument.inst_id)))
        for instrument in PAIR_INSTRUMENTS
    }
    return {
        "range": range_,
        "bar": "5m",
        "z_window": DEFAULT_Z_WINDOW,
        "start_ms": PAIR_START_MS,
        "points": points,
        "funding_points": funding_points,
        "recent_refresh": dict(recent_history_state),
        "bounds": bounds,
        "backfill": dict(backfill_state),
    }


@app.get("/api/v1/backfill-status")
async def backfill_status() -> dict:
    return dict(backfill_state)


@app.post("/api/v1/backfill", status_code=202)
async def trigger_backfill() -> dict:
    if not backfill_state["running"]:
        asyncio.create_task(backfill())
    return dict(backfill_state)
