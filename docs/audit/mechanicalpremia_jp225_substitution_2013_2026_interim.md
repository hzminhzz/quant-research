# Mechanical Premia — JP225 replaces DE30: interim audit

**Session:** `mechanicalpremia-nikkei-replaces-dax-2013-2026-v1`
**Frozen before first candidate outcome:** yes, in `config/research_sessions/` and `run_log/research_sessions/`.
**Control status:** EXPLORATORY, NOT_APPROVED. No live trading. Existing original/2025-26 DE30 experiments remain unchanged.
**Design:** H1 US500/US100/JP225; D1 US500/US100/JP225/EU50. No DE30. Identical native ML4T indicator, fill semantics, sizing, source risk split and assumed direct costs.
**Interpretation restriction:** Nikkei source is Dukascopy `jpnidxjpy` (JPY), EU50 is EUR, US500/US100 USD. All numbers below are price-unit synthetic $100k starting-equity returns with **no FX conversion** and missing broker spread/financing/tick multiplier. Not live USD PnL and not source MT5 fill parity. 2025/2026 were previously inspected under the DE30 experiment, so this is a post-selection exploratory substitution trial.

## Completed paired years — marked equity, direct costs 1bp commission + 2bps slippage per side

| Year | Sleeve | Prior DE30 % | New JP225 % | Change percentage points |
| --- | --- | ---: | ---: | ---: |
| 2013 | Source-weighted portfolio | +2.97 | +5.39 | +2.42 |
| 2023 | H1 breakout | -4.63 | +0.45 | +5.08 |
| 2023 | D1 mean rev | +5.57 | +5.64 | +0.08 |
| 2023 | Equal-risk portfolio | +0.74 | +3.02 | +2.28 |
| 2023 | Source-weighted portfolio | +2.67 | +4.45 | +1.78 |
| 2024 | H1 breakout | -2.03 | +3.64 | +5.67 |
| 2024 | D1 mean rev | +3.74 | +4.36 | +0.62 |
| 2024 | Equal-risk portfolio | +0.96 | +3.65 | +2.69 |
| 2024 | Source-weighted portfolio | +2.08 | +4.30 | +2.21 |
| 2025 | H1 breakout | -2.27 | -3.20 | -0.93 |
| 2025 | D1 mean rev | +6.79 | +5.87 | -0.92 |
| 2025 | Equal-risk portfolio | +2.33 | +1.45 | -0.87 |
| 2025 | Source-weighted portfolio | +4.43 | +3.34 | -1.09 |
| 2026 YTD (through Oct11) | H1 breakout | +2.99 | +6.66 | +3.68 |
| 2026 YTD | D1 mean rev | +3.29 | +3.29 | ~0.00 |
| 2026 YTD | Equal-risk portfolio | +2.98 | +4.73 | +1.75 |
| 2026 YTD | Source-weighted portfolio | +3.20 | +4.07 | +0.87 |

All 24 annual trial/cost cells for 2023, 2024, 2025 and 2026 YTD completed without failure. The 2013 baseline strategies have also completed, including source-weighted +5.39% versus the old +2.97%; 2013 cost stresses and 2014–22 remain in the frozen 84-cell matrix. No historical full-period conclusion yet. Do not infer total 2013–2026 edge from these selected years.

### Predeclared source cost stresses
- 2025: old source +3.43% (1.5x), +2.44% (2x). New JP225 +2.47% (1.5x), +1.62% (2x). The variant worsened.
- 2026 YTD: old source +2.60% (1.5x), +2.01% (2x). New +3.59% (1.5x), +3.12% (2x). The variant improved.
- 2023: new JP225 source-risk +3.61% (1.5x), +2.77% (2x); old DE30 +1.72% (1.5x), +0.79% (2x).
- 2024: new JP225 source-risk +3.44% (1.5x), +2.60% (2x) vs DE30 +1.05% (1.5x), +0.02% (2x).
- All 2013-22 trials and stresses remain to be verified at time of this interim report.

### Forensic instrument evidence
- JP225 H1 2025: 53 closed trades, net -1,080.61 synthetic price units.
- JP225 H1 2026 YTD: 34 closed trades, net +3,094.12 synthetic price units.
- JP225 D1 2025: no closed trade; removing DE30 D1 removes three profitable 2025 DE30 trades from the original D1 sleeve, explaining part of the decline.
- This is historical period dependence and potential selection bias; it is not evidence of an adaptive market-switching rule.

## Data checks and execution
- Canonical JP225 store `index_minute_NIKKEI225`, Dukascopy source symbol `jpnidxjpy`, 1-minute BID CFD, JPY quote units. Long history from Sep 2011.
- Acceptance audit `docs/audit/mechanicalpremia-nikkei-replaces-dax-2013-2026-v1-data-eligibility.json`: Nikkei has 4,134 eligible annual-partition day files in 2013-2026 YTD, zero missing acceptance files, 731 days below the frozen 1,000-minute daily signal threshold (including holiday/short sessions). The audit does not prove tradable ASK spreads.
- Same `ml4t.engineer.compute_features` registered ATR/BB/EMA and native `ml4t.backtest.Engine` as the old strategy. Three new JP225 regression tests and two existing feature-parity checks passed.
- Unresolved H1 entry-minute protective-stop gap, exact broker session/holiday clock, multi-currency NAV and contract/financing. No ML or new feature search introduced.
- No fresh OOS remains in the tested 2013-2026 history; all dates are development/exploratory for this post-selected replacement.

## Running matrix and evidence identities
- `tmux: ml4t-premia-jp225-replace`, one native year/trial at a time to protect a memory-constrained VPS.
- Frozen plan: `docs/plans/mechanicalpremia-nikkei-replaces-dax-2013-2026-v1.md`.
- Current progress and failures: `run_log/research_sessions/mechanicalpremia-nikkei-replaces-dax-2013-2026-v1/batch_state.json`.
- Detailed append-only log: `run_log/research_sessions/mechanicalpremia-nikkei-replaces-dax-2013-2026-v1/batch_log.jsonl`.
- Fill/trade/equity/summary each cell: `run_log/research_sessions/mechanicalpremia-nikkei-replaces-dax-2013-2026-v1/yearly_native/year=YYYY/<trial>/cost_<multiple>x/`.
- Read-only paired comparisons: `uv run python -m scripts.compare_mechanicalpremia_jp225_vs_de30_v1`.
- Full 84-native-cell audit after completion: `uv run python -m scripts.audit_mechanicalpremia_jp225_substitution_v1`.
- No unrelated dirty files edited or staged; no commit or push.
