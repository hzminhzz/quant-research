# Tokyo Fix Program3: OHLCV execution audit

**Decision: RESEARCH COMPLETE / EXPLORATORY / NOT_APPROVED.**

The post-fix Gotobi short does not remain robustly positive under the frozen conservative limit-fill bounds. At the assumed 1-pip roundtrip cost, the native market benchmark earns $212.27 on 468 signals. Eleven of twelve native limit bounds lose money. The +1-pip offset, 3-minute TTL, zero-buffer bound earns $18.99, or $0.041 per submitted signal. Its 0.5-pip-buffer version loses $64.59. Every limit bound loses money in Jan–Aug2026. This rejects the stated robustness criterion. No winner was selected.

## Evidence scope and source seal

**VERIFIED:** Seven immutable annual LSE USDJPY minute OHLCV snapshots and the inherited Tokyo bank calendar supply 2020 through August2026. UTC timestamps denote minute opens and are converted to Asia/Tokyo. No data at or after2026-09-01 JST were read. All sources have SHA256 identities in `source_manifest.json`. Earlier Program1/2 artifacts and unrelated dirty files remain preserved.

**INFERENCE:** A minute close becomes available one minute after its open timestamp. The simulation uses09:54 close as the reference available at09:55. It never uses09:55 close to submit the order. The first permitted fill is09:56.

**UNKNOWN:** Prices are vendor composites. Volume is not verified executed FX volume. The local inventory has no USDJPY tick, paired bid/ask or depth data. Legacy8,507 BID candle files are not executable quotes. Broker contract, commissions, spread, lot constraints, queue position, latency, actual passive-fill probability, capacity and dealer inventory remain unknown. The notional is fixed USD10,000, with USD10,000 initial equity and no compounding. This is a research price proxy for an unspecified retail FX contract.

All studied years were already observed. 2020–23 is development, 2024–25 is retrospective validation, and Jan–Aug2026 is observed regime stress. September–October2026 remains sealed. No period is relabeled unseen OOS.

## Completeness and execution contract

**VERIFIED:** The09:54–10:30 contiguous minute gate retains 1625 bank dates: 468 Gotobi and 1157 ordinary. The gate requires each timestamp and valid finite OHLC geometry. `window_gates.parquet` and `T0_quality/result.json` retain missingness by year, weekday and Gotobi. Proxy and placebo windows use their own completeness gates. No fill is forward-filled. Five-minute staleness and zero volume are reported; unchanged composite closes alone do not establish an unavailable quote.

Native `ml4t.backtest.Engine`0.1.7 matches LIMIT orders on inclusive touches. Native fixed slippage can violate the sell limit price. The supported `PositiveVolumeLimit` execution gate therefore receives synthetic0/1 eligibility volume; raw OHLC remains unchanged. The gate permits a sell fill only when high strictly exceeds limit plus buffer within the frozen TTL. This gate is a hypothetical execution bound, not signal information or measured fill probability. The native engine owns fills, positions, cancellation and account cash. No second backtest loop exists.

The sell limit equals09:54 close plus0/0.5/1pip. Native price is the exact limit; favorable gap improvement is not assumed. TTL1 allows09:56; TTL3 allows09:56–09:58. Cancellation occurs after the last permitted matching cycle. Filled shorts close through a native MARKET submission at10:09 and fill at10:10 open. Missed signals have no invented trade and no closing order. There is no overnight or post-exit exposure.

The native ledger is JPY. Each closed JPY profit is divided by its actual raw exit USDJPY price. Assumed all-in costs0.8/1.0/1.4/2.0pips are separate quote-currency cash-flow overlays, not changes to native limit prices. Market and passive scenarios have separate illustrative entry/exit budgets but equal total costs. There is no maker rebate or zero-spread assumption. Actual costs are unverified.

## Native results at1-pip roundtrip cost

