# Feature Engineering API

## `compute_features()` Formats

```python
from ml4t.engineer import compute_features

# 1. List of feature names with default parameters
df1 = compute_features(df, ["rsi", "macd", "atr"])

# 2. List of dicts with custom parameters
df2 = compute_features(df, [
    {"name": "rsi", "params": {"period": 20}},
    {"name": "sma", "params": {"period": 50}},
    {"name": "bollinger_bands", "params": {"period": 20, "std_dev": 2.5}},
])

# 3. YAML configuration file for reproducible research pipelines
df3 = compute_features(df, "features.yaml")
```

Features are computed in dependency order using topological sorting. If an input is a `polars.LazyFrame`, the output is a `LazyFrame`.

---

## Fractional Differencing (`ffdiff`)

Preserves memory in price series while achieving stationarity:

```python
from ml4t.engineer.features.fdiff import find_optimal_d, ffdiff

# 1. Search for minimal d that passes ADF stationarity test
optimal = find_optimal_d(df["close"])
d_val = optimal["optimal_d"]

# 2. Apply fractional differencing
stationary_close = ffdiff(df["close"], d=d_val)
```

---

## Feature Discovery & Catalog

Search and filter across all 120 features dynamically:

```python
from ml4t.engineer import feature_catalog

# List all features in a category
vol_features = feature_catalog.list(category="volatility")

# Filter ML-ready normalized features
normalized = feature_catalog.list(normalized=True)

# Semantic full-text search
results = feature_catalog.search("volatility estimator")
# Returns: [("parkinson_volatility", 0.65), ("garman_klass_volatility", 0.45)]
```
