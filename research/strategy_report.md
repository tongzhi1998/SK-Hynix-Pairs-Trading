# SK Hynix / SKHY premium mean-reversion strategy

Research snapshot: 2026-08-05 23:15 Beijing time. This is a research result, not a live-trading recommendation.

## Conclusion

The premium shows short-run mean reversion, but the available sample is too short and regime-dependent to establish a stable long-run mean. The full-history average should not be used as a trading anchor. The preferred V1 signal is a robust, backward-looking exponential mean of the log premium, with a one-day half-life and explicit protection against level shifts.

The final eight-day holdout was profitable, but it produced only three trades under the preferred robust rule. That is promising enough to paper-trade, not enough to deploy meaningful capital.

## Measuring the mean

Use the log premium:

```text
x(t) = 100 × ln(10 × SKHY_mark(t) / SKHYNIX_mark(t))
```

This is preferable to averaging the displayed arithmetic percentage because log ratios are symmetric: an equal proportional widening and narrowing have equal magnitude.

Estimate location and scale with a robust EWMA:

- Warm up on at least seven calendar days before enabling trades. The estimator itself uses a one-day (288-bar) half-life.
- Initialize location with the median and scale with `1.4826 × median absolute deviation`.
- At each bar, calculate the signal from estimator values available before that bar. This avoids look-ahead bias.
- Cap each observation's contribution to the estimator at four current standard deviations. A temporary dislocation can still trigger a signal without immediately redefining the mean.
- Update both the mean and variance every five minutes.

The trading score is:

```text
z(t) = (x(t) - EWMA_mean(t-1)) / EWMA_scale(t-1)
```

Do not use the mean over all available history. The observed arithmetic premium averaged 26.79%, 30.85%, and 31.81% in successive thirds of the sample. That drift is economically large and makes an all-history z-score misleading.

## Proposed V1 rules

Use equal USDT notionals on the two legs. The 10:1 ADR ratio belongs in the signal calculation; it does not imply trading ten times the dollar exposure on one leg.

| State | Rule | Action |
|---|---|---|
| Flat, ADR rich | `2.0 ≤ z < 4.0` | Short SKHY, long SKHYNIX |
| Flat, ADR cheap | `-4.0 < z ≤ -2.0` | Long SKHY, short SKHYNIX |
| Short-premium position | `z ≤ 0.5` | Exit both legs |
| Long-premium position | `z ≥ -0.5` | Exit both legs |
| Either position | Adverse `|z| ≥ 4.0` | Stop both legs |
| Either position | Held for 48 hours | Exit both legs |
| After stop/time exit | Until `|z| < 2.0` | Block re-entry |

The re-entry block is important. Without it, a persistent level shift causes repeated stop-and-re-enter losses while the estimator catches up.

For initial paper trading, cap each leg at 10% of account equity and keep the two legs equal in USDT notional. After enough live observations, replace that simple cap with volatility targeting and a maximum loss budget per trade.

## Backtest design

- Data: 7,478 aligned, confirmed OKX five-minute mark candles from 2026-07-11 00:10 through 2026-08-05 23:15 Beijing time.
- Completeness: 100% of adjacent intervals were five minutes.
- Split: first 50% research/warm-up, next 20% model validation, final 30% untouched holdout.
- Signal: only information available before each simulated trade.
- Returns: equal-dollar pair return, `0.5 × side × (SKHY return - SKHYNIX return)`.
- Baseline cost: 7.5 basis points per one-way gross turnover. This represents the published 5 bp standard taker fee plus a 2.5 bp slippage allowance.
- Funding: excluded, as requested.
- Execution: mark-to-mark. Mark prices are not executable prices, so the test is optimistic when actual slippage exceeds the allowance.

## Results

### Model validation and holdout

The validation comparison selected a one-day rolling mean. On the untouched holdout it generated 13 trades, a 76.9% win rate, +2.59% net return, and -3.81% maximum drawdown at the 7.5 bp cost assumption.

The preferred robust one-day EWMA was fixed independently as the baseline. On the same holdout it generated three trades, all profitable, for +3.44% net return and -1.74% maximum drawdown. Across the combined validation and holdout period it generated five trades, four profitable, for +2.57% net return and -2.52% maximum drawdown.

These returns are on the backtest's gross pair capital, before any leverage. Annualized figures are intentionally not emphasized because the history and trade counts are too small.

### Cost sensitivity

For the validation-selected one-day rolling estimator, holdout net return was:

| One-way cost | Net return |
|---:|---:|
| 5.0 bp | +3.26% |
| 7.5 bp | +2.59% |
| 10.0 bp | +1.92% |
| 20.0 bp | -0.70% |

The result is therefore execution-sensitive. A signal based on marks should not be traded until realized two-leg slippage is measured.

### Stability diagnostics

- AR(1) coefficient of the log premium: 0.998.
- Naive implied half-life: about 28.4 hours.
- Full-sample arithmetic premium: mean 29.82%, median 31.39%, standard deviation 5.40 percentage points.
- Successive-third means: 26.79%, 30.85%, and 31.81%.
- The robust strategy lost 3.77% in the first four-day block after warm-up, during the launch regime.

The half-life estimate supports a one-day adaptive mean, but it does not prove stationarity. The shifting subperiod means and the early loss are evidence that the equilibrium level can move.

## Deployment decision

Keep the strategy in paper-trading mode. A reasonable promotion gate is at least 60–90 calendar days of history, 30–50 out-of-sample completed trades, positive results at 10 bp one-way costs, and no single subperiod accounting for most profits. Re-run the frozen rules weekly; do not retune thresholds after each loss.

Before live deployment, record actual fills for both legs and re-run the test with observed spread/slippage. Also add stale-mark and data-gap guards, simultaneous two-leg execution logic, maximum leg imbalance duration, and a kill switch for abrupt contract/index methodology changes.

## Reproduce

```bash
python3 research/mean_reversion_backtest.py --json
PYTHONPATH=. .venv/bin/pytest -q
```

## References

- Gatev, Goetzmann, and Rouwenhorst, [Pairs Trading: Performance of a Relative Value Arbitrage Rule](https://www.nber.org/papers/w7032). The paper also warns that microstructure effects can explain part of apparent pairs-trading profit.
- Engle and Granger, [Co-integration and Error Correction: Representation, Estimation, and Testing](https://doi.org/10.2307/1913236). A stable residual relationship should ultimately be tested with substantially more history.
- OKX, [TradFi/Stock Perpetuals FAQ](https://www.okx.com/en-us/help/stock-perpetuals-faq). The published standard example uses a 0.05% taker fee and 0.02% maker fee; the account's actual tier should replace this assumption.
