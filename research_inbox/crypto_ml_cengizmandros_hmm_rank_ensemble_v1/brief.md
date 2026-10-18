# cengizmandros: PIT crypto ensemble with regime filtering and negative selection evidence

**SOURCE_CAPTURE_ONLY / THESIS_CAPTURED.** Original practitioner repository: https://github.com/cengizmandros/crypto-ml-trading-research . Inspected author README and public repository layout, 2026-10-18. No models trained or backtests run locally.

## Original idea
The author constructs a lagged top-20 daily **Binance spot** universe, 58 price-volume-derived cross-sectional features and forward-filtered three-state Gaussian HMM regime probabilities. A nested walk-forward stack of LightGBM, XGBoost and a compact Transformer makes ranking scores; a long-only volatility-controlled allocation chooses stronger coins. The author documents past preprocessing-leak corrections, delisted coin/ticker-reuse fixes, selection-trial accounting and realistic fee/slippage/impact assumptions.

## Important adverse evidence
Author claims OOF rank IC 0.14 versus momentum 0.014, 2021–2025 walk-forward Sharpe 0.90, but **CAGR 24.6% failed BTC buy-and-hold CAGR 33.2%**. The author's DSR drops to 0.82 when counting 425 trials, below conventional 0.95. The claimed final 2025-10–2026-10 holdout return was **-8.7%**. These are source claims, **not** locally reproduced facts or a qualified local ATS holdout. The interesting source proposition is coin **underperformer avoidance**, which the author notes cannot be fully monetized by a long-only spot portfolio.

## Source fidelity / ATS transfer
No short leg in original source. A short-bottom-decile perpetual/CFD portfolio would be a NEW adaptation requiring its own source-independent spec and proper firm short/margin permissions, not faithful replication. Original model uses daily prediction and next-day first-hour approximate fill and dynamic regime/risk weights; these do not equal ATS native equal-count dollar-neutral allocation. The model artifacts, historical OOF manifest and precise product cost parity are absent. Mark executable handoff **BLOCKED_PROTOCOL** until an approved, causally verifiable mapping exists. No funding-alpha signal.
