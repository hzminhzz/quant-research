# ML4T Diagnostic

Signal diagnostics, statistical validation, and backtest evaluation for quantitative trading workflows.

## Overview

`ml4t-diagnostic` provides rigorous quantitative validation across four distinct research phases to prevent overfitting, data leakage, and false alpha discoveries.

### Four-Tier Validation Framework

1. **Feature Stage:** Evaluate stationarity, autocorrelation, conditional heteroskedasticity, and distribution properties (`FeatureDiagnostics`).
2. **Signal & Model Stage:** Information coefficient (IC), HAC-adjusted t-stats, quantile monotonic spreads (`analyze_signal`, `quantile_profile`).
3. **Backtest Stage:** Multiple-testing corrections, Deflated Sharpe Ratio (`deflated_sharpe_ratio`), Probability of Backtest Overfitting (`compute_pbo`), False Discovery Rate (`benjamini_hochberg_fdr`).
4. **Portfolio & Tearsheet Stage:** Comprehensive standalone HTML reports, factor exposures, tail-risk metrics (`generate_backtest_tearsheet`).

## Quick Example: Deflated Sharpe Ratio

```python
import numpy as np
from ml4t.diagnostic.evaluation.stats import deflated_sharpe_ratio

# Returns matrix across tested strategy variants (T sessions, N trials)
returns = np.random.normal(0.0004, 0.01, size=(504, 10))

dsr = deflated_sharpe_ratio(
    returns,
    frequency="daily",
    correlation_method="effective_rank",
    min_k_eff=2.0,
)

print(f"Annualized Sharpe: {dsr.sharpe_ratio_annualized:.2f}")
print(f"Deflated Probability: {dsr.probability:.3f}")
print(f"Raw Trials: {dsr.n_trials_raw}")
print(f"Effective Trials: {dsr.n_trials_effective:.2f}")
```
