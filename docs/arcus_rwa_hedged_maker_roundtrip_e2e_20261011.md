# Arcus/Lighter four-leg controller E2E — October 11, 2026

State: **SIMULATED_E2E_PASS / LIVE_BROKER_E2E_BLOCKED**. Hummingbot checkout: `/home/quant/dev/hummingbot`. No authenticated trading, cash or collateral movement, live orders, commit or push.

## What was executed
- `test/hummingbot/strategy_v2/controllers/test_arcus_hedged_rwa_roundtrip_e2e.py` exercises the real Hummingbot Strategy V2 ArcusHedgedRWAController with exclusively fake private Arcus+Lighter connectors, confirmed synthetic Arcus maker limit fill events, market hedge proposals, 12h virtual hold, synthetic maker exit and corresponding Lighter market unwind. Tests both directions, partial failure/no fills, VWAP depth, stale checkpoints.
- `tools/arcus_hedged_rwa_cycle_e2e.py` provides the controller-based test harness and authenticated-free live **public books only**. Replays always use fresh disposable simulated broker state.
- Full related test suite: **66 PASSED**, 6 unrelated Pydantic warnings. TDD red tests included module missing, missing spread reporting, synthetic state contamination and minimum hedge notional, all resolved. HEAD remains `36d9c64abc88c8ca59c9905ba2b04a1c557ac137`.
- Complete report: `/home/quant/dev/hummingbot/run_log/arcus_hedged_rwa_e2e_20261011/full_cycle_e2e_report.md`.
- Public snapshot JSON: `/home/quant/dev/hummingbot/run_log/arcus_hedged_rwa_e2e_20261011/full_cycle_live_books_20261011.json`.
- Existing separate long-run old-code shadow process still RUNNING, at last check 101/101 healthy SPY and 101/101 healthy QQQ; its results are not code-version verification for new controller.

## Results
- Deterministic synthetic long 0.1 ETF units: four synthetic fills (Arcus BUY maker100, Lighter SELL market100.08, Arcus SELL maker100.6, Lighter BUY market100.5): entry gross +0.08/unit; exit gross +0.10/unit; combined +0.18/unit; total gross PnL +$0.018 (no funding/slippage/fees/rewards).
- Deterministic synthetic short 0.1 ETF units: Arcus SELL maker101.10, Lighter BUY market100.95, Arcus BUY maker100.50, Lighter SELL market100.70: entry gross +0.15/unit; exit gross +0.20/unit; combined +0.35/unit; gross PnL +$0.035.
- Fresh live public market **two snapshots only seconds apart**: SPY long entry +$0.07/unit and hypothetical exit −$0.19/unit => −$0.12/unit before funding/fees, BUT strategy did not enter because initial edge below 2bps. QQQ long entry +$0.55/unit and hypothetical exit −$0.61/unit => −$0.06/unit, BUT strategy rejected the maker exit due to fair-value gate. No actual four-leg trading took place; snapshots 4s apart with simulated 12h clock are NOT 12h held return evidence.
- Grounded rejection is valuable: cross-exchange spread often pays on one side and loses on the other; conditional market and execution economics dominate reward farming.

## Next research gates
Actual 12h+ synchronized snapshots with reliable exchange timestamps, queue/fill and market-order slippage model, realized signed funding and fees, reward account attribution, account contract mappings, private authenticated connectors and emergency two-venue unwind. Holdout protected, no live authorization.
