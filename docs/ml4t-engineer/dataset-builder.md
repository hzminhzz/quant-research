# Leakage-Safe Dataset Builder

`MLDatasetBuilder` guarantees time-series ML readiness by preventing look-ahead bias and data leakage during feature scaling and train/test splitting.

```python
from datetime import date, timedelta
import polars as pl
from ml4t.engineer import create_dataset_builder

# Prepare features and labels
builder = create_dataset_builder(
    features=features_df,
    labels=labels_series,
    dates=dates_series,
    scaler="robust",  # Options: "standard", "robust", "minmax", or None
)

# 1. Leakage-Safe Train/Test Split
# Automatically fits scaler on train set only and transforms both train & test
X_train, X_test, y_train, y_test = builder.train_test_split(
    train_size=0.8,
    shuffle=False,  # Always False for financial time-series!
)

# 2. Cross-Validation Integration
# Fits independent scaler on each CV fold
for fold in builder.split(cv=splitter):
    X_tr = fold.X_train  # Scaled using fold train statistics
    X_te = fold.X_test   # Scaled using fold train statistics
    y_tr = fold.y_train
    y_te = fold.y_test

    # Convert to NumPy for LightGBM, XGBoost, PyTorch
    X_np, X_test_np, y_np, y_test_np = fold.to_numpy()
```
