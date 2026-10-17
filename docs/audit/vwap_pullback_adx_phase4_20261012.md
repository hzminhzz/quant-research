# VWAP Pullback + ADX — Phase 4 native ML4T backtest and independent audit

Date: 2026-10-12. Repo: `/home/quant/dev/quant/quant-research`.
Session: `vwap_pullback_adx_nq_20261012_proxy_v2`.
Status: **PHASE4 PROXY ENGINE EXPERIMENT COMPLETED; CME EXECUTION NOT QUALIFIED; ADX INCREMENT INCONCLUSIVE**.
This is not paper-trading approval or a real CME futures fill claim.

## Scope and data

- Period: development only, Jan 1 to Jun 30, 2026, America/Chicago; 122 complete XNYS cash sessions after excluding March 6 source gap.
- Input: `data/processed/vwap_adx_nqf_2026h1_1m.parquet` SHA256 `a0670b34b2175ca0df4a7ab98fa79bb02650cf4cce64ed67261ad29f706ebaad`.
- Source: LSE provider-defined continuous `NQ.F`. No dated CME contract chain, confirmed roll semantics, true exchange volume or bid/ask feed; VWAP is source-volume weighted.
- Frozen original session and v2 `frozen_spec.json` were not edited.
- `ml4t.engineer.compute_features` generates Wilder ADX(14); session VWAP is causal cumulative typical-price-by-reported-volume from 08:30 CT.
- 1 contract; **NQ-equivalent** illustration: USD $20 per point, 0.25 point tick, initial account $1,000,000. The latter makes percentage drawdowns small; these values do not describe the margin/risk profile of an actual small futures account.

## Native implementation

`scripts/run_vwap_pullback_adx_phase4_20261012.py` SHA256 `475f30121ab9c78888699a5af95913c63b8aa169bdbcedc76a00063e33b4cb76`.

The strategy subclasses `ml4t.backtest.Strategy`. Orders, fills, ledger, portfolio and metrics come from `ml4t.backtest.Engine(DataFeed, strategy, BacktestConfig, contract_specs=...)`; no custom trade simulation loop was used.

B0: no trade (zero PnL). B1: OR breakout only. B2: OR -> later VWAP touch -> reclaim. B3: B2 with ADX>20 non-increasing, including delayed waiting. All use:
- Exact 30-minute OR 08:30-08:59 CT, no entry before 09:00.
- Signal on completed minute t, market entry at minute t+1 open.
- Fixed TP = highest high of 5 completed minutes immediately preceding entry bar; fixed SL = lowest low of 20 completed minutes immediately preceding entry bar, rounded to 0.25.
- Native resting stop-market and limit; native EXIT_FIRST processing with protective stop submitted before target. Opposing sibling is cancelled when position closes. One position maximum; reentry requires a fresh Gate 1 after exit. No numeric daily cap.
- 15:54 CT completed-bar callback submits flatten market, filled at 15:55 CT open; no overnight carry.
- **OCO is not atomic** in this installed engine. The observed dataset did not trigger a reversal and a stop-first outcome was seen in the one B1 exit minute that touched both barriers; this does not prove broker-live OCO safety.

Nine native variants were run without parameter selection:

| Variant | Trades | Win rate | Net USD | Net expectancy USD/trade | Daily Sharpe | Daily max DD | Daily Calmar |
|---|---:|---:|---:|---:|---:|---:|---:|
| B1 gross | 320 | 84.38% | +6,825 | +21.33 | 1.066 | 0.723% | 1.957 |
| B1 illustrative costs | 320 | 77.81% | +2,025 | +6.33 | 0.323 | 0.867% | 0.483 |
| B1 higher slippage | 320 | 71.88% | -1,175 | -3.67 | -0.178 | 1.062% | -0.228 |
| B2 gross | 115 | 52.17% | +8,275 | +71.96 | 1.841 | 0.500% | 3.434 |
| B2 illustrative costs | 115 | 48.70% | +6,550 | +56.96 | 1.469 | 0.509% | 2.667 |
| B2 higher slippage | 115 | 46.96% | +5,400 | +46.96 | 1.217 | 0.518% | 2.161 |
| B3 gross | 77 | 77.92% | +5,165 | +67.08 | 1.120 | 0.706% | 1.515 |
| B3 illustrative costs | 77 | 68.83% | +4,010 | +52.08 | 0.876 | 0.718% | 1.156 |
| B3 higher slippage | 77 | 62.34% | +3,240 | +42.08 | 0.712 | 0.729% | 0.919 |

