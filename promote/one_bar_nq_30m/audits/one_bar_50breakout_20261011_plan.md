# One-bar 50-bar extreme breakout — seven-phase research plan (2026-10-11)

Status: PLANNED / EXPLORATORY / NOT_APPROVED. This is a planning document, not a frozen session specification or a backtest result. No trades were placed. Research date cutoff: 2026-10-11.

Repository authority: AGENTS.md, docs/research_sessions.md, SESSION_TEMPLATE.md, run_log/validation_status.json, and task-relevant installed ML4T skills. This plan follows the seven-phase research structure in run_log/prop_mvp_20261011_mission.md, with Phase 0 preflight separated for clarity.

## Phase 0 — Preflight
- Inspected branch main at c095faa and existing dirty/untracked work; preserve all unrelated files.
- Read session guide, template, validation status, and matching ML4T research/backtest/calendar/data/cost/continuous-futures skills.
- Existing repository-wide legacy ORB decision remains NOT_APPROVED; this study does not modify it.
- No separate canonical eight-phase rule was identified: SESSION_TEMPLATE.md has Phase 0–5, strategy-workflow has seven stages, and the recent seven-phase research mission gives the practical empirical sequence.

## Phase 1 — Thesis and exact rules (draft; NOT frozen)
Hypothesis: stop orders triggered by the previous 50 completed 30-minute bars' extremes experience positive directional drift until the beginning of the next 30-minute bar, with sufficient gross edge to exceed costs. Mechanism candidate: clustered breakout/stop flow and delayed liquidity replenishment. Competing mechanism: transient stop runs reverse before the following bar.

Primary universe: actual dated CME/CBOT E-mini futures contracts NQ (Nasdaq-100), ES (S&P 500), EMD (S&P MidCap 400), YM (Dow Jones). No equity index level, CFD, or vendor alias substitutes for exchange futures execution.

Original parameters to preserve unchanged across products:
- 30-minute bars anchored to the actual Globex calendar; 50 **completed** bars in rolling extrema, never the forming bar.
- While flat, a buy-stop at the preceding 50-bar highest high and sell-stop at preceding 50-bar lowest low; one-cancels-other when one fills.
- Entry trigger occurs during the following eligible bar; exits at the open of the next 30-minute bar after the entry bar, or earlier on the protective stop.
- One contract per entry in the baseline unless a position-sizing constraint forces a no-trade; one global $1,000 loss-stop per trade, using the actual contract multiplier and ticks.
- At most two filled entries per instrument per exchange trading day; no simultanous long and short on one instrument.
- Orders are disabled/canceled during Globex maintenance, trading halts, and roll boundaries as dictated by exchange calendar; define behavior when an exit coincides with a closed session.

Execution interpretations to preregister before running:
- If gap opens beyond stop-entry trigger, do not grant a fill at a better unavailable stop price.
- If both entry triggers or entry and protective stop appear within one coarse bar, use lower-resolution ordered data; unresolved paths must be handled conservatively or reported ambiguous.
- Account for stop-market slippage and exits at the actual tradable next-bar opening quote, not the last printed preceding close.
- A stop-market order limits the trigger price, not maximum realized loss.
- For live production, broker fill/fee schedule and margin must be sourced and dated.

Proposed falsifier (to freeze with evidence thresholds): no economically meaningful positive post-cost 30-minute expectancy on NQ, or apparent gain vanishes under correct entry/stop sequencing and plausible friction; the four-product transfer claim fails if original untouched parameters have materially negative results on replication products. Portfolio-level diversification is a separate hypothesis because indices are correlated.

The original claim of ~$41 average profit per trade and ~$100 in high-volatility episodes is prior reported performance, not independently verified evidence. The high-volatility pause/switch is NOT a baseline trading rule; test separately only with preregistered definitions and additional trial accounting.

