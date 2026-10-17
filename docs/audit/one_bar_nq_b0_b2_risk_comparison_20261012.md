# B0 versus B2 risk comparison

Status: **Historical accounting review complete. Exploratory. Not approved for live use.**

## Question and result

This review asks if B2's lower dollar result comes mainly from smaller exposure. The answer is **no for the full comparison**. B2 uses most of its declared stop-risk budget. B2 has weaker trade and risk-adjusted results after the MNQ listing date. Its lower contract exposure does reduce dollar losses in some periods, including 2026.

B0 earned **$166,107.92** on 5,462 closed trades. B2 lost **$142,674.93** on 5,459 recorded closed trades across the full 2013–2026 history. B2's pre-May 6, 2019 results are counterfactual. MNQ did not exist then. On and after the launch date, both strategies use the same BID-only CFD proxy, not dated CME futures.

| Period | Ledger | Trades | Net P&L | Win rate | Profit factor | Expectancy / trade | R expectancy / trade | Daily Sharpe | Calmar* |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2013–2026 | B0 | 5,462 | $166,108 | 47.8% | 1.267 | $30.41 | +0.0304R | 1.28 | 0.54 |
| 2013–2026 | B2 | 5,459 | −$142,675 | 42.9% | 0.863 | −$26.14 | −0.0255R | −0.88 | −0.04 |
| May 6, 2019–July 14, 2026 | B0 | 3,084 | $169,969 | 51.7% | 1.341 | $55.11 | +0.0551R | 1.87 | 1.50 |
| May 6, 2019–July 14, 2026 | B2 | 3,077 | $104,615 | 49.3% | 1.209 | $34.00 | +0.0357R | 1.17 | 0.86 |
| 2020–2025 | B0 | 2,586 | $178,830 | 52.4% | 1.441 | $69.15 | +0.0692R | 2.29 | 1.89 |
| 2020–2025 | B2 | 2,582 | $112,699 | 50.3% | 1.281 | $43.65 | +0.0464R | 1.52 | 1.30 |
| 2026 through July 14 | B0 | 238 | −$14,167 | 47.5% | 0.806 | −$59.53 | −0.0595R | −1.83 | −1.59 |
| 2026 through July 14 | B2 | 237 | −$9,704 | 47.7% | 0.765 | −$40.95 | −0.0488R | −1.87 | −1.59 |

R is closed trade net P&L divided by the ledger's ex-ante risk budget. B0 uses $1,000 per trade. B2 uses its saved `nominal_risk_usd`. A positive win rate does not imply positive expectancy. The tables show that B2's post-launch risk-unit expectancy is positive, but it is below B0's. In 2026 both are negative. B2 has a slightly less negative R expectancy and a slightly worse daily Sharpe.

\* Calmar uses a fixed illustrative $1,000,000 starting balance. It uses the same daily P&L proxy described below. It is not a margin or account survivability result.

## Is B2 undersized?

B2's median nominal-risk use is **97.8%** of $1,000 over the full history, **95.6%** after MNQ launch, and **91.0%** in 2026. Mean use is 96.2%, 94.4%, and 89.9%, respectively. This does not show material underuse of its declared stop-risk budget.

B2's median absolute position size is 16 MNQ for the full history, 10 MNQ after launch, and 4 MNQ in 2026. Those are 1.6, 1.0, and 0.4 NQ-equivalent contracts. Quantities on short trades are signed; absolute quantity is required for exposure calculations. This lower point exposure can explain why B2's 2026 dollar loss is smaller than B0's. It does not explain the weaker full-history or post-launch quality measures.

As a non-native algebra diagnostic, the script rescales each B2 trade's net P&L, planned risk, and recorded fees/slippage by `10 / abs(actual MNQ quantity)`. The positive factor preserves the win/loss sign and the R multiple for each trade. At fixed exposure of 10 MNQ (one NQ-equivalent), this gives **+$90,632 after launch** and **+$123,939 for 2020–2025**, versus B0's +$169,969 and +$178,830. In 2026, the same hypothetical exposure gives **−$31,397**, versus B2's actual −$9,704 and B0's −$14,167. The larger 2026 loss is consistent with B2's smaller market exposure protecting dollars, not better Sharpe or win rate. This algebraic diagnostic **violates the $1,000 nominal trigger-risk budget in 228 of 237 trades in 2026**; it is not a native backtest or a deployable alternative, and ignores nonlinear execution costs, margin and market impact.

B2 also has higher recorded cost per trade: about **$39.84** after launch versus **$15.00** for B0. Across the full history the values are $82.53 and $15.00. B2 has variable contract quantity and per-contract fees. The fee and slippage assumptions are illustrative, and the BID-only source has no ASK or spread data.

## Daily risk and Monte Carlo

Closed trade net P&L is assigned to its **UTC entry date**. The daily series includes every calendar day, including zero-P&L days. It is not native mark-to-market equity. Both B0 and B2 use the same UTC entry-date period boundaries for a consistent calendar comparison. The native B2 research retains its Chicago session-day metadata separately. The full-history proxy has max drawdown of **−$21,212 (−2.12%)** for B0 and **−$263,421 (−26.34%)** for B2 on the illustrative $1m account. The B2 drawdown is dominated by pre-launch counterfactual size. Post-launch drawdown is −$17,184 for B0 and −$16,271 for B2. The proxy's ending equity and drawdown depend on shard completeness and must not be read as a funded account simulation.

The moving-block bootstrap uses 5,000 paired resamples with circular blocks of 5 and 20 calendar days. It resamples B0 and B2 from the same sampled dates. It does not resample individual trades or assume normal returns.

