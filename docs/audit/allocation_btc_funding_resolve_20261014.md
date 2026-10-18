# BTC perpetual funding repair — 2019–2024 development only

**Decision: VERIFIED exploratory funding overlay; NOT exact settlement-certified.**

Executed directly in `quant-research` with no agents, Codex, paper/live, model training, or changes to the promoted Donchian strategy or `ml4t-data`. No data or performance from 2025 or 2026 was requested or read.

## Mechanism

Native Donchian BTCUSDT_PERP backtest (`ml4t-backtest==0.1.7`) models trading fees and slippage but its fixed historical equity path omits periodic Binance perpetual funding. We reconstructed the signed BTC position from the native **fill ledger**, combined it with canonical 8-hour BTCUSDT funding rates, and charged funding at each funding event. The native fills, volatility-targeting rule, leverage, trade costs, and strategy code were not modified.

Funding cashflow: `- signed_position_btc × settlement_or_proxy_mark_usdt × funding_rate`. Positive is a received credit. The primary position convention excludes fills at the scheduled funding slot boundary. An alternative uses the original source event timestamp (which has up to 47 ms ingestion jitter); both are recorded.

## Data and reproducibility

- Canonical rates: `/home/quant/dev/quant/ml4t-data/.data/store/crypto_futures_funding_BTCUSDT_PERP/` (read only).
- Canonical source minute prices for the historical fallback: `/home/quant/dev/quant/ml4t-data/.data/store/crypto_futures_minute_BTCUSDT_PERP/` (read only).
- Original fills and equity: `run_log/independent_five_full_history_20261014/donchian-btc/{fills.csv,equity.csv}`.
- Official Binance USD-M API:
  - `GET https://fapi.binance.com/fapi/v1/fundingRate`
  - `GET https://fapi.binance.com/fapi/v1/markPriceKlines?symbol=BTCUSDT&interval=8h`
- Source raw pages and SHA-256: `run_log/allocation_prerequisites_20261014/btc/mark_repair_raw/` and `funding_repair_summary.json`.
- Retrieval: `python -m scripts.allocation_btc_funding_resolve_20261014`.
- Offline independent audit: `python -m scripts.allocation_btc_funding_verify_20261014`.

Binance's funding-history endpoint provided **1,283** nonempty exact `markPrice` values in the development period; older `markPrice` fields were blank. For those events, the historical **8-hour Binance mark-price candle close immediately preceding settlement** is used instead and is marked as a *proxy*, not an exact settlement snapshot. For the early 2019 gap before mark-price candle history starts, use the previous completely closed **Binance BTCUSDT perpetual one-minute candle** from the canonical local store, again marked explicitly as a proxy. Do not treat this as BTC spot.

No future data fill, missing return-to-zero substitution, or selective choice based on strategy PnL was used.

## Verified results

| Check | Finding |
|---|---:|
| Development funding events | 5,819 |
| Exact official settlement marks | 1,283 |
| Binance 8h mark-close proxies | 4,223 |
| Local perpetual 1m close proxies (2019) | 313 |
| Nonflat 2019 local-proxy events | 133 |
| Development native daily equity rows | 1,941 |
| Full fixed-fill funding cashflows, all events | **−47,096.83 USDT** |
| Funding booked by final native daily snapshot | **−47,090.99 USDT** |
| Final native equity (unadjusted) | 315,678.49 USDT |
| Final marked equity with funding overlay | **268,587.50 USDT** |

The final snapshot is dated on the development ledger's native UTC bar clock. The difference between all funding events and funding embedded at the final native snapshot (−5.83 USDT) is **not** pulled backward from later funding timestamps. It remains unbooked at that mark.

Yearly signed funding cashflow on the fixed-fill native path:

| Calendar year | Funding cashflow (USDT) |
|---|---:|
| 2019 | +48.13 |
| 2020 | −8,534.59 |
| 2021 | −17,169.23 |
| 2022 | +1,115.99 |
| 2023 | −7,759.93 |
| 2024 | −14,797.20 |

## Independent checks and uncertainty

The offline verifier checked all 12 raw official Binance page hashes and counts, exact rate/event-slot matching, arithmetic and timestamp ordering, 2025 cutoff, and every adjusted daily marked-equity identity.

- On 1,283 development events with **both** an official exact settlement mark and an 8h mark-close proxy, the proxy's median absolute mark difference was **0.0131 bp**, maximum **6.5383 bp**. Total absolute funding cashflow difference on this comparison subset was **0.52 USDT**, using actual fixed-fill positions. This is a *diagnostic on the available overlap*, not a proven bound on earlier years.
- The original 00:00 settlement-event timestamps may lag the scheduled slot by 1–47 milliseconds. There are **808 events** where counting a same-slot next-bar fill at the delayed event timestamp changes the position. The alternative convention produces total funding of **−47,106.51 USDT**, a **−9.68 USDT** difference relative to the primary conservative clock. No claim is made that this determines real venue fill priority.

## Scientific limitations

1. **Funding input is usable for exploratory comparison, not exact historical settlement certification.** 4,536 event prices are calibrated or local proxies with row-level provenance; do not rename these as exact `markPrice` observations.
2. The correction is a **post-hoc fixed-fill overlay** on unchanged native equities. It does not feed funding cashflows back into volatility targeting, margin/liquidation, sizing, or future fills. A full funding-integrated native replay would be required for executable-account claims.
3. Daily equity timestamps are native session labels. Funding events enter the accounting only when strictly prior to a snapshot; events after the last development mark are not prematurely recognized.
4. Funding is one component of trading economics. Broker spreads, impact, margin/liquidation and real position chronology remain separate concerns.
5. The 2025–2026 allocator evaluation remains closed. This study makes no claim that the linear allocator improves the four-strategy portfolio.

## Task-owned files

- Code: `scripts/allocation_btc_funding_resolve_20261014.py`, `scripts/allocation_btc_funding_verify_20261014.py`
- Unit tests: `tests/test_allocation_btc_funding_resolve_20261014.py`
- Event cashflow ledger: `run_log/allocation_prerequisites_20261014/btc/funding_cashflows_repaired_development.csv`
- Native-plus-funding equity: `run_log/allocation_prerequisites_20261014/btc/funding_adjusted_equity_development.csv`
- Source manifest: `run_log/allocation_prerequisites_20261014/btc/funding_repair_summary.json`
- Independent offline verification: `run_log/allocation_prerequisites_20261014/btc/funding_repair_independent_verification.json`

**Unchanged:** `promote/donchian_btc/`, `run_log/independent_five_full_history_20261014/`, `ml4t-data/`, and promotion / `NOT_APPROVED` statuses.
