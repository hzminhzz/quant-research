# Seven independent strategies: ML4T feature implementation

Status: **EXPLORATORY, NOT APPROVED**.
The seven strategies are independent and unrelated to Shannon-20.
The standalone feature builders, data loaders, and seven separate native
ML4T backtests have been created.

Authoritative implementation and 2020-2022 evidence:
[Independent seven 2020-2022 audit](independent_seven_2020_2022.md).

- Source: `src/strategies/independent_seven_native_features.py`
- Native execution: `scripts/run_independent_seven_2020_2022.py`
- Canonical local data loader: `src/strategies/independent_seven_data.py`
- Native output reconciliation: `scripts/audit_independent_seven_2020_2022.py`
- Tests: `tests/test_independent_seven_native_features.py`

```sh
uv run python -m pytest -q -o addopts='' tests/test_independent_seven_native_features.py
uv run python -m scripts.run_independent_seven_2020_2022 --case all
uv run python -m scripts.audit_independent_seven_2020_2022
```

Evidence directory: `run_log/independent_seven_2020_2022`.
Do not promote from this 2020-2022 exploratory result, or relabel any
already observed history as an independent holdout.
