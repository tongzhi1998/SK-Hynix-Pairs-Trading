from pathlib import Path

from backend.storage import Store


def test_aligned_funding_returns_only_shared_collection_events(tmp_path: Path):
    store = Store(tmp_path / "test.sqlite3")
    shared_times = [1_000, 2_000, 3_000]
    store.upsert_funding(
        "LEFT",
        [
            {
                "funding_time": timestamp,
                "funding_rate": 0.001,
                "realized_rate": 0.001 + index / 10_000,
            }
            for index, timestamp in enumerate([*shared_times, 4_000])
        ],
    )
    store.upsert_funding(
        "RIGHT",
        [
            {
                "funding_time": timestamp,
                "funding_rate": -0.001,
                "realized_rate": -0.001 - index / 10_000,
            }
            for index, timestamp in enumerate(shared_times)
        ],
    )

    result = store.aligned_funding("LEFT", "RIGHT", 1_000)

    assert [point["ts"] for point in result] == shared_times
    assert result[0] == {"ts": 1_000, "korean_rate": 0.001, "adr_rate": -0.001}
