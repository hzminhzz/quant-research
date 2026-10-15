# ML4T Engineer

High-performance feature engineering, labeling, alternative bars, and leakage-safe dataset construction for financial machine learning.

## Overview

Built natively on Polars with Numba JIT acceleration for performance-critical kernels. Contains 120 registered technical and microstructure features across 11 categories, with 60 indicators validated against TA-Lib at `1e-6` tolerance.

## Quick Example

```python
from datetime import date, timedelta
import polars as pl
from ml4t.engineer import compute_features

close = [100.0 + i * 0.1 for i in range(100)]
df = pl.DataFrame({
    "timestamp": [date(2024, 1, 1) + timedelta(days=i) for i in range(100)],
    "open": close,
    "high": [p + 1.0 for p in close],
    "low": [p - 1.0 for p in close],
    "close": close,
    "volume": [100_000 for _ in range(100)],
})

# Compute features using name list, custom parameter dicts, or YAML
features = compute_features(df, ["rsi", "macd", "atr"])
print(features.select(["timestamp", "close", "rsi", "macd", "atr"]).tail(5))
```

## Feature Categories (120 Registry Features)

| Category | Count | Key Indicators |
|---|---|---|
| **Momentum** | 31 | RSI, MACD, Stochastic, CCI, ADX, MFI, CMO, ROC |
| **Volatility** | 15 | ATR, Bollinger Bands, Yang-Zhang, Parkinson, Garman-Klass, GARCH |
| **Microstructure** | 15 | Kyle's Lambda, Amihud Illiquidity, Roll Spread, Order Flow Imbalance |
| **Trend** | 10 | SMA, EMA, WMA, DEMA, TEMA, KAMA, Donchian Channels |
| **ML Features** | 14 | Fractional Differencing (`ffdiff`), Entropy, Fourier, Lag Features |
| **Statistics** | 14 | Standard Deviation, Linear Regression, Variance Ratio, Wasserstein |
| **Risk** | 6 | Max Drawdown, Downside Deviation, Tail Ratio, Sortino |
| **Cross-Asset** | 10 | Rolling Correlation, Beta, Cointegration, Lead-Lag Correlation |
| **Regime** | 4 | Hurst Exponent, Choppiness Index, Fractal Efficiency |
| **Price Transform** | 5 | Typical Price, Weighted Close, Median Price |
| **Volume & Math** | 6 | OBV, AD, ADOSC, Rolling Maximum, Minimum, Sum |
