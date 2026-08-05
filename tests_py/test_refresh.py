from unittest.mock import AsyncMock, Mock

import pytest

from backend import main


@pytest.mark.asyncio
async def test_recent_history_refresh_ingests_both_pair_legs_and_is_throttled(monkeypatch):
    mark_candles = AsyncMock(
        side_effect=[
            [{"ts": 1, "open": 1, "high": 1, "low": 1, "close": 1}],
            [{"ts": 1, "open": 2, "high": 2, "low": 2, "close": 2}],
        ]
    )
    funding_history = AsyncMock(
        side_effect=[
            [{"funding_time": 1, "funding_rate": 0.001, "realized_rate": 0.001}],
            [{"funding_time": 1, "funding_rate": 0.002, "realized_rate": 0.002}],
        ]
    )
    upsert_candles = Mock(side_effect=lambda _inst_id, rows: len(rows))
    upsert_funding = Mock(side_effect=lambda _inst_id, rows: len(rows))
    monkeypatch.setattr(main.okx, "mark_candles", mark_candles)
    monkeypatch.setattr(main.okx, "funding_history", funding_history)
    monkeypatch.setattr(main.store, "upsert_candles", upsert_candles)
    monkeypatch.setattr(main.store, "upsert_funding", upsert_funding)
    main.recent_history_state.update(
        last_attempt=None, last_success=None, error=None, rows_processed=0
    )

    await main.refresh_recent_history(force=True)
    await main.refresh_recent_history()

    assert mark_candles.await_count == 2
    assert funding_history.await_count == 2
    assert upsert_candles.call_count == 2
    assert upsert_funding.call_count == 2
    assert main.recent_history_state["rows_processed"] == 4
    assert main.recent_history_state["last_success"] is not None
    assert main.recent_history_state["error"] is None
