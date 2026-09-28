# Crypto Research Run - High-Volatility 8-10 Week Reversal

## Conclusion

**REJECT.** The previous runtime blocker is resolved. The exact preregistered 56/63/70-day specification was resumed unchanged. No new parameter trial was added. The canonical 63-day variant passed development but failed exploratory 2024-2025 OOS with net Sharpe **-0.1802**, total return **-39.58%**, and max drawdown **-68.59%** at 10 bps one-way cost.

## Source

Patrick Kiefer and Michael Nowotny, *Reversal in Cryptocurrency Returns* (2026 revision), SSRN 6703978.

## Hypothesis and Archetype

The hypothesis is that recent 8-10 week losers outperform winners as speculative overshooting corrects, especially among high-volatility assets. Archetype: cross-sectional conditional reversal.

## Pre-Registration

Binance USD-M USDT perpetuals were aggregated from 1h bars to complete UTC days. Each Monday, the point-in-time top 50 by lagged 30-day quote volume was reduced to the high-volatility half using lagged 30-day realized volatility. Formation windows were 56, 63, and 70 days, with 63 days canonical. The portfolio was equal-weight long loser quintile and short winner quintile, 0.5 gross per side, Monday open to next Monday open. Development was 2022-2023; exploratory OOS was 2024-2025. Base cost was 10 bps one way with 2x and 3x stress.

## Universe and Data

The completed run observed **262** USDT perpetual symbols. Eligibility used lagged liquidity and volatility, never realized strategy returns. Sealed confirmation data was not used.

## ML4T Engineer Usage

The implementation used causal rolling returns, realized volatility, and lagged quote-volume liquidity from the canonical 1h panel. No full-sample scaling, feature selection, clustering, or post-result feature sweep was used.

## Signal Diagnostics

Development mean rank IC was 0.0868, 0.0778, and 0.0672 for 56/63/70 days, with HAC p-values 0.00021, 0.00106, and 0.00476. The canonical OOS IC weakened to **0.0309** with HAC p **0.227** and high-minus-low spread **-0.24%**.

## Results

Canonical 63-day development Sharpe was **1.3186**, total return **+122.27%**, and max drawdown **-29.92%**. OOS base Sharpe was -0.998 for 56 days, -0.180 for 63 days, and -0.160 for 70 days. Canonical 2024 return was +3.30%; 2025 was -41.51%. Canonical total return fell to -44.30% at 2x cost and -48.66% at 3x cost.

## Breadth and Robustness

Excluding BTC/ETH did not improve the canonical result. The strongest absolute contributor was MYXUSDT. Removing it improved Sharpe to 0.1436 but total return remained -11.33%. One-day delayed execution also failed. Neighboring formation windows, higher costs, annual stability, and the max-drawdown gate all failed.

## Failure Analysis

The effect did not generalize. Development IC and performance were strong enough to justify consuming exploratory OOS, but OOS significance disappeared, the realized spread changed sign, 2025 was strongly negative, and neighboring parameters did not stabilize the result. No post-hoc retuning is justified.

## Multiple-Testing Audit

Family DSR probability was **0.1906**. The 160-trial proxy DSR probability was **0.2488**. The reconciled research ledger remains at **165** trials because this run only completed an already-counted preregistered attempt. PBO is not meaningful for only three preregistered formation windows.

## Decision

**REJECT**

## Reproduction

`uv run python scripts/run_crypto_highvol_reversal.py --root /home/quant/dev/quant/ml4t-data/.data/store/crypto_futures_ohlcv_1h_BINANCE_UM_PERP`

## Provenance

Script git blob: `eb4b2ceb1f602a8c0d791b2af0fc7d16deccba9c`. Manifest SHA-256: `b911c5f6168df912dfded17f04c2a8e60eac7eb2cdb6766a8f5f2ba1fdb9686b`. Dataset manifest SHA-256: `261a29b1df22e242cba2fd1a68c928f2ba3233f2134ad0d00ea87f59163dca81`.