| Arm | Signals | Touches | Fills | Missed/cancelled | Net USD | USD/signal | USD/fill | Win rate | PF | Daily Sharpe | Close DD% | Minute-close MTM DD% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| market_gotobi | 468 | 468 | 468 | 0 | 212.27 | 0.454 | 0.454 | 51.7% | 1.218 | 0.591 | -0.885 | -0.921 |
| market_ordinary | 1157 | 1157 | 1157 | 0 | -464.27 | -0.401 | -0.401 | 44.5% | 0.839 | -0.827 | -4.980 | -5.036 |
| limit_o0_t1_b0 | 468 | 267 | 259 | 209 | -100.30 | -0.214 | -0.387 | 45.6% | 0.846 | -0.370 | -1.514 | -1.646 |
| limit_o0_t1_b0p5 | 468 | 267 | 220 | 248 | -174.11 | -0.372 | -0.791 | 41.8% | 0.718 | -0.675 | -2.055 | -2.187 |
| limit_o0_t3_b0 | 468 | 307 | 300 | 168 | -31.30 | -0.067 | -0.104 | 46.3% | 0.955 | -0.105 | -1.188 | -1.234 |
| limit_o0_t3_b0p5 | 468 | 307 | 268 | 200 | -121.01 | -0.259 | -0.452 | 44.0% | 0.823 | -0.431 | -1.732 | -1.857 |
| limit_o0p5_t1_b0 | 468 | 226 | 220 | 248 | -91.88 | -0.196 | -0.418 | 45.0% | 0.839 | -0.357 | -1.466 | -1.593 |
| limit_o0p5_t1_b0p5 | 468 | 226 | 188 | 280 | -114.55 | -0.245 | -0.609 | 44.7% | 0.777 | -0.472 | -1.553 | -1.680 |
| limit_o0p5_t3_b0 | 468 | 273 | 268 | 200 | -19.53 | -0.042 | -0.073 | 48.1% | 0.969 | -0.068 | -1.117 | -1.180 |
| limit_o0p5_t3_b0p5 | 468 | 273 | 237 | 231 | -69.90 | -0.149 | -0.295 | 46.8% | 0.883 | -0.259 | -1.360 | -1.420 |
| limit_o1_t1_b0 | 468 | 198 | 188 | 280 | -44.77 | -0.096 | -0.238 | 47.9% | 0.906 | -0.184 | -1.059 | -1.181 |
| limit_o1_t1_b0p5 | 468 | 198 | 156 | 312 | -84.44 | -0.180 | -0.541 | 43.6% | 0.814 | -0.357 | -1.194 | -1.308 |
| limit_o1_t3_b0 | 468 | 244 | 237 | 231 | 18.99 | 0.041 | 0.080 | 49.8% | 1.034 | 0.073 | -0.858 | -0.929 |
| limit_o1_t3_b0p5 | 468 | 244 | 199 | 269 | -64.59 | -0.138 | -0.325 | 45.2% | 0.878 | -0.252 | -1.194 | -1.251 |

All missed limit orders terminate through cancellation; native expired count is0. Sharpe uses daily USD portfolio equity changes on the full Tokyo bank calendar, including flat days, with252 periods/year. `EquityCurve` and `TradeAnalyzer` calculate performance metrics. Closed-trade drawdown differs from the native-fill-based minute-close MTM reconstruction. MTM reserves the full assumed cost on entry and excludes unobserved tick/intrabar extrema and actual broker margin.

