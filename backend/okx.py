from __future__ import annotations

import asyncio
from typing import Any

import httpx

from .config import OKX_BASE_URL


class OkxError(RuntimeError):
    pass


class OkxClient:
    def __init__(self, base_url: str = OKX_BASE_URL):
        self.client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(15.0),
            headers={"User-Agent": "hynix-basis-dashboard/0.1"},
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def _get(self, path: str, **params: Any) -> list[dict]:
        response = await self.client.get(path, params=params)
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != "0":
            raise OkxError(payload.get("msg") or f"OKX error {payload.get('code')}")
        return payload.get("data", [])

    async def mark_price(self, inst_id: str) -> dict:
        data = await self._get(
            "/api/v5/public/mark-price", instType="SWAP", instId=inst_id
        )
        if not data:
            raise OkxError(f"No mark price for {inst_id}")
        row = data[0]
        return {"mark": float(row["markPx"]), "ts": int(row["ts"])}

    async def index_price(self, inst_id: str) -> dict:
        data = await self._get("/api/v5/market/index-tickers", instId=inst_id)
        if not data:
            raise OkxError(f"No index price for {inst_id}")
        row = data[0]
        return {"index": float(row["idxPx"]), "ts": int(row["ts"])}

    async def funding_rate(self, inst_id: str) -> dict:
        data = await self._get("/api/v5/public/funding-rate", instId=inst_id)
        if not data:
            raise OkxError(f"No funding rate for {inst_id}")
        row = data[0]
        return {
            "current": float(row.get("fundingRate") or 0),
            "settled": float(row.get("settFundingRate") or 0),
            "funding_time": int(row["fundingTime"]),
            "next_funding_time": int(row["nextFundingTime"]),
            "ts": int(row["ts"]),
        }

    async def mark_candles(
        self,
        inst_id: str,
        *,
        bar: str = "5m",
        after: int | None = None,
        limit: int = 100,
        history: bool = True,
    ) -> list[dict]:
        path = (
            "/api/v5/market/history-mark-price-candles"
            if history
            else "/api/v5/market/mark-price-candles"
        )
        params: dict[str, Any] = {"instId": inst_id, "bar": bar, "limit": limit}
        if after is not None:
            params["after"] = str(after)
        data = await self._get(path, **params)
        return [
            {
                "ts": int(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "confirmed": row[5] == "1" if len(row) > 5 else True,
            }
            for row in data
        ]

    async def funding_history(
        self, inst_id: str, *, after: int | None = None, limit: int = 100
    ) -> list[dict]:
        params: dict[str, Any] = {"instId": inst_id, "limit": limit}
        if after is not None:
            params["after"] = str(after)
        data = await self._get("/api/v5/public/funding-rate-history", **params)
        return [
            {
                "funding_time": int(row["fundingTime"]),
                "funding_rate": float(row.get("fundingRate") or 0),
                "realized_rate": (
                    float(row["realizedRate"]) if row.get("realizedRate") else None
                ),
            }
            for row in data
        ]

    async def trailing_24h_change(
        self, inst_id: str, mark: float, as_of_ms: int
    ) -> float | None:
        target_ms = as_of_ms - 24 * 60 * 60 * 1000
        candles = await self.mark_candles(
            inst_id,
            bar="5m",
            after=target_ms + 5 * 60 * 1000,
            limit=3,
            history=True,
        )
        if not candles:
            return None
        reference = min(candles, key=lambda candle: abs(candle["ts"] - target_ms))["open"]
        if reference <= 0:
            return None
        return (mark / reference - 1.0) * 100.0

    async def backfill_mark_candles(
        self,
        inst_id: str,
        start_ms: int,
        on_page,
    ) -> int:
        cursor: int | None = None
        seen_oldest: int | None = None
        total = 0

        while True:
            page = await self.mark_candles(inst_id, after=cursor, limit=100)
            if not page:
                break
            relevant = [row for row in page if row["ts"] >= start_ms]
            total += await on_page(relevant)
            oldest = min(row["ts"] for row in page)
            if oldest <= start_ms or oldest == seen_oldest:
                break
            seen_oldest = oldest
            cursor = oldest
            await asyncio.sleep(0.12)
        return total

    async def backfill_funding(self, inst_id: str, start_ms: int, on_page) -> int:
        cursor: int | None = None
        seen_oldest: int | None = None
        total = 0

        while True:
            page = await self.funding_history(inst_id, after=cursor, limit=100)
            if not page:
                break
            relevant = [row for row in page if row["funding_time"] >= start_ms]
            total += await on_page(relevant)
            oldest = min(row["funding_time"] for row in page)
            if oldest <= start_ms or oldest == seen_oldest:
                break
            seen_oldest = oldest
            cursor = oldest
            await asyncio.sleep(0.12)
        return total
