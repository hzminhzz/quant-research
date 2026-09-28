# Crypto Research Run — Paper Multi-Horizon EMA TSMOM

## Conclusion

**REJECT.** A direct, pre-registered adaptation of the 2026 eight-major multi-horizon EMA time-series momentum methodology failed badly in development after realistic turnover costs. The canonical `alpha=1` variant produced **-0.10 net Sharpe**, -34.7% total return, and -60.2% max drawdown during 2022–2023. All three alpha variants lost money, so 2024–2025 OOS was not consumed.

## Source

Adedeji Daniel Gbadebo, *Momentum Trading in Cryptocurrencies: A Comparative Study of Time-Series and Cross-Sectional Strategies*, Buhalterines apskaitos teorija ir praktika 33 (2026), DOI 10.15388/batp.2026.1.

## Hypothesis / Economic Mechanism

A volatility-normalized multi-horizon EMA trend signal should capture persistent directional behavior while bounded nonlinear response and cross-asset diversification control risk.

## Research Archetype

Time-series rule.

## Pre-Registered Specification

- Eight paper assets: BTC, ETH, LTC, XRP, BNB, ADA, DOGE, SOL perpetuals.
- EMA pairs: 8/24, 16/48, 32/96 days.
- 30-day rolling normalization.
- Secondary smoothing uses each pair's long EMA horizon.
- `tanh(alpha*z)` bounded response with alpha 0.5 / **1.0 canonical** / 2.0.
- Equal-weight across horizons and assets; clipped composite exposure.
- Signal from close at t applied no earlier than t+1 return.
- 10 bps one-way base turnover cost.
- Development 2022–2023; OOS 2024–2025 only after a fixed development gate.

## Data

Partitioned Binance USD-M 1h archive, aggregated to complete UTC days. All eight source assets are available in the partitioned archive; occasional historical hourly gaps in LTC/XRP/SOL are handled by requiring complete days and common dates.

Dataset manifest SHA256: `261a29b1df22e242cba2fd1a68c928f2ba3233f2134ad0d00ea87f59163dca81`.

## ML4T Engineer Usage

No catalog sweep or learned preprocessing. The source equations were implemented directly with causal EMA and rolling-volatility calculations.

## Results

| alpha | Net Sharpe | Total return | Max DD |
|---:|---:|---:|---:|
| 0.5 | -0.161 | -38.8% | -62.8% |
| **1.0** | **-0.102** | **-34.7%** | **-60.2%** |
| 2.0 | -0.129 | -36.7% | -61.2% |

Canonical yearly split: 2022 +19.7% / 0.61 Sharpe, then 2023 -45.4% / -2.14 Sharpe. BNB was the largest negative raw contribution in the canonical development portfolio.

## Robustness

Both pre-registered response-sensitivity neighbors failed in the same direction. This is sufficient to reject without touching OOS.

## Failure Analysis

The source reports gross historical results; this replication adds explicit turnover friction and uses perpetuals. More importantly, failure is not a marginal cost effect: the 2023 directional regime is strongly adverse across all pre-registered alpha variants. Post-hoc changes to EMA pairs or alpha would be new trials, not fixes to this candidate.

## Multiple-Testing Audit

Previous trials 77; new 3; cumulative **80**. DSR/PBO are N/A because OOS was not consumed.

## Decision

**REJECT**

## Reproduction

`uv run python3 -m scripts.run_crypto_paper_ema_tsmom --data ../../../dev/quant/ml4t-data/.data/store/crypto_futures_ohlcv_1h_BINANCE_UM_PERP`

## Provenance

- Runner SHA256: `6ebd888f7fc22f4136ba7d390d4562e3cb24fb0a84c82af123fc3a14cd407894`
- Dataset manifest SHA256: `261a29b1df22e242cba2fd1a68c928f2ba3233f2134ad0d00ea87f59163dca81`
