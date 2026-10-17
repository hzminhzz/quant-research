# Funding-extreme reversal: one-rule crypto alternative-data MVP

**Study date:** 2026-10-11. **Status:** EXPLORATORY / NOT APPROVED. **Decision:** REJECT the fixed contrarian rule on this development sample. No prospective OOS evaluation.

## Hypothesis and fixed rule

After Binance USD-M perpetual funding settlements, extreme positive rates can reflect crowded longs and predict short-horizon price reversal. Extreme negative rates can reflect crowded shorts. At each BTCUSDT/ETHUSDT funding event, compute absolute funding-rate 90th percentile from the previous **90 recorded funding events**, excluding the current event. If the current absolute rate meets or exceeds the historical threshold, take the **opposite** position (short for positive, long for negative). Signal is available only after the funding event and the complete one-hour candle. Fill at the following hour's open, hold **four hours**, exit at the corresponding hour's open. Each instrument targets **0.4× account equity**, with at most two simultaneous positions. No ML, stop, optimization, feature sweep, or secondary rule.

**Development:** 2026-01-01 00:00 UTC to 2026-08-01 00:00 UTC, exclusive. Use funding data from 2025-10-01 for warmup. Both instruments are Binance USD-M USDT-settled perpetuals. Starting cash **$500**. The full 2026-08 onward TSMOM prospective holdout remains unopened.

**Execution:** installed `ml4t.backtest` Strategy + Engine, NEXT_BAR/OPEN, fractional positions, 4.5 bps taker commission and 1.5 bps assumed execution slippage **per fill** (12 bps round-trip); no additional spread charge because no bid/ask quotes in the 1h files. This cost is an exploratory estimate, not verified fill calibration. Check 8h funding cadence from source; expected next settlement is computed from current event plus documented 8h cadence, **not future actual events**. After simulation, independently reject any held trade overlapping an observed settlement. No accepted trade crosses settlement, so no funding cash flow is applied. Buy-and-hold baseline is price-only with fees/slippage and **excludes its nonzero funding**, so it is only a descriptive market reference, not a like-for-like funded perp strategy.

## Actual evidence

| Measure | BTC + ETH portfolio |
| --- | ---: |
| Funding settlements screened | 1,272 |
| Below fixed extreme threshold | 1,123 |
| Candidate events and closed positions | 149 |
| Entries/fills (entry + exit) | 298 |
| BTC trades (winners) | 81 (30) |
| ETH trades (winners) | 68 (24) |
| Gross portfolio return, no execution costs | -2.61% |
| Net portfolio return, with friction | **-9.33%** |
| Start → final net equity | $500 → **$453.33** |
| Daily-equity annualized Sharpe | -2.27 |
| Daily-equity maximum drawdown | **-11.65%** |
| Gross-to-equity peak (net run) | 0.819× |
| Rejected orders | 0 |
| No-trade cash benchmark | 0.00% |
| Equal-weight BTC/ETH long-only descriptive *price-only* benchmark | -14.22% |

Net BTC trade contribution: **-$18.57** (81 trades; 30 winners); ETH: **-$28.11** (68 trades; 24 winners). Combined closed-trade net PnL -$46.67. Library fee sum $25.59; modeled slippage value $8.53 in the net run, so execution friction dominates the change in returns; direct gross-vs-net portfolio returns differ because compounded capital and position sizing differ.

**Interpretation:** Loss before costs and worse loss after costs. One fixed retrospective development run does not support an executable contrarian extreme-funding edge. The 11.65% observed drawdown breaches the proposed 10% maximum-drawdown prop-firm constraint even before adding execution-model uncertainty. The 50/50 long-only price reference also lost money; its greater loss is not evidence that this strategy has alpha.

## Data identities and independent checks

- Hourly BTC input: `data/processed/crypto_tsmom_flow_inputs_20261008/btcusdt_1h.parquet`; SHA-256 `67528cbf7f936e41f34f08fa033b05cfb2800a9f21ee39e6048051dd577db8b7`.
- Hourly ETH input: `data/processed/crypto_tsmom_flow_inputs_20261008/ethusdt_1h.parquet`; SHA-256 `f0c4959e7ed53afeb12cfe93e3776aa3047cb39be2759187d6cd3df866dacab1`.
- BTC funding input: `data/processed/crypto_tsmom_flow_inputs_20261008_v4/btcusdt_funding.parquet`; SHA-256 `750fd743783bc0285cde779d9c1573e12bf31b3c2f5a53b97e782ebcb8585a1a`.
- ETH funding input: `data/processed/crypto_tsmom_flow_inputs_20261008_v4/ethusdt_funding.parquet`; SHA-256 `ee1864a96892c708b4ed6cb784b13373b22015335d77412fab48fce226231c23`.
- The local historical gate for these sources was previously recorded by `run_log/research_sessions/crypto_tsmom_flow_increment_20261008_v4/data_gate_report.json`. No 2026-08 or later data is used or read.
- Each symbol contributed **5,088** contiguous hourly development bars. A separate ledger comparison found **149/149 entry timestamps, exit timestamps and directions** matched to the source signal ledger; 149 closed positions, 298 fills and zero rejected orders. All modeled holds lasted exactly four hours at next-open prices. Gross exposure stayed under 1.0×.
- Focused tests: `tests/test_funding_extreme_reversal_mvp_20261011_v1.py`. No tests, execution artifacts, or results from unrelated sessions were overwritten.

## Reproduction and files

- New scope specification: `config/research_sessions/funding_extreme_reversal_mvp_20261011_v1.yaml`.
- Source/engine: `scripts/run_funding_extreme_reversal_mvp_20261011_v1.py`.
- All outcome artifacts: `run_log/funding_extreme_reversal_mvp_20261011_v1/trial_result.json`, `signal_ledger.parquet`, `transaction_ledger.csv`, `rejected_orders.csv`.
- For a clean checkout with no existing result directory, invoke `.venv/bin/python scripts/run_funding_extreme_reversal_mvp_20261011_v1.py` from the repository root. The importer writes only this study's versioned run directory. The existing completed result is immutable: the runner refuses to overwrite it. For another run, use a separate versioned script/session and log the rerun as a new trial.
- Initial scope was written before trial outcomes were inspected, but this lightweight MVP **did not create an immutable research-session CLI freeze before execution**. Therefore its classification remains historical exploratory; do not claim formal prospective preregistration.

## Limitations and next decision

The funding API does not carry a separately verified first-publication timestamp for each settled rate. The runner waits until the next complete hourly candle, but cannot prove the data vendor's exact historical dissemination latency. Fees and slippage are not reconstructed from L1 bid/ask or real fills. The engine processes next-bar orders and permits short positions, but has no direct perpetual-funding ledger; the eligibility constraint makes the model applicable only to trades that avoid settlement events. Sampling is limited to two large cap coins and seven months, with prior exploratory history. This is not independent out-of-sample evidence.

**Decision:** Do not tune the failed 90th-percentile funding rule on the same sample. Next independent MVP, if desired: one causal taker-flow imbalance feature (already present in the same source hourly bars) versus the no-flow baseline, with a frozen 4h horizon and the same cost-aware execution assumptions. Its results must be registered as a separate trial, not renamed as validation of this rejected funding strategy.

**Research skills consulted:** ml4t strategy-workflow, point-in-time, fetch-data, validate-data, polars-patterns, compute-features, evaluate-factor, information-coefficient, run-backtest, horizon-design, cost-model and transaction-costs. Primary verified invariants: chronological source bars; prior-only threshold; next-open execution; bounded leverage; no funding settlement during positions; continuous daily equity metrics; all outcomes retained.
