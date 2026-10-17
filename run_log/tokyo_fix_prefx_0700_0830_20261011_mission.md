# Autonomous mission: Tokyo Fix Program 4A — 07:00–08:30 JST Gotobi long

Principal coding/research executor. Repository: /home/quant/dev/quant/quant-research.
The user approves EXECUTION, including implementation, native backtests, independent verification, final report. Do not stop at planning. No live trading, commit, push.

## Read / inspect actual current state FIRST
Inspect Git branch, HEAD, status, remotes/upstream and recent commits, research spec, issues if available, tmux sessions/processes and other agent runs. DO NOT kill unknown sessions, reset, clean, stash, modify unrelated existing dirty work. Read AGENTS.md and any nested AGENTS.md, SESSION_TEMPLATE.md, docs/research_sessions.md, run_log/validation_status.json, and latest Program1, Program2, Program3 reports, frozen manifests, v3 alpha map and relevant ledger. Read locally installed relevant full ML4T skills (validate-data, polars-patterns, point-in-time, calendar-ops, compute-features, evaluate-factor, run-backtest, transaction-costs, cost-model, non-stationarity, regime-awareness, lookahead-bias, sensitivity-analysis, backtest-overfitting) before implementation; inspect signatures of installed ML4T APIs. Independently verify results; delegate bounded read-only audit to Codex subagents where useful. Use tmux for long jobs and make sure no duplicate exists.

## This is a specific NEW research session, not optimization
Study ONLY preregistered **calendar-only LONG USDJPY 07:00–08:30 JST** on prior BOJ calendar-defined Gotobi sessions. Hypothesis: Japanese corporate settlement USD demand creates early Tokyo buying pressure. Strongest retrospective prior Program1 observed 07:00–08:30 gross mean +1.474 pips over 415 Gotobi with weekday/year-adjusted +2.715 pips vs ordinary, Holm18 p~.0386. Program2 USDJPY 07:00–08:30 adjusted +2.110 LOG bps, Holm16 p=.0162; differs in units/cohorts. Both are PREVIOUSLY INSPECTED, NOT INDEPENDENT holdout. July-Aug 2026 allowed as already inspected research history; Sep-Oct 2026 (>= 2026-09-01 JST) is SEALED, NEVER read.

Execution identity:
- canonical immutable 7 annual USDJPY 1m LSE proxy snapshots: data/processed/tokyo_alpha_map_program1_v1/USDJPY_03_12_JST_<year>.parquet, years 2020-2026. BOJ bank-calendar registry run_log/tokyo_fix_alpha_map_program1_20261010/execution_v1/calendar_event_registry.parquet. Venue assumed unspecified retail FX broker: broker CFD/spot bid/ask, real swap, spread, margin and contract details UNKNOWN.
- Input timestamps UTC label minute OPEN. Market entry at 07:00 JST by order submitted 06:59 (calendar known in advance), NEXT_BAR open fill. Exit order 08:29 -> fills 08:30 NEXT_BAR open. Existing Program1 after-fix short and original 08:30–09:54 long benchmarks reused with sample distinction. Ordinary Tokyo business days same 07:00–08:30. No position overnight.
- USD starting equity 10000, 10000 USD base notional every eligible event (no compounding), no implied leverage >1 gross. Native Engine quote accounting JPY reconciled to USD conversion at executed exit USDJPY. Fill cost reference 1.0 pip roundtrip with 0.5 pip adverse price each fill; sensitivity 0.8,1.0,1.4,2.0 pips (must report actual execution costs assumptions, not broker-calibrated). May do per-cost native runs or backed-out, clearly distinguish. Cost breakeven and 2×/3× stress if helpful. Critical: no claim costs are realistic without executable bid/ask and commissions.
- Runtime: /home/quant/dev/quant/quant-research uses uv and native ml4t.backtest.Engine 0.1.7 previously verified; do not hand-roll simulator. Use library ml4t.engineer for features and ml4t.diagnostic or appropriate event-level statistical tests for regime diagnostics.

