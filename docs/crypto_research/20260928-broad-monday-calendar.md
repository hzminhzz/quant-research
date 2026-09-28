# Crypto Research Run - Broad Monday Calendar Premium

## Conclusion

**REJECT.** The preregistered broad Monday premium failed in development. Net Monday Sharpe was **-0.725**, total return **-45.43%**, and max drawdown **-50.71%** across 2022-2023 at 10 bps one-way cost. Exploratory 2024-2025 OOS was not consumed.

## Source

Primary source: *Calendar anomalies and market volatility in selected cryptocurrencies* (2023), DOI 10.1080/23311975.2023.2171992. Supporting mechanism source: Hansen, Kim, and Kimbrough, *Periodicity in Cryptocurrency Volatility and Liquidity*, Journal of Financial Econometrics 22(1), 2024, DOI 10.1093/jjfinec/nbac034.

## Hypothesis / Mechanism

Prior literature reports recurring day-of-week patterns in cryptocurrency returns, volatility, and volume. The preregistered hypothesis was that weekly participation, funding, and algorithmic-trading rhythms would leave a positive Monday open-to-Tuesday-open premium in a broad liquid perpetual basket.

## Archetype

Calendar time-series basket.

## Pre-Registration

- 1h Binance USD-M USDT perpetual bars aggregated to complete UTC days.
- At every candidate day, require 30 complete prior days.
- Select the point-in-time top 30 by lagged trailing-30-day quote volume.
- Equal-weight long basket.
- Enter at selected day open and exit at next UTC day open.
- Canonical day: Monday.
- Fixed placebo variants: Sunday and Tuesday.
- Base cost: 10 bps one way, charged on entry and exit.
- Development: 2022-2023.
- Exploratory OOS: 2024-2025 only if development gate passes.
- Three preregistered weekday variants count as three new statistical trials.

## Universe

The development loader observed **262** USDT perpetual symbols. The basket at each date was selected only from lagged liquidity and sufficient causal history; strategy returns never determined eligibility.

## Data

Existing Binance USD-M 1h market-data store. Daily bars required all 24 hourly observations. No sealed confirmation data was read.

## ML4T Engineer Usage

No catalog sweep was used. This rule only required canonical OHLCV aggregation and a lagged rolling liquidity measure, so adding unrelated Engineer indicators would have violated the hypothesis-first policy.

## Signal Diagnostics

The economic diagnostic was a calendar placebo comparison rather than cross-sectional IC: Monday needed to produce positive net returns and exceed both adjacent Sunday and Tuesday mean returns.

Development mean net weekly observation:
- Sunday: **-0.347%**
- Monday: **-0.470%**
- Tuesday: **+0.138%**

Monday therefore did not exhibit the preregistered premium.

## Methodology

Liquidity was computed from the 30 completed days before entry. Entry and exit prices were consecutive UTC opens, so the strategy used no same-bar future information. Each trade paid two one-way cost legs.

## Results

| Day | Net Sharpe | Total return | Max DD |
| --- | ---: | ---: | ---: |
| Sunday | -0.743 | -34.59% | -49.87% |
| **Monday** | **-0.725** | **-45.43%** | **-50.71%** |
| Tuesday | 0.272 | +7.55% | -41.72% |

Monday was negative in both development years: **-27.51%** in 2022 and **-24.72%** in 2023.

## Breadth / Contribution

The strategy was tested as a broad top-30 liquid basket rather than on BTC alone, so the rejection is not a single-asset artifact.

## Robustness

The candidate failed before OOS. Sunday and Tuesday placebo variants were fully preregistered. Tuesday was materially better than Monday, which directly contradicts the canonical Monday-specific hypothesis for this universe and period.

## Failure Analysis

The published Monday anomaly did not transfer to this later, broad Binance perpetual universe under conservative trading costs. The result could reflect regime change, different market structure, spot-versus-perpetual differences, or the original anomaly being sample-specific. These possibilities are not grounds for post-hoc day selection.

## Multiple-Testing Audit

This cycle adds **3** preregistered weekday trials, increasing the reconciled count from **165 to 168**. DSR/PBO are not calculated because the candidate failed the development gate before exploratory OOS.

## Decision

**REJECT**

## Reproduction

`uv run python scripts/run_crypto_monday_calendar.py --root /home/quant/dev/quant/ml4t-data/.data/store/crypto_futures_ohlcv_1h_BINANCE_UM_PERP`

## Provenance

The manifest was persisted before execution at `run_log/crypto_research/runs/20260928-broad-monday-calendar-manifest.json`.