| Arm | Net USD at0.8pip | 1.0pip | 1.4pip | 2.0pip |
|---|---:|---:|---:|---:|
| market_gotobi | 283.47 | 212.27 | 69.87 | -143.73 |
| market_ordinary | -288.03 | -464.27 | -816.74 | -1345.46 |
| limit_o0_t1_b0 | -60.86 | -100.30 | -179.17 | -297.47 |
| limit_o0_t1_b0p5 | -141.22 | -174.11 | -239.89 | -338.56 |
| limit_o0_t3_b0 | 14.78 | -31.30 | -123.47 | -261.73 |
| limit_o0_t3_b0p5 | -80.42 | -121.01 | -202.19 | -323.97 |
| limit_o0p5_t1_b0 | -58.99 | -91.88 | -157.66 | -256.33 |
| limit_o0p5_t1_b0p5 | -86.64 | -114.55 | -170.38 | -254.13 |
| limit_o0p5_t3_b0 | 21.06 | -19.53 | -100.71 | -222.49 |
| limit_o0p5_t3_b0p5 | -34.34 | -69.90 | -141.01 | -247.68 |
| limit_o1_t1_b0 | -16.86 | -44.77 | -100.60 | -184.34 |
| limit_o1_t1_b0p5 | -61.55 | -84.44 | -130.22 | -198.89 |
| limit_o1_t3_b0 | 54.55 | 18.99 | -52.12 | -158.79 |
| limit_o1_t3_b0p5 | -35.17 | -64.59 | -123.43 | -211.68 |

Full annual metrics, per-fill/per-signal expectations, negative-day counts, win rates, Sharpe, profit factor, and drawdown for all56 cost scenarios are in `all_cost_fill_metrics.csv` and each corrected run result. The following table shows selected reference arms; it does not select a strategy.

| Year | Market Gotobi USD | Ordinary USD | +1pip/TTL3/buffer0 USD | +1pip/TTL3/buffer0.5 USD |
|---|---:|---:|---:|---:|
| 2020 | -50.55 | -136.01 | -36.27 | -38.59 |
| 2021 | 11.43 | -74.74 | -10.41 | -21.43 |
| 2022 | 65.01 | 186.31 | 15.81 | -4.08 |
| 2023 | 67.55 | -59.95 | 6.78 | 2.12 |
| 2024 | 81.13 | -112.32 | 54.19 | 57.77 |
| 2025 | 85.19 | -157.86 | 17.80 | -27.40 |
| 2026 Jan–Aug | -47.49 | -109.69 | -28.92 | -32.98 |

## Price proxies, controls and adverse selection

**HYPOTHESIS:** Settlement demand and subsequent inventory unwind can explain a reversal, but price extensions, realized volatility, acceleration and range do not observe that mechanism. The five past-only proxies use completed bars. Development-only terciles stay fixed. Event-level correlation, native `Evaluator` annual expanding folds, categorical controls and HAC/month-cluster intervals are saved. `analyze_signal` requires cross-sectional prices; the single-asset event study instead uses the library event correlation and `Evaluator` APIs.

**VERIFIED:** None of the20 weekday/year-controlled proxy contrasts passes Holm. Secondary categorical/interaction estimates are descriptive. `secondary_diagnostics.json` contains controlled categorical HAC estimates and per-signal/per-fill cost expectancy intervals. No price proxy filters trades.

The market Gotobi-minus-ordinary increment is1.420pips, HAC95%CI[0.397,2.442], raw p0.00652 and Holm14 p0.0652. The matched09:26–09:40 nonfix placebo contrast has466 Gotobi pairs: fix-minus-placebo short return2.704pips, CI[1.625,3.782], Holm14 p0.0000164. This single frozen placebo result is retrospective and cannot prove settlement causality or correct prior searches.

All twelve limit policies have lower per-signal expectation than the market policy. Three differences pass the new14-contrast Holm correction. Raw1/3-minute and exit markouts, market outcomes conditional on filled/missed days, and matched policy contrasts are in `T2_comparison_corrected/result.json`. These records expose missed favorable market trades and adverse excursions. The fill bound uses crossing and time only, never the subsequent exit outcome.

Earlier native Program1v2 used458 Gotobi/1,143ordinary trades and a broader08:29–10:10 gate. Its after-cost results were+$217.14/−$450.95. Those frozen artifacts remain intact. The new cohort and raw-exit cost-overlay conversion differ, so this is not an exact same-cohort reproduction.

