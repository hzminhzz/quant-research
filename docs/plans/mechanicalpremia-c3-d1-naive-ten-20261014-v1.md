# C3 D1 ten-variant naive-entry sweep — frozen research plan

**Goal:** Increase 58 historical D1 closed trades while retaining economically plausible profits. Baseline C3 H1+daily is retained, unchanged and unapproved. **10 independent predeclared variations**, not 10 adaptive rounds that tune after seeing outcomes.

**Causal shared inputs:** US500, US100 Dukascopy 1min BID data. Daily sessions close 17:00 America/New_York; no incomplete session (<1000 minutes), past warmup only. Use ml4t.engineer ATR20 EMA100 BB(10,3) to calculate the common trend/lowvol/percent-B flags. Orders submitted only after completed source session, NEXT_BAR fill. Do not change H1 signals, stop, D1 exit percent-B>0.8, commission, slippage, risk budget or notional cap.

**Original D1:** close>EMA100 AND ATR20<100-session median AND percentB(10,3)<0.20.

## Frozen ten hypotheses

| Trial | EMA100 uptrend | Low ATR (<100-median) | %B pullback cutoff | Economic assumption |
|---|---|---|---|---|
| N01-LV-PB35 | Yes | Yes | 0.35 | Keep EMA100 trend and ATR20 below median; relax percent-B threshold 0.20 to 0.35 |
| N02-LV-PB50 | Yes | Yes | 0.5 | Keep EMA100 trend and ATR below median; relax percent-B <0.50 |
| N03-LV-PB80 | Yes | Yes | 0.8 | Keep EMA100 trend and ATR below median; relax percent-B <0.80 |
| N04-PB20 | Yes | No | 0.2 | Keep EMA100 trend and source percent-B <0.20; drop low-volatility ATR percentile filter |
| N05-PB35 | Yes | No | 0.35 | EMA100 trend and percent-B <0.35 only |
| N06-PB50 | Yes | No | 0.5 | EMA100 trend and percent-B <0.50 only |
| N07-PB80 | Yes | No | 0.8 | EMA100 trend and percent-B <0.80 only |
| N08-LV-ONLY | Yes | Yes | None | EMA100 trend and ATR below median; remove Bollinger pullback gate |
| N09-TREND | Yes | No | None | EMA100 trend-only entry, no volatility or Bollinger gate |
| N10-VOLPB20 | No | Yes | 0.2 | ATR below median and percent-B <0.20; remove EMA100 trend gate (regime-ablation control) |

**Coverage:** Combined H1+D1 source weights, 10 variants x 14 calendar-year annual resets, years 2013–2025 and 2026 YTD through Oct11. Per-event native D1 entries, fills, closed trades and equity recorded. Cost 1x for all 140, 2x cost for fixed 2021/2024/2025/2026 on all 10 (40 further cells); no winners chosen before testing.

**Baseline:** Read C3's previously completed SOURCE-US2 and D1-US2 at 1x, including original per-year D1 count. Compare the same per-asset nominal risk sizing in combined portfolio. Standalone D1-only attribution is separate; never claim the combined D1 entries must match standalone due to shared risk caps. Compare 2026 YTD separately, never treat as full year. Do not call any date virgin OOS.

**Primary required diagnostics:** D1 signal frequency, actual entries and closed trades (not simply conditions), win rate, closed profit factor, total net annual account-return mean and profitable-year count, mean annual daily Sharpe/Calmar, worst-year max DD, cost sensitivity, and paired-year deltas vs source rule. Include ALL ten, including negative cells, and trial-count caveat. No Sharpe-only ranking or automatic promotion. Report impacts on H1 from shared capacity.

**Pass for advancement to further research only:** D1 closed trades materially increase (target >=1.5x baseline 58, not guaranteed), nonnegative costs-adjusted average annual return, at least 8/14 profitable combined periods, no >1.5x old worst-year max DD, and no single year driving most profits; flag if any are not measured. These are exploratory criteria, NOT proof.

**Scientific limits:** Earlier universe selection and 2025/2026 inspection consumed historical holdout. Multiplier=1 and fractional unit proxy vs actual broker, BID-only ask/spread, overnight financing, source MT5 session parity, H1 initial stop gap and year resets all remain unresolved. No stop or exit modifications allowed in this sweep. No live orders. Preserve new/failed trials and artifacts.

**Method:** ML4T `compute-features`, `run-backtest`, `sensitivity-analysis`, `backtest-overfitting`, `risk-metrics`, `point-in-time`, `cost-model` skills; actual `ml4t.engineer.compute_features` and `ml4t.backtest.Engine`; independent checks for causality, identity and valid native fills.
