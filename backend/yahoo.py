from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx


class YahooError(RuntimeError):
    pass


class YahooClient:
    def __init__(self):
        self.client = httpx.AsyncClient(
            base_url="https://query2.finance.yahoo.com",
            timeout=httpx.Timeout(15.0),
            headers={"User-Agent": "Mozilla/5.0 (compatible; hynix-basis-dashboard/0.1)"},
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def index_quote(self, symbol: str) -> dict:
        response = await self.client.get(
            f"/v8/finance/chart/{quote(symbol, safe='')}",
            params={"interval": "1m", "range": "1d"},
        )
        response.raise_for_status()
        return parse_index_chart(response.json())


def parse_index_chart(payload: dict[str, Any]) -> dict:
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise YahooError(chart["error"].get("description") or "Yahoo Finance error")
    results = chart.get("result") or []
    if not results:
        raise YahooError("Yahoo Finance returned no index data")

    result = results[0]
    meta = result.get("meta") or {}
    timestamps = result.get("timestamp") or []
    closes = (((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or [])
    latest_close = next((value for value in reversed(closes) if value is not None), None)
    mark = meta.get("regularMarketPrice") or latest_close
    previous_close = meta.get("chartPreviousClose") or meta.get("previousClose")
    timestamp = meta.get("regularMarketTime") or (timestamps[-1] if timestamps else None)
    if mark is None or previous_close in (None, 0) or timestamp is None:
        raise YahooError("Yahoo Finance index response is missing price metadata")

    mark = float(mark)
    previous_close = float(previous_close)
    session = parse_market_session(meta)
    return {
        "mark": mark,
        "change_pct": (mark / previous_close - 1.0) * 100.0,
        "previous_close": previous_close,
        "ts": int(timestamp) * 1000,
        "currency": meta.get("currency") or "KRW",
        "session": session,
    }


def parse_market_session(meta: dict[str, Any]) -> dict | None:
    regular = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    start = regular.get("start")
    end = regular.get("end")
    timezone = meta.get("exchangeTimezoneName")
    if start is None or end is None or not timezone:
        return None

    start_ms = int(start) * 1000
    end_ms = int(end) * 1000
    return {
        "regular_start": start_ms,
        "regular_end": end_ms,
        "next_regular_start": next_weekday_session_start(start_ms, timezone),
        "timezone": timezone,
    }


def next_weekday_session_start(start_ms: int, timezone: str) -> int:
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        return start_ms + 24 * 60 * 60 * 1000

    current = datetime.fromtimestamp(start_ms / 1000, zone)
    next_date = current.date() + timedelta(days=1)
    while next_date.weekday() >= 5:
        next_date += timedelta(days=1)
    next_start = datetime(
        next_date.year,
        next_date.month,
        next_date.day,
        current.hour,
        current.minute,
        current.second,
        tzinfo=zone,
    )
    return int(next_start.timestamp() * 1000)
