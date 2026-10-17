# One-bar NQ stop scaling: independent Phase 2–4 review

Status: **INCONCLUSIVE; EXPLORATORY; NOT APPROVED FOR LIVE.** All 14 year shards ran for both registered B2 cost cases. Independent audit found material accounting and annual-boundary limits. Do not use the annual cash-risk figures as clean independent-year evidence.

## Scope and preserved evidence

- Frozen question: compare the unchanged promoted B0 breakout with one preregistered B2 rule using a 1.5 × causal ATR20 stop and integer MNQ sizing. No B1 or B3 variant ran. Phases 5–7 were not authorized.
- Protected package: `promote/one_bar_nq_30m` was not changed. Frozen archive SHA-256: `4553cf1647e9652fc9bb4f2621597648632c0a20678aae1c359b456ffc9de181`.
- Data: 163 frozen one-minute partitions; manifest SHA-256 `fd810bef0a390a77972d22d1cb0100e6d17f46dec437bed5abf865f39e579e75`; 3,883,929 in-scope rows through 2026-07-14 UTC; no post-cutoff rows. Source is Dukascopy USATECH.IDX/USD BID-only CFD/index proxy, not dated futures.
- Skills loaded: `ml4t-run-backtest`, `ml4t-cost-model`, and `ml4t-point-in-time`. The runner uses the installed native `ml4t.backtest.Engine`; source, causal feature release, integer sizing, and per-fill cost invariants were checked against saved artifacts. The selected skill names, paths, reasons, invariants, and independent checks are recorded in `independent_skill_checks.json`. The repository-required skill selection is also recorded in the frozen spec.

## Latest B0 control and Phase 3 correction

The first Phase 3 run used an older B0 ledger with 5,150 trades. I preserved that study under `superseded_phase3_legacy_5150/`. The current study uses all 14 promoted cost-aware `evaluation_trades.csv` files. It has 5,462 unique closed trades and $166,107.92 net P&L. This is the latest B0 baseline.

The corrected Phase 3 join has ATR20 for all 5,462 entries. Median ATR20 is 20.1474 points. Native B0 STOP exits are counted from `fills.csv` order type, not the generic `exit_reason`: 211. The fixed B0 path diagnostic found 316 path touches at the B2 stop distance. The result is conditional on B0 entry/exit paths; it is not a B2 replay.

