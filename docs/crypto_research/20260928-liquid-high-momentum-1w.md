# Crypto Research Run — Liquid Crypto Distance-to-1-Week-High

## Conclusion

**REJECT.** The source-inspired high-momentum factor passed the pre-registered 2021–2023 development diagnostic gate, with weekly rank IC **0.0748** (HAC t **2.80**, p **0.0051**) and a positive top-minus-bottom next-week spread. It then failed the untouched 2024–2025 portfolio OOS: canonical 168h net Sharpe **-0.19**, total return **-17.1%**, and max drawdown **-46.6%** at 3 bps one-way friction. The edge was slightly positive in 2024 but reversed materially in 2025. Neighbor windows, higher costs, BTC/ETH exclusion, strongest-asset removal, and one-hour delayed execution do not rescue the hypothesis.

## Source

Milan Fičura, *Impact of size and volume on cryptocurrency momentum and reversal*, FFA Working Papers 5.003 (2023), SSRN DOI 10.2139/ssrn.4378429.

Source URL: https://ideas.repec.org/p/prg/jnlwps/v5y2023id5.003.html

The source reports that large/liquid cryptocurrencies show weekly momentum and that distance of the previous-week close from the k-week high is a stronger predictor than conventional momentum. The supplied Binance panel lacks historical market capitalization, so this run uses a causal trailing-dollar-volume filter inside a curated liquid-perpetual universe rather than claiming an exact replication.

## Hypothesis / Economic Mechanism

Among liquid Binance perpetuals, assets whose prior close sits nearer their trailing one-week high should outperform peers during the next week. The proposed mechanism is short-horizon continuation from gradual speculative-capital rotation / underreaction, with liquidity reducing the microcap reversal effect documented in broader crypto universes.

## Research Archetype

Cross-sectional factor / relative-strength.

## Pre-Registered Specification

Pre-registration commit: `812b82e0969e8422cec3ad4a5c87849b36255bb1`.

| Item | Fixed specification |
|---|---|
| Canonical lookback | 168 hours |
| Neighbor trials | 336h, 672h |
| Signal | prior close / max prior hourly close over lookback − 1 |
| Rebalance | Monday 00:00 UTC |
| Execution | current Monday 00:00 open; signal uses data only through prior hourly bar |
| Universe | 8 weeks continuous history, then top 70% by lagged 168h mean(close×volume) |
| Cross-section minimum | 8 |
| Portfolio | long top quintile 0.5 gross / short bottom quintile 0.5 gross |
| Weighting | equal weight inside each side |
| Development | 2021-01-01 through 2023-12-31 |
| Primary OOS | 2024-01-01 through 2025-12-31 |
| Base cost | 3 bps per one-way traded notional |
| Cost stress | 1x / 2x / 3x |
| Planned trials | 3 parameter trials |

The development gate required canonical mean rank IC ≥ 0.02, HAC two-sided p < 0.05, and positive top-minus-bottom forward return. The 2024–2025 portfolio OOS was only constructed after this gate passed.

## Universe Construction

The source panel contains 19 Binance USDT perpetuals. Eligibility is reconstructed independently at each weekly timestamp. An asset must have an exact continuous 8-week hourly history, current execution price, and valid lagged liquidity information. The top 70% by trailing 168h mean `close × volume` is retained.

This panel is curated and is **not** a full survivorship-free historical Binance listing universe. That limits any positive result; it does not explain the negative OOS result.

## Data

Dataset: `/home/quant/dev/quant/ml4t-data/data/crypto/market/perps_1h.parquet`

SHA256: `f35452fab6b9a32ebc7e773162575ecf582e62ed5cdfaab200f6808060f5f6b8`

- Rows: **866,868**
- Symbols: **19**
- Range: 2020-01-01 00:00 UTC to 2025-12-31 23:00 UTC
- Duplicate symbol/timestamp rows: **0**
- OHLC integrity failures: **0**
- Known hourly gaps: **2**, both XRPUSDT in late 2020

Known XRP gaps:
- 2020-11-29 23:00 → 2020-12-01 00:00 UTC
- 2020-12-01 23:00 → 2020-12-05 00:00 UTC

The point-in-time continuity rule automatically excludes weekly observations spanning those gaps.

## ML4T Engineer Usage

No registered Engineer feature exactly represents the paper's “distance from prior close to k-week high” signal. The factor is therefore implemented directly with group-aware Polars using the pre-registered formula rather than approximated with RSI/MACD/ROC or discovered through a feature sweep.

The implementation preserves the Engineer guardrails: data sorted by `(symbol,timestamp)`, lagged per-symbol rolling windows, contemporaneous cross-sectional ranks, and no full-sample normalization.

## Signal Diagnostics

### Development 2021–2023

| Window | Weeks | Mean rank IC | HAC t | HAC p | Top−bottom next-week return |
|---|---:|---:|---:|---:|---:|
| 168h | 156 | **0.0748** | **2.80** | **0.0051** | **+0.887%** |
| 336h | 156 | 0.0750 | 2.47 | 0.0136 | +1.372% |
| 672h | 156 | 0.0600 | 2.03 | 0.0422 | +0.594% |

