# Four-strategy allocation — development decision (2026-10-14)

**Outcome: EXPLORATORY DEVELOPMENT COMPLETE / PRIMARY ML4T LINEAR THESIS REJECTED / NOT_APPROVED.**

No allocator performance from 2025–2026 was evaluated. That retrospective period remains reserved for a future, explicitly approved single test. It was previously examined during underlying strategy selection and is not an independent strategy-level final holdout.

## Reconciled observed development panel

The four frozen promoted strategy streams were represented as independently marked synthetic capital accounts:
- B0 NQ-index CFD: one continuous native `ml4t-backtest.Engine` account and exact 23:59 UTC marked equity.
- C3 US500/US100 CFD: continuous native Engine account with cross-year position carry and an equity minute mark at exactly 23:59 UTC.
- Donchian BTCUSDT perpetual: native marked equity plus signed funding as a fixed-fill, development-only overlay. Historical exact Binance funding marks are supplemented by explicitly labeled mark-candle or perpetual-close proxies.
- RSI 30/50 ES CFD proxy: unchanged native marked equity, where `00:00` UTC is a daily session label derived from NY 17:00 session aggregation, not midnight valuation.

The BTC native session-label accounting was corrected before allocation training. Its 2024 final equity was **268,581.66 USDT** after all 2019–2024 funding charges available by the completed session. This supersedes the earlier 268,587.50 USDT figure that used the label as an instant 00:00 snapshot.

All four native return paths are relative to their **own** original capital and position-sizing conventions. We compare dimensionless capital returns, not raw USD PnL. The CFD accounts are synthetic USD-like price-unit accounts; BTC uses USDT, approximated at USD parity only for exploratory portfolio learning.

Data inspection established:
- First/last eligible months: 2019-09 / 2024-12.
- Four-way common session-date intersection: 1,373; strict valid clock-common session dates: 1,102.
- 64 valid **observed** monthly portfolio marks and 63 intervals, no missing months.
- The final valid common session in a month can precede that month's literal last calendar date. The next month accounts for all observed NAV change since the previous mark, including intervening BTC weekend exposure.
- No forward-fill of source returns, invented zero trading PnL, or conversion of absent marks to zero.

Reproduction artifacts: `run_log/allocation_prerequisites_20261014/allocation_development/monthly_observed_panel.csv` and `calendar_and_provenance.json`.

## Preregistered trial

Preregistered BEFORE model-fit in `docs/audit/multi_strategy_allocation_prereg_20261014.md`.

- Exactly 1 learned configuration: installed `ml4t-models==0.1.4` `LinearFeaturePortfolioModel`, `ridge_alpha=1e-4`, `seed=42`, `gross_exposure=net_exposure=1`, `max_abs_weight=0.4`.
- Information available at each decision: prior 1-month and 3-month strategy returns; 21 and 63 common-observed-session volatility; 63-session drawdown.
- Target: next month's strategy-account return, with labels that are fully known at training time. The earliest 2022 evaluation prediction was fitted to 24 completed labels; the final one to 59.
- 2019–2021: expanding initial fit; 2022-01 through 2024-12: 36 chronological walk-forward months.
- Same 10 bps per one-way capital transfer friction on all non-cash comparators, with 2x and 3x scenario stress. Native fees and funding remain included in source return streams.
- Models compete against zero-yield cash, monthly rebalanced 25% equal weight, and 63-observed-session inverse-volatility weights with matching 40% cap. A long-only 4-strategy portfolio fully deploys its capital; there is no defensive cash option inside the learned allocator.
- Model fit and prediction use the installed `PortfolioSequenceBatch` and `PortfolioAllocationPipeline`; no PyTorch and no strategy rerun.
- Portfolio performance was scored using `ml4t.diagnostic.api.PortfolioAnalysis(periods_per_year=12)`; independent Sharpe checks use installed `ml4t.backtest.analytics.metrics.sharpe_ratio` with monthly annualization adjustment.

### Primary development results (2022–2024, 1× allocation friction)