CME launched MNQ on May 6, 2019 ([CME launch notice](https://www.cmegroup.com/media-room/press-releases/2019/5/06/cme_group_announceslaunchofnewmicroe-miniequityindexfutures.html)). MNQ is $2 per index point with a 0.25-point ($0.50) tick ([CME contract specifications](https://www.cmegroup.com/markets/equities/nasdaq/micro-e-mini-nasdaq-100.html)). Therefore 2013–May 5, 2019 is only a counterfactual fractional NQ proxy. May 6, 2019 onward still uses a BID CFD series, not dated CME MNQ prices.

## B2 annual native results

The costed rule used $1.25 commission per MNQ contract per fill and 0.25 point adverse slippage per side. The zero-cost path used no commission or slippage. Annual accounts reset to $1,000,000. Stop exit counts use native exit fill order types.

| Year | Costed closed trades | Costed net P&L ($) | Costed PF | Worst daily equity change ($)* | Native STOP exits | Zero-cost net P&L ($) |
|---:|---:|---:|---:|---:|---:|---:|
| 2013 | 319 | -63,197.63 | 0.359 | -2,542.50 | 25/319 (7.84%) | 6,959.39 |
| 2014 | 394 | -62,667.85 | 0.384 | -2,325.00 | 30/394 (7.61%) | 7,116.75 |
| 2015 | 388 | -31,177.19 | 0.600 | -2,381.26 | 19/388 (4.90%) | 14,684.31 |
| 2016 | 369 | -49,966.06 | 0.474 | -14,884.52 | 19/369 (5.15%) | -3,756.03 |
| 2017 | 341 | -47,900.00 | 0.377 | -2,371.02 | 13/341 (3.81%) | 171.80 |
| 2018 | 424 | 9,644.80 | 1.150 | -1,879.36 | 14/424 (3.30%) | 42,970.30 |
| 2019 | 405 | -406.08 | 0.995 | -4,705.21 | 25/405 (6.17%) | 39,633.96 |
| 2020 | 436 | 2,492.75 | 1.040 | -2,214.19 | 16/436 (3.67%) | 19,995.75 |
| 2021 | 444 | 22,546.43 | 1.341 | -2,083.50 | 21/444 (4.73%) | 42,233.93 |
| 2022 | 438 | 35,728.80 | 1.585 | -2,189.02 | 28/438 (6.39%) | 47,730.13 |
| 2023 | 433 | 12,153.45 | 1.161 | -2,316.67 | 31/433 (7.16%) | 30,976.45 |
| 2024 | 415 | 14,693.67 | 1.207 | -3,744.00 | 32/415 (7.71%) | 29,191.17 |
| 2025 | 416 | 25,084.26 | 1.390 | -8,810.57 | 17/416 (4.09%) | 36,161.26 |
| 2026 | 237 | -9,704.29 | 0.765 | -1,848.00 | 23/237 (9.70%) | -5,591.29 |

*The saved daily equity paths include fills outside some shard session-years. Six distinct entry fills fall in a later session-year than their shard. One entry fill is duplicated across adjacent shards. The Engine’s native `submit_order` API has no expiry field for the pending STOP orders. The annual cash-risk series is therefore contaminated. The table preserves the observed shard outputs; it does not present them as clean independent-year estimates.*

Across the 14 reported shard ledgers, costed B2 has 5,459 closed trades and −$142,674.93 net P&L. Zero-cost B2 has +$308,477.89. Costed fees total $321,815.00; modeled slippage totals $128,726.00. The costed-minus-zero-cost P&L change is −$451,152.82, which differs from those direct costs by $611.82 because the two native paths diverge. No fee-only reconciliation is claimed.

The latest B0 result is +$166,107.92 over 5,462 trades. B0 uses one illustrative NQ contract ($20/point). B2 uses uncapped variable integer MNQ proxy size ($2/point each). Dollar P&L is not exposure matched. Costed B2 quantity median/max is 28/133 MNQ before the listing date and 4/71 on or after it; 2026 is 4/13. That is 2.8/13.3 and 0.4/7.1 NQ-equivalent contracts, respectively. No dynamic-multiplier stress was run because it would be another trial.

## Independent accounting findings

- All closed native trades map to exactly one entry fill and one exit fill by timestamp, side, and quantity; the independent check found zero date mismatches. Daily final equity, trade P&L, commission totals, and the two-entry-per-session-day cap reconcile. The latest native accounting audit passes these identities.
- Planned quantity follows `floor(1000 / (2 × tick-rounded stop points))` on the saved trade records. However, outward tick rounding from an actual fill price that is off the 0.25-point grid caused actual stop-trigger risk to exceed $1,000 on 137 trades. Maximum observed actual trigger risk was $1,036.45. The fixed-risk claim therefore does not hold at the actual rounded protective stop.
- Gap losses can exceed the nominal budget. Costed trades include 226 net losses below −$1,000; the worst was −$14,768.53. Zero-cost had 24 such losses; the worst was −$14,646.03.
- Costed execution has 63 same-minute entry/stop ambiguities and one opposing-entry-order ambiguity. Zero-cost has 62 and one. The source does not resolve order sequence within the minute. Ninety-two scheduled market exits were late, with a maximum delay of 2,976 minutes.
- Actual native STOP exit rate in 2026 was 23/237 (9.70%). This compares with the original B0 count of 44 STOP exits among 238 trades, but the contracts, sizing, and source interpretation differ.
- The source is BID-only, so ASK and spread are absent. Commission, slippage, margin, and fills are illustrative, not broker-verified. No unseen holdout exists; 2026 is observed stress data.

## Repairs and checks

I repaired the Phase 3 baseline source, preserved the superseded 5,150-trade study, linked B2 signal metadata to native entry order IDs to fix immediate entry/stop attribution, and blocked warmup trading. The 2024 risk-attribution failure and replaced annual shards are preserved under each year’s `attempts/` directory. The audit records the remaining GTC boundary leakage instead of treating it as resolved.

The focused suite passed: `uv run pytest tests/test_one_bar_nq_b2_20261012.py -q` (10 passed). The repository-wide pytest run was not completed. The parallel run reached 94% and displayed two failures without a traceback before I stopped it. The serial rerun did not return a result, so I stopped it. The last three validation test files passed separately (30 passed). `git diff --check` passed for the task-owned source, test, and audit files. No trade, commit, or push occurred.

## Decision and next question

The result remains inconclusive. The costed proxy outcome is negative, the stop-risk limit fails for 137 trades after actual tick rounding, same-minute event ordering remains unresolved, and annual shards are not isolated after data gaps. No B2 deployment or instrument-validation claim follows from these results.

Next decisive question: can this frozen B2 rule be replayed with native order expiry and dated, two-sided CME MNQ data so annual boundaries and actual stop risk are valid? That requires a separately approved execution/data contract. Do not add a contract cap or multiplier stress without a new authorized trial.
