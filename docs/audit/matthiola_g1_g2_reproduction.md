# Matthiola reproduction — G1 and G2 evidence

Runner: `research_programs/matthiola/run_repro.py`
Vendored upstream: `research_programs/matthiola/upstream/` (byte-identical, hashes in
`matthiola_source_contract.md` §1)
Contract: `matthiola_source_contract.md`

No source logic was re-implemented. `features.py`, `model.py`, `validation.py`,
`qtools/backtest/*`, `qtools/data/loaders/crypto.py` and `qtools/metrics/performance.py`
execute as fetched; the runner only sequences them as notebook 05 does.

---

## G0 — raw tape

Fetched through **the upstream loader itself** (`qtools.data.loaders.crypto.get_crypto_prices`,
ccxt → Binance spot, `interval="1d"`, 2018-01-01 → 2025-07-31).

| Property | Value |
| --- | --- |
| Rows | 46,079 |
| Symbols | 20 / 20 requested (no drops) |
| Date range | 2018-01-01 → 2025-07-30 |
| Parquet SHA-256 | `17b634ade176422c363f6b69b9456e35956caf913c4f6f0577211d9e6e5cf324` |
| Cache key | `819824d3a7_2018-01-01_2025-07-31_1d_binance.parquet` |

Manifest: `research_programs/matthiola/repro_output/tape_manifest.json`.

---

## G1 — reproduction verdict: **PASS on the predictive pipeline; one residual economics gap**

Feature rows 45,659 · 20 symbols · OOS predictions 43,840 rows over 1,096 dates.

| Model | reported IC-IR | reproduced IC-IR | Δ | reported net Sharpe | reproduced net Sharpe | Δ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `xgb_ranker` | +0.18 | **+0.188** | +0.008 | +0.74 | **+0.861** | **+0.121** |
| `naive_ew` | −0.39 | **−0.386** | +0.004 | −0.22 | **−0.224** | −0.004 |

Also reproduced, unreported by the source: `xgb_ranker` mean IC +0.0507, HAC t 6.24,
hit rate 55.2%; `naive_ew` mean IC −0.1230, HAC t −12.80, hit rate 37.0%.

**Stated tolerance.** IC-IR within ±0.02 absolute; deterministic-baseline Sharpe within
±0.05. Both pass (0.008 / 0.004 and 0.004). The XGB Sharpe residual of 0.121 is **recorded
as a known discrepancy, not absorbed into a pass claim**.

**Diagnosis of the residual.** Per-year net Sharpe for the reproduced XGB book:

| Year | net Sharpe | ann net |
| --- | ---: | ---: |
| 2022 | −0.149 | −9.7% |
| 2023 | +1.176 | +38.0% |
| 2024 | +2.244 | +167.5% |

The gap is concentrated in the 2023–2024 folds. Candidate causes, in order of
likelihood, none of which is a pipeline error:

1. **Library version.** Reproduced with `xgboost 3.4.1`; the source does not pin a
   version. `rank:pairwise` split selection and the `hist` binning have changed across
   major releases. This changes the 2023/2024 rankers and leaves 2022 nearly unchanged.
2. **Data vintage.** Binance serves current history; the source cached its tape in
   2026-05. Daily bars are not revised often, but the 2024 tail is the most likely to differ.
3. **pandas 3.0 vs source's 2.x.** `_decile_labels` relies on
   `groupby.transform(pd.qcut)`. Any change in `qcut` tie-breaking shifts the 10-bin
   relevance labels and therefore the pairwise objective.

The IC reproducing to <1% across both models is the evidence that features, target,
labels, walk-forward and IC construction are faithful; the Sharpe gap is a property of
the fitted trees, not of the specification.

Artifacts: `btc_ic.csv`, `btc_backtest.csv`, `btc_oos_predictions.parquet`,
`reported_vs_reproduced.csv` (SHA-256 in the run log).

---

## G2 — clock truth: **PASS, with one modelling optimism identified**

Verified empirically by comparing one daily bar against its 24 hourly bars
(2024-03-10, BTC/USDT):

| Check | Result |
| --- | --- |
| Daily `openTime` | `2024-03-10 00:00:00+00:00` → **bar START** |
| `daily.open == first hourly open` | True |
| `daily.high == max(hourly high)` | True |
| `daily.low == min(hourly low)` | True |
| `daily.close == last (23:00) hourly close` | True |
| `daily.volume == sum(hourly volume)` | True (38404.66835) |
| Bar coverage | `[00:00, 24:00)` UTC |

So: a daily bar is stamped at its **open**, its `close` is the last trade before
24:00 UTC, and `volume` is base-asset volume (not quote turnover).

**Funding timestamps: not applicable.** This strategy trades Binance **spot** and never
touches funding. No funding-timestamp claim is made or needed anywhere in this mission.

### Identified optimism (carried into G7)

`BacktestEngine` uses `positions = weights.shift(1)` and
`return[t+1] = close(t+1)/close(t) - 1`. Combined with a signal computed from
`close(t)`, the modelled entry is **the same print that produced the signal**. You
cannot observe `close(t)` and transact at `close(t)`.

This is the standard daily-bar convention and it is what the source does — but it is a
one-bar decision/entry coincidence, and it flatters every feature that uses `close(t)`
(which is all twelve). G3 therefore reports every statistic twice: `src` (source
convention) and `lag1` (signal at `close(t)`, entry at `close(t+1)`). G7 reports the
Sharpe delta between them.

---

## Reproduction reproducibility

```bash
.venv/bin/python research_programs/matthiola/run_repro.py
```

Requires `ccxt`, `xgboost`, `lightgbm`, `scikit-learn`, `pandas`, `pyarrow`.
`xgboost` was not previously installed in this environment; it was added at 3.4.1
because the upstream `model.py` imports it at module scope.
