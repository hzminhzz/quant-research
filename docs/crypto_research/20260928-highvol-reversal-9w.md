# Crypto Research Run — High-Volatility 8–10 Week Reversal

## Conclusion
**INCONCLUSIVE due to execution limit.** The candidate was fully preregistered from Kiefer & Nowotny (2026), but the deterministic broad-universe runner exceeded the available 300-second command limit twice before producing any statistics. No result-dependent tuning occurred and 2024–2025 OOS was not consumed.

## Source
Patrick Kiefer & Michael Nowotny, *Reversal in Cryptocurrency Returns* (2026, SSRN 6703978). The paper documents 8–10 week cross-sectional crypto reversal and reports stronger results when conditioning on high past volatility.

## Pre-Registered Specification
- Binance USD-M USDT perpetuals aggregated to complete UTC days.
- Weekly point-in-time top 50 by lagged 30-day quote volume.
- Retain the high-volatility half by lagged 30-day realized volatility.
- Formation windows: **56 / 63 / 70 days**; canonical **63 days**.
- Long recent losers, short recent winners; equal-weight 0.5 gross per side.
- Weekly Monday-open holding period.
- 10 bps one-way base cost; 2x/3x stress if development passes.
- Development 2022–2023; OOS 2024–2025.

## Execution Status
1. Exact runner: exceeded 300-second command limit before any statistics returned.
2. Loader-only optimization: restricted the first scan to the causal development warmup and deferred OOS loading; strategy definition unchanged.
3. Optimized runner: again exceeded the 300-second command limit before any statistics returned.

## Multiple-Testing Audit
The three preregistered formation windows are conservatively counted as attempted trials, moving cumulative trial count from **157 to 160**. No performance values were observed.

## Decision
**INCONCLUSIVE**

## Reproduction
`uv run python scripts/run_crypto_highvol_reversal.py --root /home/quant/dev/quant/ml4t-data/.data/store/crypto_futures_ohlcv_1h_BINANCE_UM_PERP`

A runtime with a command window longer than 300 seconds should resume this exact specification rather than altering it.