For the post-launch period, the 5-day block run gives median terminal P&L of **$169,767 for B0** and **$103,494 for B2**. The 5th–95th percentile ranges are $113,254–$225,614 and $49,090–$158,626. B2's paired annualized Sharpe difference has median **−0.70** and 5th–95th percentile range **−1.03 to −0.39**. B2 Sharpe exceeds B0 in 0% of these resamples. The 20-day block result is similar; B2 Sharpe is higher in 0.02% of resamples.

For 2026, the 5-day block terminal P&L median is −$14,330 for B0 and −$9,809 for B2. B2's paired Sharpe difference has median −0.08, with a 5th–95th percentile range from −1.19 to +1.04. B2 Sharpe exceeds B0 in 44.9% of resamples. The interval is wide because 2026 has only 238 B0 and 237 B2 trades. Risk-unit bootstrap results and 20-day block sensitivity are in `monte_carlo.json`.

The bootstrap describes resampled paths from observed history. It does not forecast future regimes. The post-launch sample still contains reviewed historical results, and 2026 is observed stress evidence, not a holdout. A $5,000 drawdown threshold is exceeded in all post-launch resamples for both strategies. This threshold is descriptive only.


### Independent correction and source preservation

A prior draft of this analysis incorrectly used signed short quantities to compute exposure and a hypothetical 10-MNQ P&L. This reversed the signs of short-trade results. The draft inputs and initial report are preserved under `risk_comparison_20261012/superseded_signed_qty_bug/`. The corrected program uses absolute quantities, retains trade P&L signs, and verifies invariant per-trade R values when algebraically rescaled. The original B0/B2 native Engine ledgers, source data, promoted strategy, and already-reported primary Sharpe/Calmar/Monte Carlo statistics were not changed. The hypothetical counterfactual is a *diagnostic only* and not a strategy trial.

## Data checks and limits

- The script read all 14 current annual B0 and B2 `evaluation_trades.csv` ledgers. It checked the B0 count and P&L against the latest practical-yearly report and checked B2 against the independent Phase 2–4 review.
- The script checked B2 `r_multiple` against net P&L divided by saved nominal risk. It did not remove rows from the annual ledgers.
- The B2 independent review found annual GTC boundary leakage, six out-of-year entry fills, and one entry fill duplicated across adjacent shards. The total ledger counts therefore preserve the observed shard outputs and may contain repeated or boundary-contaminated events.
- The B2 costed path has 63 same-minute entry/stop ambiguities, one opposing-entry-order ambiguity, and 92 late scheduled exits. B0 has its own execution ambiguity. These historical path issues limit direct attribution.
- The source is a Dukascopy BID-only USATECH index CFD proxy, not NQ or MNQ futures. No result is a live readiness claim. No unseen holdout exists.

## Method and reproduction

I loaded these local methodology skills and applied their checks:

| Skill | Reason | Check applied |
|---|---|---|
| `ml4t-risk-metrics` | Compare risk-adjusted returns and drawdowns | Report Sharpe, Sortino, Calmar, drawdown, and risk-unit tails |
| `ml4t-tearsheet` | Compare full performance rather than one metric | Report win rate, profit factor, expectancy, costs, drawdown, and Sharpe |
| `ml4t-position-sizing` | Test whether B2 underuses its risk budget | Reconcile saved risk units and report quantity and budget use |
| `ml4t-stress-test` | Evaluate observed 2026 adverse period | Keep 2026 separate and label it historical stress, not a holdout |
| `ml4t-transaction-costs` | Separate gross sizing effect from cost burden | Report recorded fee and slippage burden; retain spread and impact limits |
| `ml4t-polars-patterns` | Group ledger P&L by calendar day | Use Polars for CSV loading and daily aggregation |

The installed `ml4t.backtest.analytics` signatures are recorded by the script environment: `sharpe_ratio(returns, risk_free_rate=0.0, annualize=True)`, `sortino_ratio(returns, risk_free_rate=0.0, annualize=True)`, `calmar_ratio(cagr_value, max_dd)`, and `max_drawdown(values)`. The library uses 252 days when annualization is enabled. This analysis calls its Sharpe and Sortino with `annualize=False` and multiplies by `sqrt(365.25)` to match the all-calendar-day grid. This equals the sample-mean/sample-standard-deviation formula. The library supplies maximum drawdown and Calmar.

Run the analysis with:

```bash
UV_CACHE_DIR=/tmp/uvcache .venv/bin/python run_log/one_bar_nq_stop_scaling_20261012/risk_comparison_20261012/analyze.py
.venv/bin/pytest tests/test_one_bar_nq_b0_b2_risk_20261012.py -q
```

The analysis outputs are in [`risk_comparison_20261012`](../../run_log/one_bar_nq_stop_scaling_20261012/risk_comparison_20261012/): `metrics.json`, `metrics.csv`, and `monte_carlo.json`. The focused test suite has four tests for constant-series handling, risk-unit accounting, bootstrap reproducibility, and correct signed-short exposure scaling.

## Decision

The observed dollar underperformance is **not mainly an unfilled $1,000 stop-risk budget**. B2 deployed close to its nominal risk budget. Lower MNQ contract exposure can reduce dollar P&L and the 2026 loss. After the MNQ launch date, B2 also has weaker win rate, profit factor, R expectancy, daily Sharpe, and Calmar than B0. The historical evidence therefore supports both lower point exposure and weaker risk-adjusted trade results, with the latter preventing a simple undersizing explanation.

This is an exploratory historical accounting result. It does not approve B2, B0, or any other strategy for live trading.
