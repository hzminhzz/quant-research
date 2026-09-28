# Low-anchor reversal weekly — REJECT

## Conclusion

**REJECT.** The preregistered 30-day formation-low anchor signal had strong development rank diagnostics but failed the fixed portfolio gate. Net development Sharpe was **0.4045** after 10 bps one-way costs. The 2024–2025 exploratory OOS period was not consumed.

## Source

Nakagawa & Sakemoto, *New behaviorally-based cross-sectional reversal portfolios in the cryptocurrency market and market uncertainty*, Finance Research Letters 85 (2025) 107800. DOI: 10.1016/j.frl.2025.107800; SSRN 5001299.

## Hypothesis / mechanism

Assets still trading near a salient recent formation-period low may remain temporarily underpriced because investors anchor on the low; assets far above the low may already have realized the rebound.

## Archetype

Cross-sectional behavioral factor.

## Pre-registration

Manifest: `run_log/crypto_research/runs/20260928-low-anchor-reversal-weekly-manifest.json`

- Lookbacks: 14 / 30 / 60 days; canonical = 30 days.
- Universe: each Monday, top 50 contemporaneously eligible Binance USD-M USDT perpetuals by lagged trailing-30-day quote volume.
- Signal: negative distance of prior completed-day close from rolling formation low.
- Portfolio: equal-weight, market-neutral top/bottom quintiles.
- Execution: Monday open to next Monday open.
- Base cost: 10 bps one-way.
- Development: 2022–2023.
- OOS: 2024–2025, sealed unless development gate passes.

## Data / point-in-time handling

637 symbols were available in the broad store. Signals and liquidity use only prior completed observations; weekly ranking is contemporaneous; next-week returns are labels only. No scaler/model fitting is used.

## Signal diagnostics

| Lookback | Mean rank IC | HAC t | HAC p | Top-minus-bottom weekly spread |
|---:|---:|---:|---:|---:|
| 14d | 0.0951 | 4.245 | 2.19e-05 | 0.154% |
| 30d | 0.1032 | 4.900 | 9.57e-07 | 0.501% |
| 60d | 0.1124 | 5.887 | 3.93e-09 | 0.880% |

The signal-level relation is real enough to merit future independent hypotheses, but this candidate must obey its fixed canonical parameter.

## Development results

| Lookback | Net Sharpe | Total return | Max DD | Turnover |
|---:|---:|---:|---:|---:|
| 14d | -0.001 | -4.76% | -35.97% | 137.7 |
| **30d canonical** | **0.404** | **+14.05%** | **-21.52%** | **105.1** |
| 60d | 1.066 | +47.00% | -16.63% | 81.6 |

Canonical year split: 2022 +32.83% (Sharpe 1.30), 2023 -14.14% (Sharpe -0.65).

## Failure analysis

The 30-day canonical signal failed the preregistered requirement of Sharpe > 0.70. The 60-day neighbor looked materially better, but selecting it now would be post-hoc tuning. It remains evidence only, not a promoted strategy. OOS stays untouched for this candidate.

## Multiple-testing audit

Trials before candidate: 148. New preregistered parameter trials: 3. Cumulative trials: **151**. DSR/PBO were not computed because OOS was not consumed and the candidate failed before qualification.

## Decision

**REJECT.** No sealed confirmation or deployment action.

## Reproduction

`uv run python scripts/run_crypto_low_anchor_reversal.py --root /home/quant/dev/quant/ml4t-data/.data/store/crypto_futures_ohlcv_1h_BINANCE_UM_PERP`

## Provenance

Manifest commit: `e9a0ce3`. Result produced on 2026-09-28.