## Phase 2 — Source data and contract integrity
- Available in this checkout: data/processed/nq_1m.parquet and data/processed/es_1m.parquet (file existence verified only; contents, provenance, and coverage NOT YET audited).
- EMD and YM futures 1m files were not found under the inspected repository data directory. Search canonical ml4t-data store before declaring them unavailable or acquiring anything.
- Verify actual dated contracts, coverage, timestamp meaning and timezone, session gaps, roll policy, OHLC sanity, duplicate/zero-volume periods and executable prices.
- Derive 30m from validated 1m where possible; for contested intraminute ordering, report residual ambiguity. Do not rely on vendor index proxies for futures fills.
- Decide chronological exploratory/development period based on verified coverage and previously protected windows. Do not claim any reviewed 2026 history is a fresh final holdout.

## Phase 3 — Causal entry-event study
- Count signal opportunities, triggered entries, and skipped/conflicting events by product and session.
- Measure post-entry price path to the next bar open; separate upside/downside, gap-open triggers, session times, volatility states, and rollover windows.
- Compare with contemporaneous same-time-of-day / volatility-matched placebo entries. Use outcome-aware clustered confidence intervals by trading day (and avoid treating simultaneous indices as independent samples).
- No ML model or parameter search for the primary MVP.

## Phase 4 — Native ML4T event-driven execution
- Inspect installed Engine/Strategy/Feed/Config signatures and order capabilities first; use ml4t.backtest as repository AGENTS.md mandates.
- Implement one original-rule NQ baseline and then identical parameters for ES, EMD, YM with only actual contract-specific multipliers, tick sizes, fees and session identity.
- Model stop entry, protective stop, next 30m opening-market exit, OCO, two-entry daily cap, maintenance breaks, roll handling, cash/margin and round-trip costs.
- Compare zero-cost price-path reference versus cost-aware realized returns. Track order/trade/equity ledger and cost attribution per instrument.

## Phase 5 — Chronological validation
- Freeze selection criteria before observing development results; separate exploratory chronological periods and genuine protected forward/final test.
- Check positive net expectancy and confidence limits, profit factor, daily-equity Sharpe, max drawdown, trade concentration and whether the effect persists across years/regimes.
- Classify already viewed periods as retrospective; do not unseal any protected holdout without a registered justification and explicit approval.

## Phase 6 — Small falsification and robustness panel
- Prespecify bounded checks: baseline costs / 2x costs, added one-bar execution latency, 1m path resolution/ambiguous-bar exclusion, cash-session vs overnight attribution, largest-winner removal, low-vol/high-vol descriptive slices.
- Parameter neighborhoods (e.g., 40 and 60 lookback) are additional explicitly tracked trials, not evidence that the original 50-bar no-change claim passed.
- Cross-market robustness must account for synchronized equity-risk exposure and common event timing.

## Phase 7 — Independent audit and research decision
- Run relevant tests, reconcile native backtest fills/cash with event-study path boundaries, verify margin/tick/roll/cost identities, trade-count and day-limit invariants, and review all trial artifacts.
- Record session YAML, source/data hashes, raw fills, daily equity, assumptions, failed trials, execution logs, and next decisive question under task-owned paths.
- Research decision: SUPPORTED FOR FURTHER FORWARD VALIDATION / REJECTED / INCONCLUSIVE / BLOCKED. Do not treat research completion as authorization for live trading.
- Preserve unrelated dirty work and never silently change run_log/validation_status.json. Commit/push only when specifically authorized.

## Key unknowns before freezing the formal YAML
1. Original author's exact treatment of both stops hit within one 30-minute bar; pending-order renewal after a fill; and exchange trading-day cap.
2. Native stop/OCO and intrabar fill abilities in the installed ML4T Engine.
3. True NQ/ES/EMD/YM contract coverage and price source/roll policy, including canonical ml4t-data.
4. Broker-specific per-side commission, fees, spread, stop-slippage and margin.
5. Permissible evaluation/final-test boundaries in view of already examined index history.

Current next step: Phase 1 freeze-ready rules and Phase 2 data/cost preflight. Do not initialize a frozen research session until mandatory instrument/data/cost identities and evaluation boundaries are resolved.
