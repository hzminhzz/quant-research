# VOLT BREAK Phase 4 follow-up: Test native PositionRule/RuleChain (execution gate ONLY)

Work as coding executor in `/home/quant/dev/quant/quant-research`. Implement and **run** focused synthetic native ml4t-backtest Engine tests of position rules for the frozen VOLT BREAK 1-NQ-equivalent +40-point TP/-75-point stop (illustrative $20/point). Determine whether native RuleChain or the engine's installed position-rule pathway actually solves double-sibling exit, same-entry-minute protection, stop-gap fill, temporal accuracy, and causal 14:30 CT hard exit. Do NOT run historical strategy trials or touch any 2026 outcomes; no real orders. Research decision remains mine.

Start inspect Git branch/HEAD/status/remotes, active tmux, existing docs and applicable skills. Read AGENTS.md, docs/research_sessions.md, Phase 4 frozen spec `config/research_sessions/volt_break_nq_phase4_20261012.yaml`, docs/audit/volt_break_phase4_20261012.md, tests/test_volt_break_phase4_execution_20261012.py, installed ml4t-backtest engine source 0.1.7. Protect unrelated dirty files, previous frozen trials and all artifacts; only create task-owned new files. Read installed ML4T procedure skills (run-backtest, lookahead-bias, cost-model) before coding. Do not hand-roll backtest execution loops.

Important: Don't assume RuleChain can connect to Engine. Inspect actual constructor/API and library internals, find where `PositionRule.evaluate` is wired, when called relative to open fills, and how it applies fill price/ledger; inspect risk rule order behavior and whether percent-based StopLoss/TakeProfit can support fixed 40/75 points (custom PositionRule protocol if supported). It may be an unattached helper.

Create preregistered diagnostic file `config/research_sessions/volt_break_nq_phase4_position_rule_probe_20261012.yaml` or report pre-declared test cases before testing. Use native Engine fixtures and focused pytest:
(1) 09:59 completed minute decision -> 10:00 next OPEN entry (not 10:01);
(2) entry row moves to TP +40 and/or stop -75: verify immediate protective behavior, no next-minute delay;
(3) already-open long, same 1m bar touches both TP and SL: engine makes exactly one stop-first exit, zero reverse, authentic Engine-owned trade;
(4) stop-market gap below stop fills at gap OPEN, even if more adverse than -75;
(5) single TP-only and stop-only touch, no opposing sibling residue;
(6) optional CT 14:30 boundary market exit without late fill;
(7) metric/ledger reconciliation & fixed POINT targets independent of entry price level;
(8) show unchanged prior 5 synthetic tests pass.

If RuleChain is not connected to Engine or doesn't handle intrabar entry protection, record **BLOCKED** with direct source/test evidence; do not make manual PnL adjustments or claim solved. If RuleChain is viable with a minimal strategy-local adapter, implement that adapter only if Engine still owns fills/accounting, stop-first OCO is enforced and entry minute protected; test on synthetic examples. Keep backtest stricter than data admits; mark both-touch unobservable order as stress case.

Run all new tests and relevant existing fixtures. Record output JSON `run_log/research_sessions/volt_break_nq_20261012/phase4_position_rule_probe_20261012.json` and human report `docs/audit/volt_break_phase4_position_rules_20261012.md`. No full historical backtest in this scoped probe unless expressly newly requested. No Git commit/push. Independently inspect artifacts and final git status, exact test counts. If Codex is unavailable, surface blocker and avoid duplicate autonomous sessions. No claim of verified until tests actually run. Finish with explicit PASS/BLOCKED, evidence, and next step.
