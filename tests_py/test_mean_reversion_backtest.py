from research.mean_reversion_backtest import (
    ADR_RATIO,
    Bar,
    StrategySpec,
    backtest,
    robust_ewma_scores,
    rolling_scores,
)


def make_bar(index: int, korean: float, ratio: float) -> Bar:
    adr = ratio * korean / ADR_RATIO
    return Bar(
        ts_ms=index * 300_000,
        korean=korean,
        adr=adr,
        log_premium_pct=100.0,
        premium_pct=100.0 * (ratio - 1.0),
    )


def test_rolling_score_uses_only_prior_observations():
    scores = rolling_scores([1.0, 1.0, 2.0, 100.0], lookback=3)

    assert scores[:3] == [None, None, None]
    # If the current value leaked into its own mean and scale, this score would be small.
    assert scores[3] is not None and scores[3] > 100


def test_robust_ewma_does_not_score_warmup_values():
    values = [1.0] * 288 + [2.0]
    scores = robust_ewma_scores(values, half_life=144)

    assert all(score is None for score in scores[:288])
    assert scores[288] is not None and scores[288] > 0


def test_costs_reduce_the_same_strategy_result():
    ratios = [1.00, 1.00, 1.04, 1.02, 1.00, 1.00]
    bars = [make_bar(index, 100.0, ratio) for index, ratio in enumerate(ratios)]
    scores = [None, 0.0, 2.5, 1.5, 0.0, 0.0]
    spec = StrategySpec("rolling", 1, entry_z=2.0, exit_z=0.5)

    free, _ = backtest(bars, scores, spec, 0, len(bars), 0.0)
    costly, _ = backtest(bars, scores, spec, 0, len(bars), 10.0)

    assert free.trades == costly.trades == 1
    assert free.net_return_pct > costly.net_return_pct


def test_stop_does_not_reenter_until_signal_returns_to_neutral():
    ratios = [1.00] * 9
    bars = [make_bar(index, 100.0, ratio) for index, ratio in enumerate(ratios)]
    scores = [0.0, 2.5, 4.1, 4.5, 3.0, 1.0, 0.0, 2.5, 0.0]
    spec = StrategySpec("rolling", 1, entry_z=2.0, exit_z=0.5, stop_z=4.0)

    result, trades = backtest(bars, scores, spec, 0, len(bars), 0.0)

    assert result.trades == 2
    assert [trade.entry_ts for trade in trades] == [300_000, 2_100_000]