## PRE-FREEZE a narrow design before outcomes
Create new unique session:
config/research_sessions/tokyo_fix_prefx_0700_0830_20261011_v1.yaml
scripts/run_tokyo_fix_prefx_0700_0830_20261011_v1.py plus verifier/tests
run_log/tokyo_fix_prefx_0700_0830_20261011_v1/
docs/audit/tokyo_fix_prefx_0700_0830_20261011_v1.md
Register 6-8 fixed trials T0_data_gate,T1_native_gotobi,T2_native_ordinary,T3_cost_sensitivity,T4_regimes,T5_refutation,T6_independent_oracle,T7_final_audit; initialized/frozen via scripts/research_session.py CLI before new results. Do not overwrite prior artifacts. Document data/provenance, source SHA256, no holdout, method and complete trial list.

## Phase A quality and native market execution
- Verify 06:58–08:30 JST exact contiguous minute price and OHLC; only eligible dates with complete interval, finite geometry, unique UTC timestamps, no interpolation, no synthetic fill, document year/weekday missingness and changes vs old 1418 sample. Cohort should be bank-date calendar only.
- Run native Engine LONG 07:00–08:30 Gotobi AND identical ordinary day control on equal eligibility, then independent native order/fill, timing, JPY/USD reconciliation source original snapshots including no same-bar fills and account reconciliation. Portfolio equity include ordinary flat Tokyo days, not only trade dates.
- Compute net cost ladder $ equity, full sample/yearly 2020,21,..,2025, 2026 Jan-Aug, trade count, gross/net pips, net USD, end balance, win rate, profit factor, drawdown closed and if supported intratrade bar-based, daily Sharpe with calendar flat days, tail/loss concentration, conditional day.
- Sensitivity to latency: predetermined one-minute and two-minute entry DELAYS 07:01/07:02, same 08:30 exit. Important avoid hindsight: submit 07:00/07:01 without knowledge of decision bar and cannot cheat. These are *execution stress diagnostics*, not candidate selection. Regime signals use only bars whose close is known by order submission.
- Distinguish event calendar effect from USDJPY generic Tokyo drift via weekday and year FE with HAC and month-level clustering; include matched non-fix placebo 11:00–12:00 or 10:00–11:30 ONLY if identical 90-minute timeframe exists in source, else precise feasible nonfix window must be frozen before testing. Separate date/placebo missing cohorts. Test whether premium beats ordinary after costs and multiple-comparison correction; do not treat p corrected across a tiny new family as erasing prior extensive searches.

## Phase B regime diagnostics (NOT broad optimization)
Predeclared prior-only risk conditions, before 06:59:
- prev ~30-minute realized log-return volatility (06:30–06:58 inclusive, or similar unambiguous available completed bars), features via ml4t.engineer and Polars, verify feature timestamps.
- 30m drift before 07:00, overnight/prev volatility regime if source supports, no 06:59 close known until 07:00; safer to use 06:58 last closed bar.
- Fit tercile boundaries on 2020–2023 development only, freeze cutoffs; evaluate 2024-25 and Jan-Aug2026 separately; full sample by quartiles optional for descriptive only. Report per-slice n/gross/net/year; HAC CI, risk shift and 2026 breakdown. No regime-filter strategy may be declared approved unless incremental case vs unconditional is independent and robust. Regime filtering based on observed negative years remains HYPOTHESIS only.
- Small number of tests; explicit Holm over declared event/placebo/regime contrasts. Track all negative trials. No LightGBM/parameter optimization. Plain $10k and all-cost PnL. If no edge after costs, fail honestly.

## Final QA
Tests for timestamp & timezone, 2026 seal, pre-signal close cutoff, missing bars, native next-bar order fills, no position carry, same calendar sample controls, USD notional/PnL, cost conversion and sensitivity, independent oracle. Verify current HEAD, Git diff and status, ledger artifact hash, source SHA, run logs and saved report. No unrelated edits, no commits/push. Full unrelated repo tests may be attempted if practical but do not claim pass unless pass. Distinguish Verified/Inference/Hypothesis/Unknown. End with decision approved research complete vs no live approval. If earlier 07:00 study shows weak after cost or 2026 collapse, that is valid negative result. Complete autonomous run, don't just draft plan or send pseudo results.
