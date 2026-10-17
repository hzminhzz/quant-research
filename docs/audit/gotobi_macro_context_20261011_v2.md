# Gotobi non-price context MVP — 2020–2025 retrospective

**Decision: NOT APPROVED.** Yield series are retrospective vendor snapshots.
Three-day availability lag is hypothetical, not authenticated vintages.
The LSE announcement archive dates are backfilled and cannot qualify as PIT model inputs.

## Source, method and data integrity
- Original native trades: 370 dates, only 2020–2025.
- Delayed US10Y/JP10Y coverage: 370/370 = 100.0%.
- Nonprice calendar flags: month-end 62, rolled nominal 114.
- Historical central bank archive: 100 records; 99 created after the event.
- LSE yields are daily retrospective values. For hypothetical as-of joins, add 3 UTC calendar days after observation date; as-of backward only.
- Calendar uses author Gotobi 5,10,15,20,25,month-last rollback, once per date.

## Single-feature diagnostics, HAC5, Holm3

| Predictor | N | HAC slope (pips/unit) | HAC p | Holm3 p |
|---|---:|---:|---:|---:|
| spread_10y | 370 | -2.062 | 0.1119 | 0.2237 |
| month_end | 370 | -0.401 | 0.9333 | 0.9333 |
| rolled | 370 | -5.828 | 0.0653 | 0.1959 |

These are associations, not identified causes. Pooled inference is confounded by the severe 2020–2025 regime shift.
Historical policy-event proximity is EX POST ONLY. It did NOT enter model fitting or trade decisions.

## Native ml4t.backtest Engine — chronological annual models

Fit train-only StandardScaler + Ridge(alpha=10) on preceding calendar years,
starting training 2020–2022. Predict 2023, then retrain including 2023
for 2024; continue for 2025. Trade if predicted net pips > 0.
All arms use same complete macro-feature-eligible event dates.
Execution at 03:00 OPEN, exit 09:56 OPEN, cost 0.5pip each side.

| Strategy | Trades | 2023-25 net USD | Flat-inclusive Sharpe |
|---|---:|---:|---:|
| Gotobi always-long | 185 | -300.62 | -1.056 |
| Calendar-only Ridge | 148 | -133.32 | -0.538 |
| Calendar + delayed US–JP spread Ridge | 147 | -133.77 | -0.540 |

- Macro increment versus calendar model: **-0.45 USD** over 2023–2025.
- Macro model 2024–2025: **-65.51 USD**, calendar comparator **-65.06 USD**.

| Year | Calendar-only USD | Calendar + yield USD |
|---|---:|---:|
| 2023 | -68.26 | -68.26 |
| 2024 | -38.38 | -38.38 |
| 2025 | -26.68 | -27.13 |

## Cost and identification limits

| Round trip pips | Always long USD | Calendar model USD | Calendar+yield USD |
|---|---:|---:|---:|
| 1.0 | -300.62 | -133.32 | -133.77 |
| 1.5 | -363.64 | -183.98 | -184.11 |
| 2.0 | -426.67 | -234.65 | -234.45 |

- The entire 2020–2025 history was previously observed in other Gotobi programs; these fold results are retrospective, NOT true OOS.
- Macro series do not include historically verifiable first-publication and revision vintages. Added lag alone does not solve this.
- 99/100 LSE interest-rate decision event records were archived after their event; policy-calendar predictor BLOCKED pending independent release calendars.
- Native prices use LSE one-minute spot proxy and hypothetical 1/1.5/2pip all-in cost; broker fills not verified.
- The calendar records date knowledge but no actual corporate settlement flow measurement.
- No protected September–October2026 holdout used, no live orders, no Git commit or push.

## Reproduce
- Spec `config/research_sessions/gotobi_macro_context_20261011_v2.yaml`
- Source copies and hashes: `data/processed/gotobi_macro_context_20261011_v1/source_manifest.json`
- Runner `scripts/run_gotobi_macro_context_20261011_v2.py`
- Evidence `run_log/gotobi_macro_context_20261011_v2/T*/result.json`
- Test signals `run_log/gotobi_macro_context_20261011_v2/walkforward_predictions.parquet`
- Native execution `run_log/gotobi_macro_context_20261011_v2/runs/*`

**Final: INCONCLUSIVE for deployable macro edge; model not qualified.**
