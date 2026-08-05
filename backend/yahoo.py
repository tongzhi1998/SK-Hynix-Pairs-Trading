from __future__ import annotations

from typing import Any
from urllib.parse import quote

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
    return {
        "mark": mark,
        "change_pct": (mark / previous_close - 1.0) * 100.0,
        "previous_close": previous_close,
        "ts": int(timestamp) * 1000,
        "currency": meta.get("currency") or "KRW",
    }