**Assumed costs, not broker-verified:** USD $2.50 per contract per side; fixed adverse slippage of one 0.25-point NQ tick per side (= USD $5 per side). The higher-stress trial uses two ticks per side. B2 base drag relative to gross is USD $1,725: $575 stated commissions plus $1,150 engine slippage. B3 base drag is USD $1,155: $385 fees and $770 slippage. B1 base drag is USD $4,800. Fee/cost breakdowns are from the native engine ledger.

Native engine `gross_pnl` may already use slippage-adjusted fill prices. Therefore, **gross/no-cost trial vs net/cost trial** is the correct gross-to-net attribution, not subtracting slippage a second time from a slippage-adjusted gross field.

## Hypothesis: does ADX improve VWAP reclaim?

- B3 compared with B2 increases the **win rate by 20.1 percentage points**, but reduces number of fills (115 -> 77), total net PnL by **$2,540**, net expectancy per trade by **$4.88**, daily Sharpe by **0.59**, and Calmar by **1.51**.
- Bootstrap (10,000 resamples of the 122 session-paired daily B3 minus B2 net PnL): observed -$20.82/day, 95% interval approximately **[-$114.39, +$67.54]/day**. Increment is **statistically inconclusive**, not proven negative out of sample. The test is exploratory and does not replace chronological validation.
- Phase 3 tested first event/day gross forward price changes. This Phase 4 uses **uncapped daily native entries plus actual TP/SL and time exit**. The samples and inference are different.
- Do not optimize the ADX period/threshold after seeing the result and still call 2026 July-October unseen OOS.

## Independent mechanical verification

Evidence: `run_log/vwap_pullback_adx_nq_20261012_proxy_v2/phase4/independent_audit_v2.json`.
Source: `scripts/audit_vwap_pullback_adx_phase4_20261012.py` SHA256 `88ca43abc74882dd791f484d82f3122164f847b88125c40abec4ef349183a68c`.

Across all **nine trials**:
- Entries equal the next minute of the signal; independent 5/20-bar high/low calculations match registered levels; source open + configured adverse slippage matches entry fill.
- One entry and one exit fill per closed trade. Alternating buy/sell and zero unintended reversals.
- All exits by/before 15:55 CT; no position left overnight. All native account net PnL reconciles to native closed-trade ledger to floating point tolerance.
- B3 cost exits: 17 stops, 60 target limits, zero time exits. B2 cost exits: 53 stops, 60 target limits, two time exits.
- B3: **34 of 77 trades exit within the entry minute** (high bar-path sensitivity despite no same-bar dual barrier hits in this sample). B2: 43 of 115 such exits. B1: 177 of 320.
- Same exit-minute both-barrier touch: B1 once, stop-first. B2 and B3 zero.

**Execution fidelity limitation requiring remediation before claiming live-like futures prices**:
1. Native fixed slippage is charged to resting take-profit **sell limit** executions, yielding fill price *below the specified minimum limit*. All 60 B2 cost target fills and all 60 B3 cost target fills have this defect. This is conservative accounting but not a literally legal limit execution; a model with valid price-floor semantics and separate costs is required.
2. No atomic OCO broker guarantee. Next-bar native engine FIFO/stop-first ordering is only verified for these observed bars.
3. LSE continuous proxy has unverified dated CME rolls, volume, spread, queue-position and order execution quality. Gap and touch fills rely on OHLC.

The mechanical audit is **PASS_MECHANICAL**. The exact CME execution qualification remains **BLOCKED**.

## Artifacts, trials, gate

- Machine-readable nine-trial summary: `run_log/vwap_pullback_adx_nq_20261012_proxy_v2/phase4/all_trials.json`.
- Each `phase4/B1_gross` through `B3_stress` contains native `trades.parquet`, `fills.parquet`, `equity.parquet`, `daily_equity.parquet`, `signals.json`, `transitions.json`, `metrics.json`.
- Mechanical independent audit version 2: `phase4/independent_audit_v2.json`; version 1 remains retained. A first audit classified some stop-gap events by bar-close reference instead of source open; v2 corrected that diagnostic without changing trades.
- Tests: `uv run python -m pytest -o addopts='' tests/test_vwap_pullback_adx_phase4_20261012.py tests/test_vwap_pullback_adx_phase3_20261012.py -q`.
- Script executions and trial metadata remain in files; zero parameter tuning after seeing outcomes.
- This phase may be recorded as completed **exploratory research** in v2 append-only trial record; completed does not mean `APPROVED`.

**Decision:** The profitable price-proxy results for B2/B3 motivate further test, but the original assertion that ADX adds value is **INCONCLUSIVE**. B2 is the stronger development candidate. No adopt/live signal, no OOS test performed. Next research question: repair limit-fill validity and atomic OCO semantics, then validate on a declared separate chronological sample without selecting from that sample.
