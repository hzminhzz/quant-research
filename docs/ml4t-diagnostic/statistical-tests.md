# Statistical Tests & Multiple Testing Corrections

In quantitative strategy research, testing multiple variants (lookbacks, parameters, universes) inflates the observed Sharpe ratio. `ml4t-diagnostic` provides standard mathematical corrections.

---

## 1. Deflated Sharpe Ratio (DSR)

Calculates the probability that a strategy's observed Sharpe ratio is not a false positive, accounting for skewness, kurtosis, sample length, and the variance across all tested trials.

```python
import numpy as np
from ml4t.diagnostic.evaluation.stats import deflated_sharpe_ratio

# Returns matrix: (n_observations, n_variants)
returns = np.random.normal(loc=[0.0003, 0.0006, 0.0001], scale=0.01, size=(504, 3))

dsr = deflated_sharpe_ratio(
    returns,
    frequency="daily",
    correlation_method="effective_rank",
    min_k_eff=2.0,
)

print(f"Observed Sharpe: {dsr.sharpe_ratio_annualized:.2f}")
print(f"DSR Probability: {dsr.probability:.3f}")
print(f"Effective Independent Trials: {dsr.n_trials_effective:.2f}")
```

### Persistent Trial Ledgers
When running multiple research sessions, all tested variants (including failed ones) must be recorded in a trial ledger (e.g. Parquet) so DSR reflects the true selection history.

---

## 2. False Discovery Rate (FDR) — Benjamini-Hochberg

Controls the expected proportion of false discoveries when testing multiple alpha hypotheses:

```python
from ml4t.diagnostic.evaluation.stats import benjamini_hochberg_fdr

p_values = [0.001, 0.012, 0.030, 0.080, 0.40]
fdr = benjamini_hochberg_fdr(p_values, alpha=0.05, return_details=True)

print("Rejected hypotheses:", fdr["rejected"].tolist())
print("Adjusted p-values:", fdr["adjusted_p_values"].round(4).tolist())
```

---

## 3. Probability of Backtest Overfitting (PBO)

Compares in-sample and out-of-sample performance matrices across partitions using Combinatorial Purged Cross-Validation (CPCV):

```python
from ml4t.diagnostic.evaluation.stats import compute_pbo

# is_matrix: (n_folds, n_strategies)
# oos_matrix: (n_folds, n_strategies)
pbo_result = compute_pbo(is_matrix, oos_matrix)
print(f"PBO: {pbo_result.pbo:.2%}")
```

---

## 4. HAC-Adjusted Information Coefficient

Corrects for serial autocorrelation in overlapping forward-return horizons:

```python
from ml4t.diagnostic.evaluation.stats import compute_ic_hac_stats

ic_stats = compute_ic_hac_stats(ic_series, max_lag=5)
print(f"Mean IC: {ic_stats.mean_ic:.4f}, HAC t-stat: {ic_stats.t_stat:.2f}, p-val: {ic_stats.p_value:.4f}")
```
