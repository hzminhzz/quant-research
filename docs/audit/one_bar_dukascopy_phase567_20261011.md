# One-bar Dukascopy phases 5–7 audit — 2026-10-11

**Decision: INCONCLUSIVE.** The causal native-engine ledger is positive at the tested cost, but execution semantics and the source proxy do not support a robust strategy claim. This is exploratory evidence. It does not approve live trading or CME NQ futures.

## Scope and frozen rules

The experiment uses the Dukascopy `usatechidxusd` / `USATECH.IDX-USD` BID index CFD proxy, from 2013-01-02 through 2026-07-14. It is not CME futures data. No data after 2026-07-14 was read. The prior corrected baseline completed before this work. Its zero-cost and quarter-tick ledgers each contain 5,150 trades and 10,300 fills. Their net PnL is $246,425.90 and $207,805.90. Both reconcile to terminal equity within $0.00000002. The old wrapper wrote exit code `1` despite a completed report and native `ENGINE_DONE` markers; its cause is unknown.

The rule remains 30-minute extended-session bars, rolling levels from the previous 50 complete bars, native stop entries, $1,000 protective loss trigger, next 30-minute boundary market exit, and at most two entries per Chicago session date. The future `entry_valid` gate was removed. A decision can now occur without looking at later bars. Missing exit boundary data is recorded and the order exits at the next observed event if one exists.

Frozen references and trial declarations are in `run_log/one_bar_dukascopy_phase567_20261011/frozen_trial_matrix.json`. New simulations use ML4T `Engine` 0.1.7. The final run command is `UV_CACHE_DIR=/tmp/uv-cache-onebar uv run --no-sync python scripts/run_one_bar_dukascopy_phase567_20261011.py`. Phase 5 uses fixed chronological blocks; all direction, session, and range-tercile splits are descriptive and post hoc.

## Phase 5: chronological results

| Period | Trades | Full-tick net PnL | Daily equity Sharpe | Max drawdown |
|---|---:|---:|---:|---:|
| 2013–2017 | 1,757 | -$18,459.70 | -1.18 | -1.92% |
| 2018–2020 | 1,247 | $22,826.90 | 0.89 | -1.41% |
| 2021–2023 | 1,308 | $106,383.42 | 2.94 | -0.57% |
| 2024–2025 | 822 | $71,445.08 | 2.22 | -1.16% |
| 2026-01 through 2026-07-14 | 238 | -$15,674.12 | -1.86 | -1.53% |

The historical scaling is material: average entry index level rises from about 4,358 in 2013–2017 to 20,817 in 2024–2025. Normalize PnL and execution assumptions before comparing raw dollars across eras. The full-tick top ten trades contribute 23.6% of trade PnL; the top ten Chicago session dates contribute 26.3%. The worst trade is -$4,283.06 and worst session date is -$4,199.58.

Full-tick PnL is $90,671.64 short and $75,849.94 long. The Chicago RTH proxy bucket contributes $65,686.74 across 2,127 trades; overnight/weekend contributes $100,834.84 across 3,245. These are post-hoc descriptions, not tested filters. Range terciles were formed using the full observed sample and are also post hoc. No confidence intervals were computed because no session-cluster bootstrap was available. No DSR or PBO claim is made because the complete historical trial set is unavailable.

## Phase 6: causal and cost falsification

| Trial | Trades | Net PnL | Daily Sharpe | Max drawdown |
|---|---:|---:|---:|---:|
| Causal, zero cost | 5,372 | $246,630.04 | 1.89 | -1.19% |
| Causal, $2.50 commission and 0.25 adverse points per fill | 5,372 | $166,521.58 | 1.26 | -2.03% |

At full tick, 10,744 fills incur $26,860 commission and $53,720 slippage. The recorded ledger matches these assumptions. The strategy still shows positive PnL in this replay, but this is not an execution-robust result:

- 3,335 entry stop triggers have a summed $409,132.58 difference between reference open and stop-price fill. This is a favorable trigger-price fill effect, not a separately validated execution benefit.
- 105 protective stops cross their trigger in a gap. Stop-price fills omit $19,993.80 of additional gap loss.
- A simple additive sensitivity subtracting those two price effects from full-tick PnL is about -$262,604.80. It is not a re-simulation; changed stop paths and positions are not modeled.
- 5,929 scheduled boundary decisions lack the immediate next-minute row. 216 recorded exits differ from the expected boundary, excluding protective exits. The feed contains 3,883,929 minute rows, 121,319 complete 30-minute bars, and 11,744 incomplete bars excluded from signal construction.
- 43 same-minute entry/protective-stop OHLC ambiguities occur in the zero-cost run (44 in the cost run). The adverse diagnostic replaces each ambiguous trade with a -$1,000 outcome plus full-tick costs; T4’s bound PnL is $117,030.64. Minute OHLC cannot establish event order.

The trial ledger did not run 2x/3x full-tick stress, delayed-fill stress, or a placebo. These remain untested. The additive gap sensitivity is only a bound diagnostic, not a native Engine trial.

## Phase 7: independent execution and ledger audit

The independent timing audit and six native synthetic tests identified a hard OCO failure. The broker can fill both opposite stop orders in the same minute before strategy cancellation. It happened once, at 2024-06-07 12:30 UTC. The extra order fill is visible as an exit/flattening fill; therefore the trade ledger has 5,372 trades while the strategy recorded 5,373 entry-order fills. Ordinary entries obey the two-per-session cap, with no session over the cap. The strict OCO invariant fails, so the run does not fully implement the frozen OCO rule.

Other synthetic cases passed: UTC half-hour boundaries remain distinct through the fall-back hour; native cost application is correct; entry-minute protective-stop ambiguity is flagged; a missing scheduled exit fills at the first observed event; and no exit is fabricated beyond the final feed event. ML4T `sharpe_ratio` and `max_drawdown` independently reproduce both daily-equity metrics. Trade PnL reconciles to terminal equity within $0.00000002 for both runs.

The initial causal replay attempts exposed incorrect cap accounting and duplicate OCO diagnostics. They are retained under the two `superseded_*` folders with their failure records. The final replay fixes diagnostic counting; it cannot remove the native broker’s same-minute OCO race. Test command: `UV_CACHE_DIR=/tmp/uv-cache uv run --no-sync python -m pytest -q tests/test_one_bar_dukascopy_phase567_20261011.py` — 6 passed. The OCO test passes by asserting the observed failure and records the required invariant as `FAIL`.

## Evidence and limitations

Source manifest SHA-256 is `fd810bef0a390a77972d22d1cb0100e6d17f46dec437bed5abf865f39e579e75` (163 partitions). Full metrics, fills, trades, daily equity, source-quality counts, trial matrix, skill record, synthetic tests, hashes, and chart are under `run_log/one_bar_dukascopy_phase567_20261011/`. The independent review is `docs/audit/one_bar_dukascopy_phase567_20261011_independent.md`.

The run log contains `ENGINE_DONE` for both native trials and final metrics. The attached process exit code was not retained. `runtime_status.json` records this limitation; tmux was unavailable because the sandbox denied its sockets. Historical data after July 14 remains protected. There is no genuine holdout in the evaluated period, no verified CME contract mapping or roll model, no quote/ask-side execution data, and no market-impact model. Treat all Sharpe and PnL values as descriptive research outputs only.
