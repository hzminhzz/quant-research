# Independent Phase 5-7 verification — One-bar Dukascopy Nasdaq proxy

**As-of 2026-10-11.** Independent ChatGPT verification from current VPS trade, fill, metric, and report files. This is a separate review from Codex's own Phase 7 audit and is not a strategy-approval record.

## Verified artifacts and numerical identity

Source: Dukascopy USATECH.IDX/USD BID proxy; Jan 2013–2026-07-14; 163 Parquet partitions, 3,883,929 source minutes, 11,744 incomplete 30m bins excluded. This is **not** dated CME NQ futures or proven executable CFD economics. Both new runs use installed native ml4t.backtest Engine, one NQ-equivalent $20/pt contract, 50 completed prior bars, 30-minute bar next opening-print exit, $1000 protective-stop trigger, and max 2 entries/Chicago day; no filters or parameter tuning.

| Phase 6 trial | Closed trades | Native-ledger net PnL | Avg net/trade | Daily-equity Sharpe | Equity DD |
| --- | ---: | ---: | ---: | ---: | ---: |
| Causal zero-cost | 5,373 | +$246,787.88 | +$45.932 | 1.8924 | 1.1905% |
| Causal full tick + $2.50/fill | 5,373 | +$166,664.42 | +$31.019 | 1.2606 | 2.0285% |

**Confirmed:** Native trade PnL sums equal the difference of the final equity and $1,000,000 initial capital within 2e-8 USD in each run. Both have 10,746 fills and maximum 2 entries per Chicago session. Causal removal of precomputed future 'entry_valid' gate changes trade count versus earlier retrospective baseline (5,150), so earlier result was NOT a point-in-time signal-only backtest. Full-tick friction: $2.50/fill * 10,746 = $26,865 commissions and 0.25 pt/fill * $20/pt * 10,746 = $53,730 modeled slippage, total $80,595. This is NOT broker-verified. The 2026 subset is negative.

## Phase 5 retrospective chronology under causal full-tick assumptions

| Period | Trades | Net PnL | Average/trade |
| --- | ---: | ---: | ---: |
| 2013-2017 | 1,757 | -$18,459.70 | -$10.51 |
| 2018-2020 | 1,247 | +$22,826.90 | +$18.31 |
| 2021-2023 | 1,308 | +$106,383.42 | +$81.33 |
| 2024-2025 | 823 | +$71,587.92 | +$86.98 |
| 2026-Jul14 | 238 | -$15,674.12 | -$65.86 |

This is a **retrospective** regime profile, not a protected OOS pass; manager selection history is unknown. No August 2026 onward data should be read for this session.

## Independent stop / next-boundary reconciliation

Read causal_full_tick/trades.csv and fills.csv using Polars and align every pair of native fills to its closed trade in order. All 5,373 exit fill timestamps matched ledger exit timestamps. Classify by exit fill order type and whether the market exit equals the immediately following UTC half-hour boundary of the entry.

| Category | Trades | Net PnL |
| --- | ---: | ---: |
| Correct next-boundary MARKET exits | 4,948 | +$378,016.08 |
| MARKET exits **later than required** | 216 | +$5,308.50 |
| Early protective STOP exits | 209 | -$216,660.16 |

The 216 late-market exits violate the exact next-bar-opening rule, and some are many hours or even days late after missing source bars. Their aggregate realized PnL contributes only +$5,308.50. The remaining ledger trades total +$161,355.92, a **post-hoc attribution only**, not a causal resimulation: excluding a trade can alter subsequent eligibility. The native full-tick runner also flagged 43 cases where within-one-minute stop/entry sequencing is unresolved. Stop-market orders can incur >$1000 realized losses on gaps; modeled $1000 is a trigger distance, not a guaranteed maximum.

## Independent audit exceptions

1. **Do NOT interpret all calculated source-quality 'missing-next-minute' count as real.** The phase runner's 'decisions_without_immediate_next_minute_data' is calculated using shift(-1) AFTER selecting one row per 30-minute bar-boundary decision. The next selected row is normally 30 minutes later, so that count (121,269) is a diagnostic bug. Compare boundary rows against the unfiltered source-minute event stream instead. This metric does not itself feed the strategy but must be fixed before final data-quality acceptance.
2. **Do NOT interpret reported cost_reconciliation_difference_usd = -$53,730 as missing debits.** In the engine's trade CSV, gross_pnl is already after execution slippage and before commissions. Thus gross_pnl minus net trade pnl is $26,865 in commissions, NOT all $80,595 total friction. The simulation charged $53,730 as adverse execution prices and $26,865 commissions; native equity and trade ledger reconcile. Rename the metric or compute pre-slippage notional movement separately; do not double count slippage.
3. All observed history is retrospective. Actual quotes are BID-only index CFD proxy and do not validate ask spreads, tradeable NQ futures prices, session access, settlement, or contract rolls. A no-tuning 50-bar rule can still exhibit regime dependence, especially after 2020. Margin and account size are illustrative.
4. The one-bar exit invariant fails in 216 market exits. Need a causal fail-closed execution policy for missing next opening print, then a native re-run if an exact-rule result is desired. A posthoc ledger exclusion does NOT establish correct execution.
5. A trial/multiple testing count for the manager's prior development cannot be reconstructed; DSR/PBO unavailable, not a pass. No protected Aug2026+ holdout has been authorized.

## Decision

**Evidence supports further forward validation / INCONCLUSIVE for exact-rule CME feasibility; NOT_APPROVED for live trading.** Strong positive history survives a native full-tick cost replay but depends heavily on 2021-2025, while early and 2026 periods are negative. Correct the two diagnostic reporting issues and test the missing-next-open fail-closed semantics before upgrading the research status. Native ledgers and predeclared trial matrix are retained at run_log/one_bar_dukascopy_phase567_20261011/.
