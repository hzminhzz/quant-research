# 20260928 BTC Shock Underreaction in Lower-Liquidity Altcoins

## Conclusion

**REJECT.** The beta-adjusted underreaction gap was strongly predictive, but its economic magnitude was smaller than realistic hourly round-trip costs. OOS was not consumed.

## Source

Kurihara & Matsumoto, *Price Transmission from Bitcoin to Altcoins: High-Frequency Evidence and Implications for Trading Strategy*, Asia-Pacific Financial Markets (published 2026-03-10), DOI 10.1007/s10690-026-09589-z.

## Hypothesis / mechanism

BTC leads information transmission and lower-liquidity altcoins respond more slowly. After a large BTC hourly shock, an altcoin whose contemporaneous move is smaller than its lagged-beta-implied BTC response should continue toward that implied move over the next few hours.

## Pre-Registration

- 168h causal rolling beta to BTC, estimated through t-1.
- Shock: |BTC hourly return| >= 1.5x lagged 168h BTC hourly volatility.
- Eligible cohort: Binance USD-M USDT perps listed by 2021-12-31, including later-delisted contracts where data exist.
- At each event: top 100 by lagged trailing-30-day quote volume, then trade the lower-liquidity half.
- Signal: gap = beta_i * BTC_return_t - alt_return_t.
- Horizons: 1h / **2h canonical** / 4h.
- Signal on close t, enter at open t+1; no same-bar fill.
- Base cost: 10 bps one-way.
- Development: 2022-2023; OOS 2024-2025 sealed behind the gate.

## Data

5,784,997 hourly rows, 139 symbols, 2020-01-01 through 2026-01-05. Duplicate (symbol,timestamp) pairs: 0.

## Signal diagnostics

| Horizon | Events | Mean rank IC | HAC p | Top-bottom forward spread |
|---|---:|---:|---:|---:|
| 1h | 1,366 | 0.0388 | 1.49e-12 | 4.90 bps |
| **2h** | **1,203** | **0.0448** | **3.10e-15** | **7.81 bps** |
| 4h | 999 | 0.0357 | 1.83e-09 | 5.34 bps |

The statistical transmission effect is real in this sample, but the spread is smaller than the preregistered execution friction.

## Development portfolio results

| Horizon | Net Sharpe | Total return | Max DD |
|---|---:|---:|---:|
| 1h | -13.72 | -91.0% | -90.9% |
| **2h** | **-8.61** | **-85.6%** | **-85.5%** |
| 4h | -7.95 | -82.2% | -82.1% |

A 10 bps one-way assumption implies roughly 20 bps round-trip friction for each non-overlapping event, overwhelming the observed 5-8 bps gross cross-sectional spread.

## Failure analysis

This is a **cost/frequency mismatch**, not a zero-IC rejection. The source's documented effect is minute-scale and is most relevant to very low-friction execution. The hourly adaptation preserves predictability but not enough gross edge to survive conservative perp costs. Lowering costs after seeing this result would violate the preregistered methodology.

## Multiple-testing audit

Three holding horizons were counted, moving the cumulative parameter-trial count from 93 to **96**. OOS was not consumed, so DSR/PBO are not used for promotion.

## Decision

Classification: `REJECT`. Do not retune the shock threshold, liquidity bucket, or transaction-cost assumption within this candidate.

## Reproduction

`PYTHONPATH=. uv run python scripts/run_crypto_btc_shock_underreaction.py --root /home/quant/dev/quant/ml4t-data/.data/store/crypto_futures_ohlcv_1h_BINANCE_UM_PERP`

## Provenance

Manifest: `run_log/crypto_research/runs/20260928-btc-shock-underreaction-lowliq-manifest.json`
Structured result: `run_log/crypto_research/runs/20260928-btc-shock-underreaction-lowliq-result.json`