The development gate therefore passed. Mean eligible cross-section for the canonical factor was about **12.5 assets**.

Quantile means were not perfectly monotonic: canonical Q1–Q5 were approximately 0.50%, 1.96%, 3.12%, 2.00%, 1.72%. This was a warning sign, but monotonicity was not a pre-registered hard gate.

## Methodology

The OOS simulation is sequential and position/cash explicit. At each weekly rebalance, desired dollar notionals are computed from current marked equity. Trades execute at the Monday open after the signal has been formed from previous bars; costs are deducted from cash on each notional change. Quantities are then held unchanged until the next weekly rebalance, with daily marked-to-market equity used for Sharpe.

Funding is not modeled because point-in-time funding cashflows are not present in the OHLCV panel. Market impact is omitted under the user's small-capacity research assumption. Because this candidate failed before those omissions could matter positively, no production/execution claim is made.

## Results

### Canonical 168h factor — primary OOS 2024–2025

| Metric | Result |
|---|---:|
| Net Sharpe | **-0.19** |
| Total return | **-17.1%** |
| Max drawdown | **-46.6%** |
| Sortino | -0.25 |
| Rebalances | 104 |
| Cost drag on initial equity | 3.86% |

### OOS by year

| Year | Net Sharpe | Return | Max DD |
|---|---:|---:|---:|
| 2024 | +0.19 | +1.18% | -23.3% |
| 2025 | **-0.66** | **-19.0%** | -38.6% |

The development signal did not persist through the recent period; the sign deterioration is concentrated in 2025.

### Cost sensitivity

| Cost | Net Sharpe | Total return |
|---|---:|---:|
| 1x = 3 bps | **-0.19** | -17.1% |
| 2x = 6 bps | -0.26 | -20.5% |
| 3x = 9 bps | -0.33 | -23.7% |

The factor is not failing merely because of friction; the underlying portfolio edge is weak/negative.

### Neighbor windows at base cost

| Window | Net Sharpe | Total return |
|---|---:|---:|
| 168h | **-0.19** | -17.1% |
| 336h | +0.21 | +3.8% |
| 672h | -0.03 | -9.0% |

Only the 336h neighbor is weakly positive. There is no robust profitable plateau and no basis for selecting it after observing these results.

## Asset Breadth / Contribution

The canonical result was not rescued by removing its strongest contributor. DOTUSDT was the strongest measured contributor; rerunning without it produced Sharpe **-0.24** and return **-19.5%**.

Excluding BTC and ETH produced Sharpe **-0.33** and return **-24.0%**. The failure is therefore not caused by the majors dominating the cross-section.

## Robustness

| Test | Net Sharpe | Return |
|---|---:|---:|
| Canonical | -0.19 | -17.1% |
| Remove strongest asset (DOT) | -0.24 | -19.5% |
| Exclude BTC + ETH | -0.33 | -24.0% |
| Delay execution 1 hour | -0.21 | -18.3% |

All pre-registered breadth/execution ablations remain negative.

## Failure Analysis

This candidate demonstrates why the mandatory diagnostic gate and separate OOS matter. The factor looked statistically strong in 2021–2023, including positive neighboring-window ICs, but the tradable portfolio failed in 2024–2025. The main failure is temporal instability, especially the 2025 reversal of performance.

The development IC also did not produce clean quantile monotonicity, suggesting that the rank relationship was diffuse rather than concentrated in stable extremes. High turnover then imposes additional friction on an already weak OOS return spread.

## Multiple-Testing Audit

- Previous crypto parameter trials: **3**
- New parameter trials: **3**
- Cumulative parameter trials: **6**
- Current-family base-cost Sharpes: -0.19, +0.21, -0.03
- DSR probability for canonical result: **0.289**
- Haircut Sharpe: **-0.327**
- PBO: **N/A** — only three pre-registered windows; no CPCV winner-selection exercise

The positive 336h neighbor is retained as a failed/weak trial and is not promoted.

## Decision

**REJECT**

The canonical high-momentum factor clears the historical signal screen but fails the untouched portfolio OOS, transaction-cost tests, temporal stability, neighboring-parameter stability, and breadth/execution ablations.

## Reproduction

Manifest:
`run_log/crypto_research/runs/20260928-liquid-high-momentum-1w-manifest.json`

Runner:
`scripts/run_crypto_high_momentum.py`

Focused tests:
`uv run --with pytest --with scipy python3 -m pytest -q tests/test_crypto_high_momentum.py`

## Provenance

- Research branch: `research/crypto-auto`
- Pre-registration commit: `812b82e0969e8422cec3ad4a5c87849b36255bb1`
- Data SHA256: `f35452fab6b9a32ebc7e773162575ecf582e62ed5cdfaab200f6808060f5f6b8`
- Runner SHA256: `2d89488b99ab3eae4eac2923fc9246d8acbe257bfb29a575223aed98ee743ec9`
