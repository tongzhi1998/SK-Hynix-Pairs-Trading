from unittest.mock import AsyncMock

import pytest

from backend.okx import OkxClient


@pytest.mark.asyncio
async def test_funding_rate_keeps_current_collection_time_separate_from_following_cycle():
    client = OkxClient.__new__(OkxClient)
    client._get = AsyncMock(
        return_value=[
            {
                "fundingRate": "0.0001",
                "settFundingRate": "0.0002",
                "fundingTime": "1785859200000",
                "nextFundingTime": "1785888000000",
                "ts": "1785853824212",
            }
        ]
    )

    result = await client.funding_rate("SKHYNIX-USDT-SWAP")

    assert result["funding_time"] == 1_785_859_200_000
    assert result["next_funding_time"] == 1_785_888_000_000


@pytest.mark.asyncio
async def test_trailing_24h_change_uses_nearest_five_minute_mark_candle():
    client = OkxClient.__new__(OkxClient)
    as_of_ms = 1_800_000_000_000
    target_ms = as_of_ms - 24 * 60 * 60 * 1000
    client.mark_candles = AsyncMock(
        return_value=[
            {"ts": target_ms + 180_000, "open": 100.0},
            {"ts": target_ms - 120_000, "open": 101.0},
            {"ts": target_ms - 420_000, "open": 99.0},
        ]
    )

    change = await client.trailing_24h_change("SPY-USDT-SWAP", 102.0, as_of_ms)

    assert change == pytest.approx((102.0 / 101.0 - 1.0) * 100.0)
    client.mark_candles.assert_awaited_once_with(
        "SPY-USDT-SWAP",
        bar="5m",
        after=target_ms + 5 * 60 * 1000,
        limit=3,
        history=True,
    )
