# Autonomous target: ML4T FX support execution v2

Repo: /home/quant/dev/quant/quant-research
Frozen successor: config/research_sessions/fx_support_ml4t_execution_20261008_v2.yaml
Original false P0 stop: run_log/research_sessions/fx_support_ml4t_execution_20261008/diagnostics/P0_engine_execution_gate.json
No holdout, no commit or push, no alteration of original immutable records.

## CRITICAL TIMING CORRECTION — PROVEN
Original P0 submitted at retest 30m boundary CALLBACK t+30; Engine NEXT_BAR filled t+35, then treated this as a blocker.
But 5m data has BAR-OPEN labels. Last 5m component of retest [t,t+30) is stamped t+25, with its FULL OHLC first known at t+30. The completed bar callback stamped t+25 submits market order and Engine NEXT_BAR fills at t+30. This is causal standard close-to-next-open alignment, no future OHLC. Independent test tests/test_fx_support_ml4t_boundary_v2.py PASSED with created_at=t+25 and filled_at=t+30. Review and incorporate into new P0; do not repeat erroneous t+30 callback assumption.

## Prior verified reusable work
- ML4T Engineer regeneration: scripts/verify_fx_support_ml4t_features_20261008.py and run_log/fx_support_ml4t_execution_20261008/feature_integrity_v1.json (PASS all 13 features 1395 events 730 OOF signals).
- Native Engine tests tests/test_fx_support_ml4t_execution_20261008.py (7 tests PASS including OCO, stop-first tie, worse-of-open stop gap, MOC terminal, cash rejection, real fees). Do not modify these prior tests to mask failures.
- Frozen 730 OOF scored event predictions and 112 selections: run_log/fx_support_conditions_20261008_ml_v2/I4_purged_lightgbm_v2/scored_events.parquet.
- Six development EURUSD/GBPUSD/AUDUSD 5m Parquet inputs in data/processed/ftmo_fx_reversion_202610, years 2010-2024. Files with holdout in filename are FORBIDDEN to read for strategy calculations. Test window 2017-2024.
- Existing dirty concurrent repo; preserve other work. Read applicable AGENTS.md/docs and ml4t-run-backtest, ml4t-compute-features, ml4t-lookahead-bias, ml4t-purging-embargo, ml4t-cost-model.
- Frozen successor already init and check PASS; do not edit YAML.

## Execute
1. Inspect HEAD/status/tmux/artifacts. Preserve original failed P0 as historical review in successor ledger (H0_initial_timing_gate_failure).
2. Test successor P0 with synthetic actual Engine fills at t+30 from final 5m callback t+25, plus native broker OCO/stop-first/stop-gap/target/final-close/account costs/cash. Record P0_engine_execution_gate via research_session.py record to an external task-owned v2 evidence JSON. Do not invoke built-in diagnose (100k cap).
3. Engineer stage: link prior independently verified feature parity, rerun if needed; do not retrain, tweak ML cutoff, or import label outcomes into live signal feed.
4. Implement real installed ml4t.backtest.Strategy plus Engine and run E0 unfiltered 730 events (2017-24), E1 112 OOF ML-selected with same execution, E2 selected at cost stress 2.5bp roundtrip, E3 selected flat before Prague midnight. Long only. Signal after retest close; entry next 5m open. Native bracket STOP at origin support first, LIMIT target at previous high+1e-5 second with shared parent OCO. Gap-aware stop and stop-first ties; no free same-bar fills. Risk .5 percent current equity per entry, 1 percent concurrent, one position per pair, quantity down to 1000 base units, max gross 3x equity, initial USD100k. Time expiry 240 complete 30m market bars; close terminal positions. Explicit cash/margin. Commission .25bps per side fraction .000025, slippage .50bps fraction .00005; stress slippage fraction .0001. Inspect native fees, prices, order statuses. Never simulate custom PnL loops.
5. Produce native Engine portfolio equity, true ledger, net realized R, net USD, daily-equity Sharpe, DD, pair/year decomposition, trade/entry rejection counts, timing, worst Prague day, stress comparison. Explicitly label missing overnight swaps and exact FTMO execution data as limitations.
6. Test causality, 5m/30m timestamp, no holdout, OOF artifact identity, risk, stop/target priority/cancellation, cost units, PnL reconciliation. Predeclare all rules already frozen; no post-result tuning.
7. Run large backtests in a unique checked tmux session ml4t-fx-support-backtest-20261008-v2 with logs/metadata. Verify process alive, final logs, expected artifacts and final trial status. Register all completed or failed trials using research_session.py record. Read final report, check status/diff, deliver evidence.

Use Codex subagents for independent timing/accounting review if available. Run autonomously through ordinary errors; only genuine invariants trigger a BLOCKED result. Do not use external MCP connectors, internet, or extensive unrelated searches. No commit/push or edit frozen/prior files.
