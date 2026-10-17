# One-bar NQ — fixed-percentage protective stop (12 October 2026)

**Status:** Completed exploratory ML4T native-engine comparison. Original promoted B0 is **unchanged**. Not approved for live trading. All data through 14 July 2026 was already observed. No ATR, volatility adjustment, volume adjustment, MNQ sizing or new filter was introduced.

## The exact implementation

B0 uses a fixed 50-index-point protective stop on one illustrative NQ contract at $20/point. Since that stop is not a single constant percentage across the entire historical sample, the experiment uses the explicitly discussed **2021 reference**:

- Verified median 2021 B0 costed entry price: **14,598.25** (444 B0 trades).
- Constant stop percentage: **50 / 14,598.25 = 0.34250680732279554%**.
- On a **real native entry fill**, place a protective stop at `entry_fill_price * (1 - fraction)` for longs or `entry_fill_price * (1 + fraction)` for shorts, rounding **away** from entry on the 0.25-point tick grid. The stop is never recalculated.
- Keep **one NQ-equivalent contract** at $20/point and B0 commission/slippage assumptions ($2.50 per fill and 0.25 point adverse slippage per fill). Preserve original 50 completed 30-minute bar breakout and next-30-minute-opening exit, both directions, intended OCO, and two entries per Chicago session day.
- At the observed 2026 median entry level of 25,828.5, the stop is approximately **88.5 points / $1,770 nominal risk**, excluding gap losses, instead of 50 points / $1,000.
- This anchor was chosen using 2021 data. **2013–2021 are ex-post calibration/counterfactual**, not causally selectable from inception. 2022–2026 was already inspected and is not unseen out-of-sample.

## Cost-aware native backtest results

| Period | B0 net USD | Fixed-% net USD | Change USD | B0 win | Fixed-% win |
|---|---:|---:|---:|---:|---:|
| 2013–2021 (ex-post) | +42,414.00 | +45,045.90 | +2,631.90 | 45.69% | 45.34% |
| 2022–2025 | +137,860.88 | +140,578.76 | +2,717.88 | 52.26% | 52.52% |
| **2026 Jan–Jul14** | **−14,166.96** | **−18,743.00** | **−4,576.04** | 47.48% | 50.21% |
| **2022–2026** | **+123,693.92** | **+121,835.76** | **−1,858.16** | 51.67% | 52.24% |
| 2013–2026 all observed | +166,107.92 | +166,881.66 | +773.74 | 47.82% | 47.79% |

The 2026 fixed-% trial has **237 closed trades** vs B0's 238, **21 protective-stop exits** vs 44, and profit factor **0.771** vs B0's **0.806**. It made a higher fraction of winning trades but losses on unsuccessful trades were larger; the total net P&L and profit factor deteriorated. The difference between total counts is a legitimate simulated order-path difference, not a matched-trade comparison.

## Risk-adjusted results

These are independent *daily realized cash-flow proxies*, built by grouping each native **closed trade** P&L on its UTC **entry date**, including all UTC calendar dates (zero-P&L days), using 365.25-day annualization, 0% risk-free rate and a hypothetical starting $1,000,000. They are **not** a continuous native mark-to-market futures equity curve and should not be interpreted as a prop-account capital simulation.

| Period | B0 Sharpe | Fixed-% Sharpe | B0 Calmar | Fixed-% Calmar | B0 max realized DD | Fixed-% max realized DD |
|---|---:|---:|---:|---:|---:|---:|
| 2022–2025 | 2.389 | **2.437** | 2.148 | **2.209** | −$17,184 | **−$17,074** |
| 2026 Jan–Jul14 | **−1.825** | −2.053 | −1.590 | −1.524 | **−$16,608** | −$22,925 |
| **2022–2026** | **1.885** | 1.815 | **1.706** | 1.281 | **−$17,184** | −$22,925 |
| 2013–2026 all observed | **1.281** | 1.272 | **0.538** | 0.471 | **−$21,212** | −$24,373 |

For negative-CAGR 2026, Calmar values are not a useful ranking by themselves; compare the absolute drawdowns and Sharpe. For 2022–2026 the wider stop **reduces** overall historical risk-adjusted performance, despite a modest advantage in 2022–2025.

## Decision

**Do not replace the promoted B0 with this percentage-stop variant yet.** The exact user-requested rule has been implemented and fully tested, but it does **not** cure the observed 2026 underperformance. The widening is sufficient to reduce the number of stop exits, not to improve expectancy or protect the drawdown in 2026. No further optimization or alternative stop mechanism was executed.

## Data quality, uncertainty and verification

- Source: Dukascopy **BID-only** USATECH.IDX/USD CFD/index price proxy, **not CME dated NQ**.
- The entry and stop fill sequence is modeled with 1-minute OHLC; intraminute event order and native non-atomic OCO remain uncertain. The native broker executes adverse gaps, and price-only stops cannot guarantee a maximum $ loss.
- Annual ML4T runs restart the Engine with warmup, rather than maintaining a single continuous margin/equity state; native daily-equity files are not treated as a seamless account curve.
- All **14 annual years** completed both native zero-cost and cost-aware trials (28 scenario runs); native reconciliation status **passed**, no stop or daily-cap invariant errors.
- Independent verification: **5,613 entry contexts** across the cost-aware annual runs exactly match the stop formula with tick rounding, long and short. Original source and promoted package unchanged: package checksum verifier passed.
- **6 focused synthetic tests passed**, including native stop-market adverse gap behavior.
- The initial final-report invocation failed due to an import path error *after all annual simulations completed*; it was corrected in the report-only script. A subsequent resumable top-level invocation skipped all durable completed years, completed its audit and exited **0**. The immutable yearly *strategy* script hash matches its frozen-spec identity. The earlier failure log was retained.
- A pre-existing B0 `recovery_agent.log` hash-index mismatch existed before the run and was unchanged; it does not affect the trade/fill ledgers. No Git commit/push or live order occurred.

## Reproduce and inspect

- Independent frozen spec: `run_log/one_bar_nq_percent_stop_20261012/frozen_spec.json`
- Source integrity and attempts: `run_log/one_bar_nq_percent_stop_20261012/source_quality.json`, `trial_ledger.json`, `validation/native_reconciliation.json`
- Full native result: `run_log/one_bar_nq_percent_stop_20261012/final_report.json`
- Daily realized proxy comparison: `run_log/one_bar_nq_percent_stop_20261012/comparison_realized_daily.json`
- Yearly native trades/fills/metrics: `run_log/one_bar_nq_percent_stop_20261012/by_year/YYYY/percent_costed/` (and `percent_zero_cost/`)
- Source implementation: `scripts/run_one_bar_nq_percent_stop_yearly_20261012.py`; runner and report: `scripts/run_one_bar_nq_percent_stop_20261012.py`, `scripts/report_one_bar_nq_percent_stop_20261012.py`.
- Config: `config/research_sessions/one_bar_nq_percent_stop_20261012.yaml`; tests: `tests/test_one_bar_nq_percent_stop_20261012.py`.

Re-run focused tests with `uv run --no-sync python -m pytest -q tests/test_one_bar_nq_percent_stop_20261012.py` and regenerate the daily comparison with `uv run --no-sync python scripts/report_one_bar_nq_percent_stop_20261012.py`. Do not modify the original `promote/one_bar_nq_30m/` to store these experimental changes.
