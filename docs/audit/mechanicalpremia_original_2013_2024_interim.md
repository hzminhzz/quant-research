# Mechanical Premia original-universe extension — interim research evidence

Session: `mechanicalpremia-original-four-2013-2024-v1`
Frozen before the first extended trial. Classification: EXPLORATORY / NOT_APPROVED.
User objective: extend 2013–2024 and restore article's original four indices.

## Source universe and data
- H1 breakout: US500 (`index_minute_ES`), US100 (`index_minute_NQ`), DE30 (`index_minute_DAX`).
- D1 mean reversion: all above and EU50 (`index_minute_EUSIDXEUR`).
- All Dukascopy daily-Hive Parquet in `/home/quant/dev/quant/ml4t-data/.data/store`.
- ES/NQ January 2013; DE30 September 30 2013; EU50 June 2 2014. Ignore protected 2025 onward.
- Acceptance audit: `docs/audit/mechanicalpremia_data_2013_2024_v1.json` (3,583 accepted US500 daily files, 3,583 US100, 3,331 DE30, 2,712 EU50; significant short/stale or zero-volume days).
- Historic acceptance and bid-only quote semantics do NOT establish correct ask/spread, lot multiplier, day-boundary, currency conversion or financing. EU50's >=600 rows per day selection is a frozen adaptation, not proven MT5 matching.

## Executable implementation
- `scripts/mechanicalpremia_source_universe_2013_v1.py`: native ml4t-engineer ATR, BB, EMA and causal multi-sleeve signal/order logic.
- `scripts/run_mechanicalpremia_extended_2013.py`: one-year native ml4t.backtest.Engine, marked daily-equity risk metrics, trade and fill artifacts.
- `scripts/batch_mechanicalpremia_extended_2013.py`: deterministic, serial bounded-RAM 72-cell test matrix (4 baseline source/equal/standalone trials + two cost stresses times twelve years).
- `tests/test_mechanicalpremia_source_universe_2013.py` and earlier native suite: 8/8 passed. EU50 cannot enter H1; seven individual source sleeves supported.
- Native simulation uses SYNTHETIC unit positions and price-unit equity: mixing USD and EUR index PnL without FX conversion is NOT executable USD PnL. Every year resets account; cannot claim continuous twelve-year compounded Sharpe.
- Source D1 has NO hard stop; H1 protective stop has the already documented first-minute protection gap. Correct broker economic validation therefore remains blocked.

## Interim development results (not OOS; 2024 was already observed)
| Year | H1 source 3 | D1 source 4 | Equal-risk 7 | Source-risk 7 |
| --- | ---: | ---: | ---: | ---: |
| 2013 | -1.91% | +5.36% | +1.68% | +2.97% |
| 2014 | -4.43% | +4.30% | +0.32% | +1.29% |
| 2015 | -1.64% | -0.81% | -1.24% | -1.00% |

These are annual native-engine synthetic account returns under assumed 1 bp per-side commission and 2 bp per-side slippage, *excluding actual ASK spread and CFD overnight financing*.
The 2013 source risk survives 2x these proxy costs at +0.83%; 2014 source risk falls from +1.29% to -1.38% at 2x costs.
No inference about 2016–2024 or total risk-adjusted edge until complete verified runs.

## Job state
- tmux job: `ml4t-mechanicalpremia-source2013`
- ledger: `run_log/research_sessions/mechanicalpremia-original-four-2013-2024-v1/batch_log.jsonl`
- counter: `run_log/research_sessions/mechanicalpremia-original-four-2013-2024-v1/batch_state.json`
- annual native outputs: `run_log/research_sessions/mechanicalpremia-original-four-2013-2024-v1/yearly_native/year=YYYY/<trial>/cost_<rate>x/`
- This document is an interim snapshot; consult the real counter/log to determine whether work remains running. No task should be marked scientifically qualified solely because an annual engine run completed.
- No live orders, no protected 2025 score, no commit/push of unrelated dirty work.
