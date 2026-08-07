"""Leakage-free research backtest for the SK Hynix / SKHY premium.

The signal is computed from OKX five-minute mark candles already stored by the
dashboard. Funding is deliberately excluded. Mark prices are not executable
prices, so the command applies an explicit fee/slippage assumption and prints
several cost sensitivities.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from zoneinfo import ZoneInfo

BEIJING = ZoneInfo("Asia/Shanghai")
KOREAN = "SKHYNIX-USDT-SWAP"
ADR = "SKHY-USDT-SWAP"
ADR_RATIO = 10.0
BARS_PER_DAY = 288


@dataclass(frozen=True)
class Bar:
    ts_ms: int
    korean: float
    adr: float
    log_premium_pct: float
    premium_pct: float


@dataclass(frozen=True)
class StrategySpec:
    estimator: str
    lookback_bars: int
    entry_z: float = 2.0
    exit_z: float = 0.5
    stop_z: float = 4.0
    max_hold_bars: int = 2 * BARS_PER_DAY

    @property
    def name(self) -> str:
        unit = f"{self.lookback_bars / BARS_PER_DAY:g}d"
        return f"{self.estimator}-{unit}"


@dataclass
class Trade:
    entry_ts: int
    exit_ts: int
    direction: str
    entry_z: float
    exit_z: float
    bars_held: int
    net_return: float
    exit_reason: str


@dataclass
class Result:
    name: str
    start: str
    end: str
    cost_bps_one_way: float
    trades: int
    wins: int
    win_rate_pct: float | None
    net_return_pct: float
    gross_return_pct: float
    max_drawdown_pct: float
    daily_sharpe: float | None
    average_trade_pct: float | None
    median_trade_pct: float | None
    average_hold_hours: float | None
    exposure_pct: float
    profit_factor: float | None


def load_bars(database: Path) -> list[Bar]:
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            """
            SELECT korean.ts, korean.close, adr.close
            FROM mark_candles AS korean
            JOIN mark_candles AS adr ON adr.ts = korean.ts
            WHERE korean.inst_id = ? AND adr.inst_id = ?
              AND korean.confirmed = 1 AND adr.confirmed = 1
            ORDER BY korean.ts
            """,
            (KOREAN, ADR),
        ).fetchall()

    bars: list[Bar] = []
    for ts_ms, korean, adr in rows:
        ratio = ADR_RATIO * float(adr) / float(korean)
        bars.append(
            Bar(
                ts_ms=int(ts_ms),
                korean=float(korean),
                adr=float(adr),
                log_premium_pct=100.0 * math.log(ratio),
                premium_pct=100.0 * (ratio - 1.0),
            )
        )
    if len(bars) < 3 * BARS_PER_DAY:
        raise RuntimeError("At least three days of aligned confirmed history are required")
    return bars


def rolling_scores(values: list[float], lookback: int) -> list[float | None]:
    """Score each observation using only the preceding `lookback` observations."""
    scores: list[float | None] = [None] * len(values)
    window: deque[float] = deque()
    total = 0.0
    total_sq = 0.0
    for index, value in enumerate(values):
        if len(window) == lookback:
            mean = total / lookback
            variance = max(total_sq / lookback - mean * mean, 0.0)
            scale = math.sqrt(variance)
            scores[index] = None if scale < 1e-10 else (value - mean) / scale
        window.append(value)
        total += value
        total_sq += value * value
        if len(window) > lookback:
            old = window.popleft()
            total -= old
            total_sq -= old * old
    return scores


def robust_ewma_scores(
    values: list[float], half_life: int, *, warmup: int = BARS_PER_DAY, clip: float = 4.0
) -> list[float | None]:
    """Past-only EWMA location/scale with capped updates to limit outlier distortion."""
    scores: list[float | None] = [None] * len(values)
    warmup = max(warmup, min(half_life, 3 * BARS_PER_DAY))
    if len(values) <= warmup:
        return scores

    initial = values[:warmup]
    location = statistics.median(initial)
    deviations = [abs(value - location) for value in initial]
    # 1.4826 makes median absolute deviation comparable to standard deviation.
    scale = max(1.4826 * statistics.median(deviations), 1e-6)
    variance = scale * scale
    alpha = 1.0 - math.exp(math.log(0.5) / half_life)

    for index in range(warmup, len(values)):
        value = values[index]
        scale = max(math.sqrt(variance), 1e-6)
        residual = value - location
        scores[index] = residual / scale

        capped = max(-clip * scale, min(clip * scale, residual))
        location += alpha * capped
        variance = (1.0 - alpha) * (variance + alpha * capped * capped)
    return scores


def make_scores(values: list[float], spec: StrategySpec) -> list[float | None]:
    if spec.estimator == "rolling":
        return rolling_scores(values, spec.lookback_bars)
    if spec.estimator == "robust-ewma":
        return robust_ewma_scores(values, spec.lookback_bars)
    raise ValueError(f"Unknown estimator: {spec.estimator}")


def _beijing_iso(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).astimezone(BEIJING).isoformat()


def backtest(
    bars: list[Bar],
    scores: list[float | None],
    spec: StrategySpec,
    start: int,
    end: int,
    cost_bps_one_way: float,
) -> tuple[Result, list[Trade]]:
    if not (0 <= start < end <= len(bars)):
        raise ValueError("Invalid test range")

    position = 0  # +1 long ADR/short Korean; -1 short ADR/long Korean.
    blocked_until_neutral = False
    held = 0
    entry_ts = 0
    entry_z = 0.0
    trade_pnl = 0.0
    trades: list[Trade] = []
    net_equity = 1.0
    gross_equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    invested_bars = 0
    daily_returns: dict[str, float] = defaultdict(float)
    cost_rate = cost_bps_one_way / 10_000.0

    def apply_return(value: float, day: str, *, is_cost: bool = False) -> None:
        nonlocal net_equity, trade_pnl, peak, max_drawdown
        net_equity *= 1.0 + value
        daily_returns[day] += value
        if position != 0 or is_cost:
            trade_pnl += value
        peak = max(peak, net_equity)
        max_drawdown = min(max_drawdown, net_equity / peak - 1.0)

    for index in range(start, end - 1):
        score = scores[index]
        target = position
        reason = ""

        if score is not None:
            if position == 0:
                if abs(score) < spec.entry_z:
                    blocked_until_neutral = False
                if (
                    not blocked_until_neutral
                    and spec.entry_z <= score < spec.stop_z
                ):
                    target = -1
                elif (
                    not blocked_until_neutral
                    and -spec.stop_z < score <= -spec.entry_z
                ):
                    target = 1
            else:
                held += 1
                reverted = (position == -1 and score <= spec.exit_z) or (
                    position == 1 and score >= -spec.exit_z
                )
                stopped = (position == -1 and score >= spec.stop_z) or (
                    position == 1 and score <= -spec.stop_z
                )
                if reverted:
                    target, reason = 0, "mean"
                elif stopped:
                    target, reason = 0, "stop"
                    blocked_until_neutral = True
                elif held >= spec.max_hold_bars:
                    target, reason = 0, "time"
                    blocked_until_neutral = True

        day = datetime.fromtimestamp(bars[index].ts_ms / 1000, tz=BEIJING).date().isoformat()
        if target != position:
            turnover = abs(target - position)
            apply_return(-cost_rate * turnover, day, is_cost=True)
            if position == 0 and target != 0:
                entry_ts = bars[index].ts_ms
                entry_z = float(score)
                held = 0
            elif position != 0 and target == 0:
                trades.append(
                    Trade(
                        entry_ts=entry_ts,
                        exit_ts=bars[index].ts_ms,
                        direction="long ADR / short Korean" if position == 1 else "short ADR / long Korean",
                        entry_z=entry_z,
                        exit_z=float(score) if score is not None else math.nan,
                        bars_held=held,
                        net_return=trade_pnl,
                        exit_reason=reason,
                    )
                )
                trade_pnl = 0.0
                held = 0
            position = target

        if position != 0:
            invested_bars += 1
            korean_return = bars[index + 1].korean / bars[index].korean - 1.0
            adr_return = bars[index + 1].adr / bars[index].adr - 1.0
            pair_return = 0.5 * position * (adr_return - korean_return)
            gross_equity *= 1.0 + pair_return
            apply_return(pair_return, day)

    if position != 0:
        final = end - 1
        day = datetime.fromtimestamp(bars[final].ts_ms / 1000, tz=BEIJING).date().isoformat()
        apply_return(-cost_rate, day, is_cost=True)
        trades.append(
            Trade(
                entry_ts=entry_ts,
                exit_ts=bars[final].ts_ms,
                direction="long ADR / short Korean" if position == 1 else "short ADR / long Korean",
                entry_z=entry_z,
                exit_z=float(scores[final]) if scores[final] is not None else math.nan,
                bars_held=held,
                net_return=trade_pnl,
                exit_reason="end",
            )
        )

    trade_returns = [trade.net_return for trade in trades]
    wins = sum(value > 0 for value in trade_returns)
    gains = sum(value for value in trade_returns if value > 0)
    losses = -sum(value for value in trade_returns if value < 0)
    day_values = list(daily_returns.values())
    daily_sharpe = None
    if len(day_values) >= 2 and statistics.stdev(day_values) > 0:
        daily_sharpe = statistics.mean(day_values) / statistics.stdev(day_values) * math.sqrt(365)

    result = Result(
        name=spec.name,
        start=_beijing_iso(bars[start].ts_ms),
        end=_beijing_iso(bars[end - 1].ts_ms),
        cost_bps_one_way=cost_bps_one_way,
        trades=len(trades),
        wins=wins,
        win_rate_pct=100.0 * wins / len(trades) if trades else None,
        net_return_pct=100.0 * (net_equity - 1.0),
        gross_return_pct=100.0 * (gross_equity - 1.0),
        max_drawdown_pct=100.0 * max_drawdown,
        daily_sharpe=daily_sharpe,
        average_trade_pct=100.0 * statistics.mean(trade_returns) if trades else None,
        median_trade_pct=100.0 * statistics.median(trade_returns) if trades else None,
        average_hold_hours=(statistics.mean(t.bars_held for t in trades) * 5.0 / 60.0)
        if trades
        else None,
        exposure_pct=100.0 * invested_bars / max(end - start - 1, 1),
        profit_factor=gains / losses if losses > 0 else (math.inf if gains > 0 else None),
    )
    return result, trades


def ar1_diagnostics(values: list[float]) -> dict[str, float | None]:
    previous = values[:-1]
    current = values[1:]
    x_mean = statistics.mean(previous)
    y_mean = statistics.mean(current)
    denominator = sum((value - x_mean) ** 2 for value in previous)
    phi = (
        sum((x - x_mean) * (y - y_mean) for x, y in zip(previous, current)) / denominator
        if denominator
        else math.nan
    )
    half_life_bars = -math.log(2.0) / math.log(phi) if 0.0 < phi < 1.0 else None
    return {
        "ar1_phi": phi,
        "implied_half_life_hours": half_life_bars * 5.0 / 60.0 if half_life_bars else None,
    }


def profile(bars: list[Bar]) -> dict:
    values = [bar.log_premium_pct for bar in bars]
    premiums = [bar.premium_pct for bar in bars]
    gap_counts = defaultdict(int)
    for left, right in pairwise(bars):
        gap_counts[(right.ts_ms - left.ts_ms) // 60_000] += 1

    thirds = []
    for part in range(3):
        start = part * len(bars) // 3
        end = (part + 1) * len(bars) // 3
        segment = premiums[start:end]
        thirds.append(
            {
                "start": _beijing_iso(bars[start].ts_ms),
                "end": _beijing_iso(bars[end - 1].ts_ms),
                "mean_premium_pct": statistics.mean(segment),
                "median_premium_pct": statistics.median(segment),
                "std_premium_points": statistics.stdev(segment),
            }
        )
    return {
        "bars": len(bars),
        "start": _beijing_iso(bars[0].ts_ms),
        "end": _beijing_iso(bars[-1].ts_ms),
        "five_minute_intervals_pct": 100.0 * gap_counts[5] / max(len(bars) - 1, 1),
        "premium_pct": {
            "mean": statistics.mean(premiums),
            "median": statistics.median(premiums),
            "std": statistics.stdev(premiums),
            "minimum": min(premiums),
            "maximum": max(premiums),
        },
        "ar1": ar1_diagnostics(values),
        "thirds": thirds,
    }


def segment_stability(
    bars: list[Bar],
    scores: list[float | None],
    spec: StrategySpec,
    cost_bps: float,
) -> list[dict]:
    """Evaluate the same frozen rule in non-overlapping four-day blocks."""
    block = 4 * BARS_PER_DAY
    start = max(spec.lookback_bars, BARS_PER_DAY)
    results = []
    while start < len(bars) - BARS_PER_DAY:
        end = min(start + block, len(bars))
        result, _ = backtest(bars, scores, spec, start, end, cost_bps)
        results.append(asdict(result))
        start = end
    return results


def rounded(value):
    if isinstance(value, float):
        if math.isinf(value):
            return "inf"
        return round(value, 4)
    if isinstance(value, list):
        return [rounded(item) for item in value]
    if isinstance(value, dict):
        return {key: rounded(item) for key, item in value.items()}
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path("data/hynix_basis.sqlite3"))
    parser.add_argument("--cost-bps", type=float, default=7.5)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    bars = load_bars(args.database)
    values = [bar.log_premium_pct for bar in bars]
    train_end = len(bars) // 2
    validation_end = 7 * len(bars) // 10

    candidates = [
        StrategySpec("rolling", BARS_PER_DAY),
        StrategySpec("rolling", 3 * BARS_PER_DAY),
        StrategySpec("rolling", 7 * BARS_PER_DAY),
        StrategySpec("robust-ewma", BARS_PER_DAY // 2),
        StrategySpec("robust-ewma", BARS_PER_DAY),
        StrategySpec("robust-ewma", 3 * BARS_PER_DAY),
    ]
    score_cache = {spec.name: make_scores(values, spec) for spec in candidates}

    validation = []
    for spec in candidates:
        result, _ = backtest(
            bars,
            score_cache[spec.name],
            spec,
            train_end,
            validation_end,
            args.cost_bps,
        )
        validation.append(result)

    # Selection happens on validation only. Requiring at least two completed trades
    # prevents a single lucky position from winning the small model comparison.
    eligible = [item for item in validation if item.trades >= 2]
    selected_result = max(eligible or validation, key=lambda item: item.net_return_pct)
    selected = next(spec for spec in candidates if spec.name == selected_result.name)

    holdout = []
    for cost in (5.0, 7.5, 10.0, 20.0):
        result, trades = backtest(
            bars,
            score_cache[selected.name],
            selected,
            validation_end,
            len(bars),
            cost,
        )
        holdout.append({"result": asdict(result), "trades": [asdict(trade) for trade in trades]})

    baseline = StrategySpec("robust-ewma", BARS_PER_DAY)
    baseline_scores = score_cache[baseline.name]
    baseline_holdout, baseline_trades = backtest(
        bars,
        baseline_scores,
        baseline,
        validation_end,
        len(bars),
        args.cost_bps,
    )
    baseline_post_research, _ = backtest(
        bars,
        baseline_scores,
        baseline,
        train_end,
        len(bars),
        args.cost_bps,
    )

    threshold_sensitivity = []
    for entry_z in (1.5, 2.0, 2.5):
        adjusted = StrategySpec(
            selected.estimator,
            selected.lookback_bars,
            entry_z=entry_z,
            exit_z=0.5,
        )
        result, _ = backtest(
            bars,
            score_cache[selected.name],
            adjusted,
            validation_end,
            len(bars),
            args.cost_bps,
        )
        threshold_sensitivity.append(asdict(result) | {"entry_z": entry_z})

    output = {
        "method": {
            "split": "first 50% warm-up/research, next 20% validation, final 30% untouched holdout",
            "signal_variable": "100 * log(10 * SKHY mark / SKHYNIX mark)",
            "position_return": "0.5 * side * (SKHY return - SKHYNIX return)",
            "funding_included": False,
            "marks_executable": False,
        },
        "profile": profile(bars),
        "validation": [asdict(item) for item in validation],
        "selected_on_validation": asdict(selected),
        "holdout_cost_sensitivity": holdout,
        "pre_registered_baseline_holdout": {
            "spec": asdict(baseline),
            "result": asdict(baseline_holdout),
            "trades": [asdict(trade) for trade in baseline_trades],
        },
        "baseline_validation_plus_holdout": asdict(baseline_post_research),
        "baseline_four_day_stability": segment_stability(
            bars, baseline_scores, baseline, args.cost_bps
        ),
        "holdout_threshold_sensitivity": threshold_sensitivity,
    }
    print(json.dumps(rounded(output), indent=2 if args.json else None))


if __name__ == "__main__":
    main()
