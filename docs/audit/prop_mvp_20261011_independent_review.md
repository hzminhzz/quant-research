# Prop Perpetual MVP — Seven-Phase Research Audit (2026-10-11)

**Scope:** A BTC/ETH hourly time-series momentum; B liquidation-exhaustion mechanism and independent OHLCV dislocation proxy; C NAS100/SPX500 NY cash-opening breakout reference. **Classification:** EXPLORATORY / NOT_APPROVED. No live trading. Research periods stop before 2026-08-01 to preserve previously protected later history. All measured history is retrospective.

## Executive decision
No positive executable alpha was demonstrated. All six tested instrument baselines lost money at exploratory friction assumptions, and all exhibited drawdowns incompatible with ordinary prop evaluation limits. This does not disprove every version of the broader structural mechanisms. It rejects or deprioritizes the **specific frozen MVP implementations** only.

| Track / instrument | Coverage | Trades (native) | Return after assumed execution costs, before funding | PF | Annualized daily-equity Sharpe | Max DD |
|---|---|---:|---:|---:|---:|---:|
| A BTCUSDT momentum | 2021-01-01 to 2026-07-31 | 4,916 | -96.36% | 0.804 | -1.927 | 97.12% |
| A ETHUSDT momentum | 2021-01-01 to 2026-07-31 | 4,719 | -96.57% | 0.890 | -1.385 | 97.83% |
| B BTCUSDT dislocation proxy | 2024-01-01 to 2025-05-31 | 2,536 | -89.95% | 0.175 | -17.341 | 89.99% |
| B ETHUSDT dislocation proxy | 2024-01-01 to 2025-05-31 | 1,555 | -70.10% | 0.384 | -8.202 | 70.53% |
| C NAS100 opening range | 2017-01-03 to 2026-07-31 | 2,376 | -58.63% | 0.839 | -0.876 | 59.51% |
| C SPX500 opening range | 2017-01-03 to 2026-07-31 | 2,371 | -58.33% | 0.782 | -1.145 | 58.83% |

Note: Metrics are from the locally persisted native ML4T backtest reports. The Sharpe statistics are recomputed from daily equity observations; do not substitute the engine's bar-level Sharpe.

## Phase audit
1. **Thesis/specification:** Separate task-specific YAMLs in `config/research_sessions/prop_mvp_20261011_{a,b,c}.yaml`. Fixed causal definitions before valid runs; earlier strategy-family trials had already exposed historical intervals. Full parent trial history remains incomplete.
2. **Data integrity:** `run_log/prop_mvp_20261011/preflight_data_quality.json`, `data_hashes.json`, and `frozen_manifest.json`. Binance-referenced BTC/ETH processed hourly files and 1m 2024-25 price files, and vendor index 5m/15m aliases. Precise original-source provenance and Vest/Propr venue mapping remain unverified. Binance funding histories exist but are not included in final cash.
3. **Feature/event study:** A sign of 24-hour return at a completed 1h bar; B prior-bar abnormal 1m downside move measured against past ATR; C completed NY 09:30-09:45 opening range and next bar breakout. B's real liquidation signal was NOT supported by any verified historical timestamped forced liquidation dataset; do not label the proxy a liquidation strategy.
4. **Native event-driven backtests:** `scripts/run_prop_mvp_20261011.py` uses `ml4t.backtest.Engine`, `Strategy`, `DataFeed`, and `NEXT_BAR`. Ledger and equity artifacts in subdirectories of `run_log/prop_mvp_20261011/`. Fees/slippage: A 4.5+1.5 bps per filled side, B 4.5+5.0 bps, C 2.0+3.0 bps; all assumed and not broker-validated. No perpetual funding, exchange-specific spread, impact, or exact prop liquidation implementation included.
5. **Chronological validation:** Existing historical periods previously examined; no honest fresh OOS validation. Later-than-July-2026 protected slices were not intentionally scored. Long samples do not turn retrospectively chosen hypotheses into clean OOS evidence.
6. **Robustness/refutation:** A contains zero-cost baseline, 2x cost and extra one-bar-delay, plus cash/buy-hold controls. B has cost and event proxy diagnostics. C includes cost and one-bar-delay variants. Refer to per-trial JSON and parquet ledger; no DSR/PBO with incomplete prior trial accounting.
7. **Independent audit:** Initial A implementation mistakenly adjusted target-percent every hour, producing ~48,000 fills per instrument. **That run was invalid.** Replaced with changes-only signal logic and regression-tested; old metrics moved under `a_momentum/failed_rebalance_bug/`. Corrected baseline now has 4,916 BTC and 4,719 ETH trades. Focused tests: 2 passed with existing third-party warnings. `git diff --check` passed at inspected HEAD `c095faa`; task-owned files uncommitted, unrelated work preserved.

## Cost attribution and refutation details
A's corrected **zero-cost** net-price strategy was already negative (BTC -30.24%, ETH -41.67%); assumed trading costs take the baseline to approximately -96%. Doubling costs further worsens performance. Raw trade-level PnL/costs are recorded in `run_log/prop_mvp_20261011/a_momentum/{BTCUSDT,ETHUSDT}/`; do not interpret cumulative after-cost account return as additive to a zero-cost account return because rebalancing and compounding paths differ.

For B, the 1m price-only event study is not mechanistic evidence of forced liquidations. The huge negative result and high turnover do not justify searching for a profitable parameter after the fact. For C, results are *index vendor-price proxy backtests*, not actual Propr/Vest perp returns. Only a separate mapped contract with venue costs could validate executable index economics.

## Decisions
- **A: REJECT this fixed 24h-sign fast momentum baseline** for further prop-firm development, not the entire time-series-momentum mechanism. More promising independent hypotheses require a new registered session with lower-turnover horizons and non-price conditioning, not posthoc tuning.
- **B: BLOCKED for the actual liquidation-exhaustion thesis** (no real liquidation data). **REJECT the separate tested OHLCV dislocation proxy** at these costs.
- **C: REJECT the fixed opening-range proxy baseline**; **BLOCKED for venue-specific prop execution** pending verified exact instrument mapping.
- **Portfolio/probability-of-challenge-pass: NOT EVALUATED**. No synchronized independently validated positive PnL streams and no fixed account-specific floating drawdown rules/costs.

## Reproduction/status
- `scripts/run_prop_mvp_20261011.py`
- `tests/test_prop_mvp_20261011.py`
- `run_log/prop_mvp_20261011/a_results.json`
- `run_log/prop_mvp_20261011/b_results.json`
- `run_log/prop_mvp_20261011/c_results.json`
- `run_log/prop_mvp_20261011/summary.json` **may be stale** relative to corrected A and subsequent reconciliation refresh; check its mtime/contents against trial-level files.
- No commit or push authorized. No live orders.
