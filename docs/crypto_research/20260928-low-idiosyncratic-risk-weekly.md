# Crypto Research Run — Weekly Low-Idiosyncratic-Risk

## Conclusion

**REJECT.** The pre-registered development gate failed before any 2024–2025 OOS portfolio result was observed. The canonical 720h residual-variance signal had mean rank IC 0.0861 with HAC p=0.0031, but its pre-registered low-minus-high weekly spread was -1.30%, and the 336h/1440h neighboring windows were negative as well. The OOS sample remains unconsumed for this hypothesis.

## Source

- *The pricing of jump and diffusive risks in the cross-section of cryptocurrency returns* (2023)
- https://ideas.repec.org/a/eee/empfin/v74y2023ics0927539823000786.html

The source motivates a low-idiosyncratic-risk anomaly. This implementation is deliberately simpler: hourly OHLCV residual variance rather than a high-frequency jump/diffusive decomposition.

## Hypothesis / Economic Mechanism

Lower recent idiosyncratic return variance should predict higher subsequent weekly returns because limits to arbitrage may allow a low-idiosyncratic-risk anomaly to persist in crypto.

## Research Archetype

Cross-sectional factor.

## Pre-Registered Specification

- Estimation windows: 336h / **720h canonical** / 1440h.
- Market factor: equal-weight hourly return across contemporaneously available panel assets.
- Signal: negative rolling residual variance from var(asset) - cov(asset, market)^2 / var(market), using only completed prior-hour information.
- Universe: point-in-time assets with exact hourly history; top 80% by lagged trailing 30-day close×volume; minimum 8 assets.
- Rebalance: Monday 00:00 UTC, current-open execution.
- Portfolio: equal-weight long lowest-idiosyncratic-risk tercile / short highest-idiosyncratic-risk tercile, 0.5 gross each side.
- Development: 2021-01-01 through 2023-12-31.
- OOS: 2024-01-01 through 2025-12-31.
- Gate: canonical mean rank IC >= 0.02, HAC p < 0.05, and positive low-minus-high subsequent-week return.

## Universe Construction

Eligibility is causal. Rolling liquidity/history statistics are lagged one hour and exact-hour continuity is required. The raw panel contains 19 Binance USDT perpetuals. Two known non-hourly XRP gaps are excluded automatically when exact history is unavailable.

## Data

- Path: `/home/quant/dev/quant/ml4t-data/data/crypto/market/perps_1h.parquet`
- Rows: 866,868
- Symbols: 19
- Coverage: 2020-01-01 through 2025-12-31
- SHA256: `f35452fab6b9a32ebc7e773162575ecf582e62ed5cdfaab200f6808060f5f6b8`
- Duplicate symbol/timestamps: 0
- OHLC failures: 0
- Non-hourly symbol gaps: 2

## ML4T Engineer Usage

No catalog sweep was used. The factor was implemented directly from the pre-registered residual-variance mechanism with grouped, lagged panel operations. No feature selection or learned preprocessing was used.

## Signal Diagnostics

| Window | Mean IC | HAC p | Low-minus-high weekly spread |
|---:|---:|---:|---:|
| 336h | 0.0908 | 0.0028 | -0.98% |
| **720h** | **0.0861** | **0.0031** | **-1.30%** |
| 1440h | 0.0803 | 0.0056 | -1.53% |

Canonical quintile mean weekly returns from lowest signal to highest signal were approximately 4.27%, 0.89%, 1.22%, 1.61%, 1.76%. This fails the required economic ordering even though the average rank IC is positive.

## Methodology

All residual-variance inputs are lagged one hour. Cross-sectional liquidity ranks are calculated only at each contemporaneous timestamp. Development labels do not cross into the pre-registered OOS period. No OOS backtest is run unless the fixed development gate passes.

## Results

Development gate: **FAIL**.

OOS consumed: **No**.

Net OOS Sharpe / drawdown / cost sensitivity: **N/A**, because consuming OOS after the failed development gate would violate the pre-registration.

## Asset Breadth / Contribution

Mean eligible assets in the canonical development sample: 13.98. No OOS asset contribution analysis was performed.

## Robustness

The two pre-registered neighboring estimation windows failed the same spread-direction check. This is sufficient to reject without consuming OOS.

## Failure Analysis

The anomaly does not translate into the required portfolio ordering in the development period. The direction of the tercile spread is wrong across all three pre-registered estimation windows. Further tuning of windows or thresholds after this observation would count as a new hypothesis/trial and is not permitted inside this candidate.

## Multiple-Testing Audit

- Previous crypto parameter trials: 21
- New trials: 3
- Cumulative: **24**
- DSR/PBO: N/A because the development gate stopped the experiment before OOS portfolio evaluation.

## Decision

**REJECT**

## Reproduction

`uv run --with scipy python3 -c "import sys; from scripts import run_crypto_low_idio_variance as m; sys.argv=['research','--data','/home/quant/dev/quant/ml4t-data/data/crypto/market/perps_1h.parquet']; raise SystemExit(m.main())"`

## Provenance

- Runner SHA256: `9fb69530282a028371e6e081a651006f7c3e1484ff79cc6a23c63a4a02697d57`
- Data SHA256: `f35452fab6b9a32ebc7e773162575ecf582e62ed5cdfaab200f6808060f5f6b8`
- Starting branch HEAD: `273ecd60f76ce315d577ddb5de62fe50894d656f`
