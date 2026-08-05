from __future__ import annotations

import math
from collections import deque

from .config import ADR_RATIO, DEFAULT_Z_WINDOW


def pair_metrics(korean_mark: float, adr_mark: float) -> dict[str, float]:
    if korean_mark <= 0 or adr_mark <= 0:
        raise ValueError("Mark prices must be positive")
    adr_equivalent = ADR_RATIO * adr_mark
    spread = adr_equivalent - korean_mark
    premium_pct = (adr_equivalent / korean_mark - 1.0) * 100.0
    return {
        "adr_equivalent": adr_equivalent,
        "spread": spread,
        "premium_pct": premium_pct,
    }


def funding_carry(korean_rate: float, adr_rate: float) -> dict[str, float]:
    long_korean = adr_rate - korean_rate
    return {
        "long_korean_short_adr": long_korean,
        "short_korean_long_adr": -long_korean,
    }


def rolling_zscores(values: list[float], window: int = DEFAULT_Z_WINDOW) -> list[float | None]:
    if window < 2:
        raise ValueError("Window must be at least two")

    result: list[float | None] = []
    queue: deque[float] = deque()
    total = 0.0
    total_sq = 0.0

    for value in values:
        queue.append(value)
        total += value
        total_sq += value * value
        if len(queue) > window:
            old = queue.popleft()
            total -= old
            total_sq -= old * old

        if len(queue) < window:
            result.append(None)
            continue

        mean = total / window
        variance = max((total_sq / window) - mean * mean, 0.0)
        stddev = math.sqrt(variance)
        result.append(0.0 if stddev == 0 else (value - mean) / stddev)

    return result
