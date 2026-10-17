# Autonomous Codex objective — FX Support ML4T Engineer + Backtest

Repository: /home/quant/dev/quant/quant-research
Session: fx_support_ml4t_execution_20261008
Frozen spec: config/research_sessions/fx_support_ml4t_execution_20261008.yaml
Existing immutable gate: run_log/research_sessions/fx_support_ml4t_execution_20261008
Status: FROZEN / EXPLORATORY / NOT_APPROVED. Do not edit the frozen YAML.

## Mission

Implement and RUN the repo-governed, real ML4T feature and event-driven backtesting workflow, not just a plan. Test whether the pre-existing 112 out-of-fold LightGBM-selected support-retest signals yield positive executed net trading PnL versus the same 730-event unfiltered development cohort. Use strict time and fill correctness. The 2025-2026 frozen final holdout must remain unopened and unscored. The result must not be mislabeled as verified prop trading or approved live.

## Repo obligations

1. Inspect branch, HEAD, git status, remotes, current tmux sessions, concurrent work, existing artifacts, and applicable nested AGENTS.md. Respect all dirty/concurrent changes; stage/commit/push NOTHING. Never reset/clean/stash/delete unrecognized files. Add only unique task-owned new files.
2. Read AGENTS.md, docs/research_sessions.md, full frozen session, prior result/ledger, run_log/validation_status.json and .agents/skills: ml4t-run-backtest, ml4t-compute-features, ml4t-polars-patterns, ml4t-lookahead-bias, ml4t-purging-embargo, ml4t-validate-data and cost guidance. Observe installed API versions/signatures; verify against installed code not example API guesses.
3. Use subagents for independent (a) engine order mechanics including bracket/OCO and fills, (b) lookahead/timestamp/holdout audit, and (c) accounting/test review if tools available; integrate their findings independently. No concurrent edits to shared files.
4. Do not alter parameter choices after seeing results; all changes are engineering/test fixes, document deviations and failures. Record all trials with scripts/research_session.py and immutable evidence, including blocked/inconclusive.

## Frozen signal/feature contract

- Canonical input only local LSE-derived DEV EURUSD GBPUSD AUDUSD 5m snapshots under data/processed/ftmo_fx_reversion_202610. Do not open any file whose filename contains holdout for strategy calculations, or any price data after 2024-12-31.
- Parent target event ledger: run_log/fx_support_reclaim_newhigh_20261008/D0_support_hold_new_high/event_labels.parquet
- Fixed feature panel (already built using ml4t.engineer.compute_features): data/features/fx_support_conditions_20261008.parquet; manifest identity.
- Immutable OOF ML predictions and selected events: run_log/fx_support_conditions_20261008_ml_v2/I4_purged_lightgbm_v2/scored_events.parquet. 730 OOF events 2017-2024, 112 at cutoff p>=0.30, 55 positive future labels (NOT trades).
- Do not rerun hyperparameter search, retrain using validation labels, use event outcome columns as predictive input, touch final holdout, or revise OOF probabilities.
- Proper ml4t.engineer stage: regenerate/verify causal EMA50 ATR20 ATR100 and fixed event features with the installed public ml4t.engineer.compute_features, confirm consistency with frozen panel, and persist a versioned feature integrity/availability report. Those previous labels are custom path-dependant; do not claim generic triple-barrier library produced them unless independently correct.

## Required backtest implementation

- Real installed ml4t.backtest.Engine(DataFeed(...), Strategy subclass, BacktestConfig(...)). No hand-rolled PnL/backtest loop or ad hoc Sharpe. Do not count raw event labels as fills.
- Signal timestamp stored in event ledger is 30m RETEST BAR OPEN. Decision may occur only after its 30m close. Correct next 5m open entry on standard bar-open timestamps with engine NEXT_BAR. Synthetic fixture MUST assert actual submit/fill timestamps, not just attributes.
- Long only, one position/symbol, one shared USD100k account, concurrent risk <=1.0% equity, initial 0.5% equity risk/position, size down 0.01 lot (1000 base units), gross exposure <=3x equity, leverage/margin explicit. No future references.
- Target reference high+0.00001, hard intrabar stop origin support (different than parent label's 30m closing invalidation), one-cancels-other; stop before target if both reached in same 5m bar; gap down stop fills no better than available open; time expiry 240 completed 30m bars, also next executable bar / gaps.
- If broker cannot guarantee OCO or stop-first/gap ordering, fix via DOCUMENTED verified native engine API/rules; if still impossible DO NOT create synthetic PnL as native: report P0 BLOCKED and stop economic trials.
- Base costs per side commission .25bps = 0.000025, slippage/spread .50bps = .00005, total RT approx 1.5bps. Stress slippage/spread 1bp per side=.0001, RT approx 2.5bps. Verify code units, realized effective roundtrip drag.
- Continuous multi-pair daily equity from ml4t backtest with zeros on no-position days, compare same 2017-24 chronology E0 vs E1. For long 240bar runs overnight swaps unavailable -> explicitly say cannot claim exact prop economics. E3 closes before Prague midnight, independent variant, no overnight swap; ensure no false session resets.
- Report engine ledger: actual entries/exits, reject reasons, exit reason stop/target/time/prague, net PnL, R, daily Sharpe, DD, worst Prague day, per-year/pair, exposure, 5/10% breaches, matched baseline, max pending, integrity. No percentage-to-bps errors, no next-bar lookahead, no unrealistic same-bar exit.
- Trials frozen in order: P0_engine_execution_gate first; if passed, E0_unfiltered_oof_cohort, E1_lightgbm_oof_capped_risk, E2_lightgbm_cost_stress, E3_lightgbm_flat_before_daily_reset. Must record completed/failed with artifact and generate report. Do not optimize.

## Execution and verification

- Use small synthetic end-to-end broker tests for market next-open, stop/target priority, target/stop first, gap-open stop, terminal closure, cash/risk, and 30m-to-5m timestamp. Confirm actual trades and fees. Add parity tests for engineer features and OOF identity/timestamps.
- Before a long job check existing tmux; if > tool session lifespan, run it in uniquely named tmux ml4t-fx-support-backtest-20261008 and preserve exact command, log, HEAD, spec sha. Do not reuse or kill unknown sessions. Confirm launched and initial output. Track until result or a real blocker.
- Run required tests, data gate, inspect final output, reconcile engine PnL and metrics, inspect changes. If ordinary code/test errors occur, diagnose and fix then rerun only as permitted by immutable trial handling (failed attempts versioned).
- The repo has extensive unrelated dirty changes. Never touch/stage them. Keep all new files under task-owned filenames/config/scripts/tests/run_log. Commit/push prohibited.
- Required final report: exact status, verified files, cost/stop semantics, independent checks, metrics and caveats, and blockers. Do not call a worker report proof without audit.

Finish the actual engineering/backtest run if the engine can satisfy the gates. If blocked, record an honest BLOCKED status with the exact failing invariant and evidence. Do not ask for user clarification on routine engineering choices.
