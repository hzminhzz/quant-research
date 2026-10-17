# NQ one-bar breakout — stop-scaling research (draft)

**Status:** DRAFT · exploratory · no new backtests executed · not approved for live trading.

## Preserve the original

The existing `promote/one_bar_nq_30m/` package is **read-only for this project**. An external byte-for-byte archive was saved at `run_log/one_bar_nq_stop_scaling_20261012/frozen_baseline/one_bar_nq_30m_as_is_20261012.tar.gz` (SHA-256 `4553cf1647e9652fc9bb4f2621597648632c0a20678aae1c359b456ffc9de181`). The promoted source was uncommitted at the capture time; a tarball is not a Git commit. Snapshot metadata and file hashes are in `frozen_baseline/snapshot.json`.

The current control remains 50 completed 30-minute bars, long and short stop entries, intended opposing-order OCO, immediately-next-30-minute-opening market exit, maximum two entries per Chicago session day, and $1,000 nominal protective stop on one NQ-equivalent contract.

## Economic question

A fixed 50-point stop represents a smaller part of the market's price movement as Nasdaq's price and absolute intraday volatility increase. The median pre-entry 30-minute ATR20 was 27.9 points in the matched 2018–2025 comparison and 66.7 points in January–July 2026. The original stop fell from about 1.79 ATR units to 0.75 ATR units. The 2026 stop-out frequency reached 44/238 trades (18.5%). More stop-outs may impair the strategy without any loss of its 50-bar breakout/time-exit mechanism. However, wider stops can create larger losses, and a reduction in stop frequency is **not proof of higher expectancy**.

## Trial ladder (proposed, not run)

| Trial | Stop distance | Size | What it isolates |
|---|---|---|---|
| B0 | Fixed 50 points | 1 NQ-equivalent | Frozen original benchmark |
| B1 | 1.5 × causal ATR20(30m) | 1 NQ-equivalent | Stop distance alone; **dollar risk floats** |
| B2 | 1.5 × causal ATR20(30m) | MNQ, sized to $1,000 nominal stop risk | Primary volatility-aware fixed-risk candidate |
| B3 | 0.40% of prior completed 30-minute closing index level | MNQ, sized to $1,000 nominal stop risk | Simple price-level correction |

No entry/exit indicator or timing rule is added. B1 is **diagnostic only**: a wider stop on one NQ cannot respect the same $1,000 budget. B2 uses `floor($1000 / ($2 per MNQ point × tick-rounded stop distance))` micro contracts; skip only if a single MNQ breaches the nominal trigger-risk budget. At ATR20=66.7, 1.5 ATR is about 100.1 points, so tick rounding and integer contract sizing matter. Five MNQ are affordable at exactly 100 points; four may be required when the valid stop distance rounds above 100 points. Stop-market gaps can still lose more than the nominal $1,000.

B3's 0.40% is a round proposed comparator, **not** an empirically selected optimum. As further diagnostics, a broader emergency-only stop or ATR multipliers 1.0 and 2.0 could be registered in a subsequent trial, but they are not initial candidates.

## Research method and safeguards

1. Verify that all 44 recorded 2026 protective STOP exits correspond to the actual native stop orders and assess any entry-to-stop intraminute ambiguity. Never rely on the generic trade `exit_reason=signal` label.
2. Use only previous fully completed 30-minute bars for ATR20 and reference price. No future bar may enter the stop when the entry is placed.
3. Compare B0–B3 over the **already-seen** 2013–2025 retrospective and 2026 through July 14 stress period. This is **not** unseen out-of-sample validation.
4. Run each through `ml4t.backtest.Engine` at the same source resolution. Preserve the first-fill OCO policy, one-bar time exit, cost assumptions, and trial identity. No hand-written execution simulator.
5. For risk-normalized B2/B3, simulate MNQ's separate per-contract commission, slippage/tick cost and integer sizing. Report **R-multiples** alongside USD P&L. Compare gross/net, worst-case loss, stop rate, max drawdown, return stability by year, and 2026 loss attribution. Include gap overshoots and failed/inconclusive variants.
6. Do not choose the variant that maximizes 2026 hindsight P&L and claim it will generalize. Do not read data after July 14, 2026 or modify the promoted baseline.

**Done condition for this planning stage:** the original archive verifies; a separate draft YAML and methodology exist; no trials run and no original strategy files change.

**Decision needed next:** approve execution of the small B0–B3 comparison, or revise the trial list first.
