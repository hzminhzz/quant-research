# Mechanical Premia H1 breakout — forensic source, features and PnL audit (2026-10-13)

**Scope:** READ-ONLY forensic audit of already-observed 2013–2024 development runs in
`mechanicalpremia-original-four-2013-2024-v1`. No new H1 outcome trial,
no parameter tuning, no 2025+ market observations, no live orders.
**Source MQL5:** https://mechanicalpremia.substack.com/p/building-a-multi-strategy-portfolio
(retrieved with TinyFish `fetch_content` 2026-10-13).
**Audit code:** `scripts/audit_mechanicalpremia_h1_feature_parity_20261013.py`
and `tests/test_mechanicalpremia_h1_feature_parity_20261013.py`.

## Conclusion

The source **entry indicator rule is implemented correctly at the intended
H1 OHLC numerical level**; but source-to-broker **execution parity is NOT
established**. It is incorrect to declare the original MQL5 strategy economically
unprofitable from the synthetic multi-index native run.

The 2013–2024 H1 negative net PnL is **primarily explained within this native
cost model by high turnover + assumed transaction costs**, with DE30 contributing
most of the negative net synthetic PnL. The signal has positive pre-cost
synthetic PnL, but this is not certified tradable edge.

## Original MQL5 vs native implementation

| Rule | MQL5 source | Current native code | Verdict |
|--|--|--|--|
| Assets | US500, US100, DE30 | Same | MATCH |
| ATR | `iATR(PERIOD_H1,14)`, previous completed bar | registered `atr`, period=14, last completed H1 | MATCH numeric indicator |
| ATR median | copy last 100 completed ATRs, sort, `Atr_Sorted[50]` | rolling quantile 0.5, interpolation=higher | MATCH intended rank |
| Bands | `iBands(PERIOD_H1,40,0,2,PRICE_CLOSE)` upper buffer 1 | registered `bollinger_bands` width 2, upper struct field | MATCH mathematical indicator |
| Entry | last H1 Close > last H1 Upper AND ATR < sorted median | same causal last H1 signal | MATCH intended signal |
| Fill | market BUY at live ASK after new H1 trigger | next-bar native fill from BID OHLC proxy + synthetic slippage | NOT MATCH |
| Initial stop | buy order transmitted with initial attached 2×ATR SL | separate stop only after fill observed in next callback | NOT MATCH: entry-minute gap |
| Manager | live BID sampled every ~60s, update SL to BID−2×last closed ATR with point-distance constraint | previous H1 ATR + available 1m close, update outstanding native STOP | APPROX, NOT PARITY |
| Size/margin | MT5 tick size/value, lot size/step, account balance + broker margin | synthetic fractional units, marked equity, gross cap, risk budget distributed across 3 H1 assets | NOT MATCH |
| Exits | broker stop at set price/gap, tick-level | native STOP fill from OHLC only | UNVERIFIED intra-minute/gap sequencing |
| Sessions | MT5 broker H1 series and chart timer | UTC H1 complete-60-minute aggregation | UNVERIFIED broker calendar and incomplete-bar rules |

**Original source inconsistency**: MQL5 input defaults set `H1_BB_Risk_Perc = 1.0` and `D1_PctB_Risk_Perc = 1.0` per trade; article's portfolio discussion proposes **0.2336% H1** and **0.7664% D1** per trade. Native research uses fixed article-level weights divided across sleeve instruments, plus an exposure cap. Thus native H1 sizing is a portfolio adaptation, not a literal default-input MQL5 reproduction.

## Feature discovery and independent numerical parity (verified)

`feature_catalog.list()` and `feature_catalog.describe()` discover built-in
`atr`, `bollinger_bands`, `ema`; `compute_features(...)` executes
registered features. Existing code used these before, but had not recorded
this formal discovery and an independent numerical source-compatibility proof.

On canonical US500 2023 H1 bars:
- 5,619 complete hourly samples.
- ATR14 versus independent TA-Lib ATR14: max absolute difference `1.07e-14` across 5,605 valid comparisons.
- BB40 upper versus TA-Lib BBANDS40(2): max absolute difference `5.00e-11` across 5,580 valid comparisons.
- MQL5 sorted-100 upper median oracle: 123/123 H1 signals identical, 0 disagreements over 5,506 eligible bars.
- New deterministic synthetic-data tests independently verify ATR/BB calculation,
  sorted-100 upper-middle and prefix/append invariance; original native
  regression tests remain. **10 tests passed**.
- These checks certify consistency with TA-Lib + intended source formula
  **on our constructed H1 bars**, NOT exact equivalence with MT5 broker bars,
  tick events, stop behavior or final PnL.

## Why the synthetic H1 net is negative

Summing 1,741 CLOSED native H1 trades over 12 independently reset years
(2013–2024). All figures are synthetic price-unit account deltas; EUR DAX
is not FX-converted and should **not** be labeled real USD dollars.

| Source ledger bridge | Synthetic PnL across 12 resets |
|--|--:|
| Before assumed direct cost (reconstructed as gross+slippage) | +54,028.84 |
| Less recorded native slippage | -39,491.55 |
| Native gross PnL after slippage, before commission | +14,537.29 |
| Less commission | -19,745.77 |
| **Native net PnL** | **-5,208.48** |

Trade-count-weighted net expectancy: -2.99 synthetic units/trade.
Win rate: 34.92%; the source trailing-stop strategy can have a low win rate,
so win rate alone does not prove the edge absent.

By asset after native costs:
- US100_H: 589 trades, net **+9,676.50**.
- US500_H: 584 trades, net **-3,077.04**.
- DE30_H: 568 trades, net **-11,807.95**.

The direct-cost assumption is 1 bp commission + 2 bps slippage **per side**,
about 6 bps round trip before real bid/ASK spread, broker financing, FX.
Gross profitable does **not** establish tradable alpha. Costs are hypothetical.

2013 QA: 19 of 61 US500 H1 BUY fills and 14 of 51 US100 H1 BUY
fills landed on minute bars with recorded `volume=0`. That is **33/112
US index entries (~29.5%) with reported zero quote-volume**; it does NOT
prove they were untradable, but undermines unqualified fill assertions.
The input acceptance archive contains many short/stale days.

## Execution-ledger checks

All 1,741 H1 closing fills were native `order_type=stop`, and all entries
were native market buys. The journal's `price_source=open` denotes the
reference quote source; the actual stop base uses the native `check_stop_fill`
and can fill at stop or adverse gap. Do not misdiagnose `reference_price`
being above/below stop as a fill-contract violation. Native `stop_price`
and fill prices are visible. Pending-stop and entry-minute lifecycle parity
with MT5 remain unproved.

## Decision

- **Verified:** H1 source indicator formula and registry usage at H1 OHLC,
  on the tested data, passed the independent TA-Lib proof.
- **Verified:** H1 synthetic net loss and cost contribution from native ledger.
- **Inference:** direct-cost drag and DE30 are major reasons the tested
  portfolio H1 result is negative.
- **Unknown:** whether the authentic MT5 bot is profitable or not over
  broker-specific 2013–2024 quotes/fills/fees. Our native proxy is not a
  faithful enough replication for that claim.

**Next task only as a separately registered correction/qualification trial:**
source-fidelity H1 stop attached at entry, broker time/H1 incomplete bars,
BID/ASK/lot/FX costs, source per-trade lot sizing and unchanged signals.
Hold the original source parameters fixed. Run a SOURCE-PARITY comparison
and only then evaluate native profitability and instrument decomposition.
Do not optimize H1 thresholds or discard DE30 because it was losing
in the already-observed data. Preserve all earlier results.