## Independent audit and retained failures

**VERIFIED:** `T3_oracle/result.json` independently rescans original snapshots and checks every submitted signal, earliest strict crossing, exact limit price, TTL, no same-bar fill, missed cancellation, scheduled exit, quote-PnL reconciliation and USD conversion. The oracle uses decimal arithmetic independently of the production Polars gate.

The first full14-run implementation admitted some exact decimal touches because of binary floating-point arithmetic. Independent verification rejected six limit runs. All initial run artifacts, initial comparison and ledger entries remain in `runs/`, `analysis_complete.json` and `T2_comparison/`; they are superseded as evidence. The corrected full14-run replay is under `runs_corrected/`, `analysis_corrected.json` and `T2_comparison_corrected/`. Comparison rounds to8decimal places solely to remove observed floating dust below3e-14JPY; source prices are unchanged. This is a strict-cross implementation repair, not a new parameter ladder.

Execution accounting includes28 complete native run artifacts, including14 corrective replays. One additional market Engine run returned in attempt3 before artifact finalization failed;29 economic Engine runs returned in total. Engineering probes and unit-test engines are separate from these economic runs. Three earlier runtime failures were retained: UTC/JST literal mismatch, required feature volume omitted, and touch-count join missing the session key. Logs, code identities, correction dispositions and every initial/corrected result hash are in `execution_accounting.json`. The immutable CLI terminal records show that the original trials executed; completion alone did not validate their fills. Final audit points to corrected evidence and preserves rejected originals.

Focused regressions passed51 tests with3 third-party SHAP deprecation warnings. The final Program3 suite passed all20 tests. Eight native semantics probes also passed. Exact logs and checks are in `T4_final_audit/result.json`. The full304-item repository suite was attempted and interrupted after it stalled near47%; a full-suite pass is not claimed. The first `uv` attempt could not write its user cache; the retry used a task-specific writable cache and the installed environment. No notebook was changed.

## Limits and next decisive input

**INFERENCE:** Conservative crossing and missed-fill sensitivity erode the apparent historical market edge. The model does not establish an executable passive strategy. The frozen robustness falsifier fails, and deployment remains NOT_APPROVED.

**UNKNOWN:** Real order-book queues and adverse broker selection cannot be estimated from these bars. Obtain timestamp-verified executable bid/ask and actual passive order outcomes on genuinely future data, then preregister another test. Do not open the sealed holdout for optimization. Prior historical trial history is incomplete; DSR/PBO and any full-search confidence adjustment remain unreproducible.

## Artifacts and reproduction

- Frozen spec: `config/research_sessions/tokyo_fix_program3_ohlcv_execution_20261011_v1.yaml`.
- Runner: `scripts/run_tokyo_fix_program3_ohlcv_execution_20261011_v1.py`; modes `prepare`, `run`, `run_corrected`. Existing immutable outputs block changes; resumption verifies identical data.
- Independent oracle: `scripts/verify_tokyo_fix_program3_ohlcv_execution_20261011_v1.py`.
- Supplement/report: `scripts/supplement_tokyo_fix_program3_ohlcv_execution_20261011_v1.py`.
- Authoritative executions: `runs_corrected/*/orders.parquet`, `trades.parquet`, `signals.parquet`, `result.json`.
- Charts: [price proxy map](../../run_log/tokyo_fix_program3_ohlcv_execution_20261011_v1/price_proxy_map.png), [corrected cost/fill sensitivity](../../run_log/tokyo_fix_program3_ohlcv_execution_20261011_v1/fill_cost_sensitivity_corrected.png).
- Source/window evidence: `source_manifest.json`, `window_gates.parquet`, `T0_quality/result.json`.
- Independent audit: `T3_oracle/result.json`; final preservation/ledger/verification: `T4_final_audit/result.json`.

No real orders, commits, pushes, old frozen artifact changes or holdout analysis occurred.
