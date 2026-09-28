# Crypto Research Run — Relative Signed Jump Weekly

## Conclusion

**REJECT.** The source-motivated relative signed jump factor showed genuine positive development diagnostics, but the tradable weekly portfolio did not clear the pre-registered development gate. The canonical 7-day signal produced **0.519 net Sharpe**, +18.8% total return, and -27.2% max drawdown during 2022–2023; the 3-day neighbor lost money. The 2024–2025 OOS sample was therefore not consumed.

## Source

Zehua Zhang and Ran Zhao, *Good volatility, bad volatility, and the cross section of cryptocurrency returns*, International Review of Financial Analysis 89 (2023), DOI 10.1016/j.irfa.2023.102712.

## Hypothesis / Economic Mechanism

Lower lagged relative signed jump variation should predict higher subsequent weekly crypto returns. The mechanism separates upside and downside intraday semivariance and tests whether asymmetric jump risk is priced cross-sectionally.

## Research Archetype

Cross-sectional factor.

## Pre-Registered Specification

- Binance USD-M USDT perpetuals listed by 2021-12-31.
- Monday universe: top 50 contracts by lagged trailing-30-day quote volume.
- Daily RSJ from positive/negative hourly log-return semivariances.
- Signal: negative lagged rolling mean RSJ over 3 / **7 canonical** / 14 completed days.
- Weekly long lowest-RSJ quintile / short highest-RSJ quintile, 0.5 gross each side.
- 10 bps one-way base cost.
- Development: 2022–2023.
- Exploratory OOS: 2024–2025, unlocked only after the development gate.
- Gate: canonical mean rank IC >0.02, positive spread, net Sharpe >0.70, and at least 2/3 lookbacks profitable.

## Universe Construction

The universe is point-in-time. Listing eligibility is fixed from observed first timestamps, and liquidity ranking uses only lagged quote volume. Each Monday requires sufficient causal history. Delisted names remain eligible until their data end.

## Data

Partitioned Binance USD-M 1h archive at `ml4t-data/.data/store/crypto_futures_ohlcv_1h_BINANCE_UM_PERP`.

- Eligible symbols: **139**
- Dataset manifest SHA256: `261a29b1df22e242cba2fd1a68c928f2ba3233f2134ad0d00ea87f59163dca81`

## ML4T Engineer Usage

No catalog sweep. RSJ was implemented directly from the economic hypothesis using grouped lagged transformations. No learned preprocessing or full-sample normalization was used.

## Signal Diagnostics

| Lookback | Mean rank IC | IC IR | Top-minus-bottom next-week return |
|---:|---:|---:|---:|
| 3d | 0.0531 | 0.297 | +0.36% |
| **7d** | **0.0636** | **0.348** | **+0.73%** |
| 14d | 0.0608 | 0.320 | +0.75% |

The signal relationship was directionally strong enough to merit the portfolio gate, but predictive rank information did not translate into sufficiently robust net strategy Sharpe.

## Results

| Lookback | Net Sharpe | Total return | Max DD |
|---:|---:|---:|---:|
| 3d | 0.055 | -1.7% | -25.2% |
| **7d** | **0.519** | **+18.8%** | **-27.2%** |
| 14d | 0.612 | +24.6% | -27.1% |

Canonical yearly results: 2022 +16.3% / 0.74 Sharpe; 2023 +2.15% / 0.21 Sharpe.

## Robustness

The two pre-registered neighboring lookbacks were tested. The shortest variant was unprofitable, so parameter stability was insufficient for the development gate.

## Failure Analysis

The factor itself is predictive in rank terms, but the edge is too weak after portfolio construction and realistic weekly turnover costs. Raising Sharpe through post-hoc lookback selection would violate the pre-registration.

## Multiple-Testing Audit

Previous parameter trials: 74. New: 3. Cumulative: **77**. DSR/PBO are not applicable because the sealed exploratory OOS was not consumed.

## Decision

**REJECT**

## Reproduction

`uv run python3 -m scripts.run_crypto_rsj_weekly --root /home/quant/dev/quant/ml4t-data/.data/store/crypto_futures_ohlcv_1h_BINANCE_UM_PERP`

## Provenance

- Runner SHA256: `ad9fe71b98e971e0a2444754ae31f000f3d7cabc07548fa92f583a20a5c8e179`
- Dataset manifest SHA256: `261a29b1df22e242cba2fd1a68c928f2ba3233f2134ad0d00ea87f59163dca81`