| Strategy capital allocation | Cumulative net | Annual return | Net Sharpe | Maximum DD | Mean monthly one-way turnover |
|---|---:|---:|---:|---:|---:|
| Cash | 0.00% | 0.00% | undefined | 0.00% | 0.00% |
| Equal 25% each | +24.95% | 7.71% | **0.969** | **−5.09%** | 3.92% |
| Inverse-volatility | +8.94% | 2.90% | 1.787 | −1.02% | 5.73% |
| ML4T linear | +25.10% | 7.75% | **0.941** | **−5.49%** | 4.82% |

**Primary preregistered falsifier FAILED**: The learned allocator needed at least +0.15 net Sharpe improvement and no drawdown deterioration relative to equal weight. Actual net Sharpe difference: **−0.0281**; max DD also worsened by 0.40 percentage points. Its additional 0.15 percentage-point cumulative return does not meet the risk-adjusted objective.

Paired 3-month circular block bootstrap on 36 monthly results, 5,000 fixed-seed draws: 95% interval for learned-minus-equal Sharpe difference **[−0.0805, +0.0169]**, which does not support positive improvement.

### Turnover-cost sensitivity (net cumulative development return)

| Arm | 1× base cost | 2× | 3× |
|---|---:|---:|---:|
| Equal weight | +24.95% | +24.77% | +24.60% |
| Inverse-volatility | +8.94% | +8.72% | +8.49% |
| ML4T linear | +25.10% | +24.89% | +24.67% |

The learned allocator's average weight was roughly 24.6% B0, 24.5% C3, 26.4% BTC, and 24.5% RSI. It stayed close to equal weight while incurring somewhat more rebalance turnover. The inverse-vol baseline achieved higher raw Sharpe through lower realized risk, not higher cumulative return. No risk-normalized new arm was tested; doing so would constitute another registered comparison.

## Acceptance and restrictions

**Verified:**
- Four valid development-monthly source streams, provenance and source hashes.
- Full chronology, features and next-month labels have separated train/prediction indices.
- Model returned feasible long-only weights, each ≤40%.
- First capital deployment correctly charged a full unit transfer from cash; subsequent transfers charged half the risky-weight L1 change.
- Separate 1× / 2× / 3× allocation cost accounting.
- Complete 36-month development ledger; exactly one learned configuration.
- Tests passed with the existing research prerequisite suites; no promotion status was changed.

**Known limitations:** This experiment models strategy-capital ownership of net synthetic native accounts, not the real operational transfers or trade fills of CFD and crypto bots. Monthly weights were assumed effective at observed portfolio marks without a separate broker execution delay model. USD/USDT parity, CFD financing, BID-only proxy costs, BTC funding mark proxies, B0 stop/OCO ambiguity, strategy-level selection history, and C3 financing remain limitations. These results cannot support deployment or live approval.

**Decision:** Reject the linear allocator as an improvement over equal weight in the frozen development comparison. Do not inspect the reserved 2025–2026 allocator test to choose another model. A NEW separately preregistered study may test a risk-budgeting or regime-dependent policy, with explicit new trial accounting and a revised genuinely future confirmation boundary.

## Paths

- Preregistration: `docs/audit/multi_strategy_allocation_prereg_20261014.md`
- Source panel: `run_log/allocation_prerequisites_20261014/allocation_development/monthly_observed_panel.csv`
- Clock/source hashes: `run_log/allocation_prerequisites_20261014/allocation_development/calendar_and_provenance.json`
- Monthly predictions and comparator outcomes: `run_log/allocation_prerequisites_20261014/allocation_development/allocation_stage_dev_monthly_trials.csv`
- Summary: `run_log/allocation_prerequisites_20261014/allocation_development/allocation_stage_dev_report.json`
- Final trial record and bootstrap: `run_log/allocation_prerequisites_20261014/allocation_development/trial_ledger_allocation_dev_20261014.json`
- Code: `scripts/allocation_btc_session_alignment_20261014.py`, `scripts/allocation_monthly_panel_20261014.py`, `scripts/allocation_linear_development_20261014.py`, `scripts/allocation_dev_summary_review_20261014.py`
- Tests: `tests/test_allocation_development_20261014.py`

No Git commits or pushes were made; unrelated dirty changes were preserved.
