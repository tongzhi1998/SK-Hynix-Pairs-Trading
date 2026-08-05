from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import Lock


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS mark_candles (
                    inst_id TEXT NOT NULL,
                    ts INTEGER NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    confirmed INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (inst_id, ts)
                );

                CREATE TABLE IF NOT EXISTS funding_rates (
                    inst_id TEXT NOT NULL,
                    funding_time INTEGER NOT NULL,
                    funding_rate REAL NOT NULL,
                    realized_rate REAL,
                    PRIMARY KEY (inst_id, funding_time)
                );

                CREATE INDEX IF NOT EXISTS idx_mark_candles_ts
                    ON mark_candles(ts);
                """
            )

    def upsert_candles(self, inst_id: str, candles: list[dict]) -> int:
        if not candles:
            return 0
        rows = [
            (
                inst_id,
                row["ts"],
                row["open"],
                row["high"],
                row["low"],
                row["close"],
                int(row.get("confirmed", True)),
            )
            for row in candles
        ]
        with self._lock, self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO mark_candles
                    (inst_id, ts, open, high, low, close, confirmed)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(inst_id, ts) DO UPDATE SET
                    open=excluded.open,
                    high=excluded.high,
                    low=excluded.low,
                    close=excluded.close,
                    confirmed=excluded.confirmed
                """,
                rows,
            )
        return len(rows)

    def upsert_funding(self, inst_id: str, rows: list[dict]) -> int:
        if not rows:
            return 0
        values = [
            (
                inst_id,
                row["funding_time"],
                row["funding_rate"],
                row.get("realized_rate"),
            )
            for row in rows
        ]
        with self._lock, self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO funding_rates
                    (inst_id, funding_time, funding_rate, realized_rate)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(inst_id, funding_time) DO UPDATE SET
                    funding_rate=excluded.funding_rate,
                    realized_rate=excluded.realized_rate
                """,
                values,
            )
        return len(values)

    def bounds(self, inst_id: str) -> tuple[int | None, int | None, int]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT MIN(ts) AS minimum, MAX(ts) AS maximum, COUNT(*) AS count "
                "FROM mark_candles WHERE inst_id = ?",
                (inst_id,),
            ).fetchone()
        return row["minimum"], row["maximum"], row["count"]

    def aligned_closes(self, left: str, right: str, since_ms: int) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT left_leg.ts AS ts,
                       left_leg.close AS korean_mark,
                       right_leg.close AS adr_mark
                FROM mark_candles AS left_leg
                INNER JOIN mark_candles AS right_leg
                    ON right_leg.ts = left_leg.ts
                WHERE left_leg.inst_id = ?
                  AND right_leg.inst_id = ?
                  AND left_leg.ts >= ?
                  AND left_leg.confirmed = 1
                  AND right_leg.confirmed = 1
                ORDER BY left_leg.ts ASC
                """,
                (left, right, since_ms),
            ).fetchall()
        return [dict(row) for row in rows]

    def aligned_funding(self, left: str, right: str, since_ms: int) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT left_leg.funding_time AS ts,
                       COALESCE(left_leg.realized_rate, left_leg.funding_rate) AS korean_rate,
                       COALESCE(right_leg.realized_rate, right_leg.funding_rate) AS adr_rate
                FROM funding_rates AS left_leg
                INNER JOIN funding_rates AS right_leg
                    ON right_leg.funding_time = left_leg.funding_time
                WHERE left_leg.inst_id = ?
                  AND right_leg.inst_id = ?
                  AND left_leg.funding_time >= ?
                ORDER BY left_leg.funding_time ASC
                """,
                (left, right, since_ms),
            ).fetchall()
        return [dict(row) for row in rows]
