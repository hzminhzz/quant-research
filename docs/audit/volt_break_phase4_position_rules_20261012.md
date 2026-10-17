# VOLT BREAK Phase 4 — Native PositionRule / RuleChain probe (2026-10-12)

## Decision

**PARTIAL PASS on post-entry risk management; BLOCKED for exact original Phase 4.**

The installed `ml4t-backtest 0.1.7` Engine wires `Broker.set_position_rules` to native `Broker.evaluate_position_rules`, and the position-rule pipeline owns fill and accounting records. The existing Phase 4 independent-order bracket remains unsafe. A custom fixed-point stop-first `PositionRule` inside `RuleChain` generates only one exit when an *already open* position's one-minute OHLC reaches both thresholds. However, ordinary NEXT_BAR strategy entries become filled **after** the Engine has already evaluated position rules on that bar. The entry minute is therefore **unprotected**, and using this pathway alone is not an exact execution of VOLT BREAK.

**No historical Phase 4 strategy trial was run. No strategy win rate, Sharpe, Calmar, profit factor, or net expectancy was estimated.** This experiment used synthetic bars only and read no 2026 market outcomes.

## Work and provenance

- Repository: `/home/quant/dev/quant/quant-research`
- HEAD checked: `c095faab89835c49f4cd6fd66d1a9ed922709039`, branch `main`, with unrelated dirty work preserved.
- Engine: installed `ml4t-backtest 0.1.7`, inspected runtime code for `RuleChain`, `Broker.set_position_rules`, `Broker.evaluate_position_rules` and `Engine._run_once`.
- Frozen Phase 4 strategy reference: `config/research_sessions/volt_break_nq_phase4_20261012.yaml`
- Probe predeclared as: `config/research_sessions/volt_break_nq_phase4_position_rule_probe_20261012.yaml`
- Focused tests: `tests/test_volt_break_phase4_execution_20261012.py`; the five pre-existing fixtures were preserved, with five new position-rule fixtures added.
- Independent test run: `.venv/bin/python -m pytest -q tests/test_volt_break_phase4_execution_20261012.py` returned **10 passed in 1.32s**. The previous five Phase 4 fixtures still passed.
- `git diff --check` returned no errors. No commit, push, data mutation, or real order.

## Native Engine evidence

At each one-minute event, `Engine._run_once` updates the broker's current OHLC state and then calls:

1. `preopen_target_manager.process_opening(timestamp)`
2. `broker.evaluate_position_rules()`
3. For NEXT_BAR, `broker._process_orders(use_open=True)` on existing pending entry orders
4. Only then, `strategy.on_data(...)` for new submissions.

Consequently, a normal pending MARKET entry submitted from the completed 09:59 minute fills at the 10:00 OPEN **after** the 10:00 position-risk evaluation. The engine does not retroactively evaluate that minute's low/high against the new position's stop/target. A violent 10:00 price excursion can be entirely omitted as a TP/SL event. This fails the original strategy's entry-minute protection requirement.

`RuleChain` is not merely a detached utility. `Broker.set_position_rules(rule, asset=...)` registers it with the risk subsystem, and `Engine` calls that subsystem each event. `RuleChain` returns the first non-HOLD action. This avoids two independently live OCO sibling exits for an already-held position.

## Verified synthetic behaviors (ten tests total)

| Area | Observation | Status |
| --- | --- | --- |
| 09:59 decision -> 10:00 next OPEN | Fill occurs at 10:00 source open; callback at 10:00 would fill at 10:01 | PASS |
| Ordinary entry minute hits TP/SL | Native position rule does not exit; the position remains open | **FAIL for exact strategy** |
| Already-held position touches TP and SL same minute | Custom stop-first fixed-point rule returns exactly one native exit, no reversal | PASS for conservative scenario |
| Fixed absolute target | +40 points at entries of 100 and 1000 yields exits at 140 and 1040 | PASS |
| Fixed absolute stop | -75 points evaluated correctly after entry bar | PASS |
| Gap-through stop | Native stop exit uses opening price, not an incorrectly guaranteed stop price | PASS |
| Target-only and stop-only | Exactly one exit, with Engine-owned fill | PASS |
| Accounting reconciliation | +40 points gives +$800, -75 points gives -$1500, gap -80 gives -$1600 (20 USD/point, zero-cost fixture) | PASS |
| Hard exit | Sell submitted at 14:29 fills at 14:30 opening quote in synthetic timing fixture | PASS |
| Old independent bracket tests | Conflicting sibling fills and unprotected entry-minute failures remain reproducible | PASS as regression checks |

Tests verify behavior of the simple strategy callback pathway. They do **not** establish that the alternate native `preopen_target_manager` / `CanonicalTargetIntent` path can solve the entry-minute protection gap. That path appears before rule evaluation in `Engine._run_once` and is a bounded next candidate, not a verified solution. It requires separate synthetic tests for fill timing, rule installation, stop-first conflict resolution, account ledger invariants and ability to submit an intent causally after the 09:59 completed decision.

## Interpretation

- Native `PositionRule` / `RuleChain`: **VERIFIED** useful for mutually exclusive, conservative post-entry exits.
- Same-entry-minute TP/SL protection for ordinary `Strategy.on_data` NEXT_BAR market orders: **VERIFIED FAILURE**.
- Exact frozen VOLT BREAK historical backtest: **BLOCKED** until entry-minute risk is fixed in the Engine-owned execution path.
- 1m OHLC cannot determine the actual TP-vs-SL first-touch order. Stop-first is a conservative *stress convention*, not observed execution.
- Existing Dukascopy USATECH.IDX/USD data is BID CFD index proxy; provider units are not CME traded futures volume; costs and basis remain unverified.
- Phase 3 observed negative average continuation. This position-rule probe is not additional alpha evidence.

## Next bounded action

Test `CanonicalTargetIntent` / native pre-open target manager. It precedes `evaluate_position_rules()` and may create the position and install its rules at the 10:00 open. If it cannot preserve causal 09:59 signal, same-10:00 OPEN entry, instantaneous stop-first protection and Engine-owned PnL, use a small, independently tested execution-lifecycle adapter or upgrade native engine; do not silently simulate missing fills or report invalid historical performance.

Codex's CLI encountered an out-of-credits error during final report generation; this report and independent final pytest verification were completed through the VPS workspace tools. The five prior and five additional synthetic tests passed.
