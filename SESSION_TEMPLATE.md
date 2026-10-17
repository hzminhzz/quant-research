# Quantitative Research Session Prompt & Checklist Template

Use this template at the start of any coding session in `quant-research`. It guarantees that all agents load the required ML4T skills, use verified library modules, and maintain repository audit standards.

---

## 📋 Copy-Paste Prompt for Starting a Session

```markdown
You are working in quant-research. Strictly follow AGENTS.md Mandatory Execution Gate:

1. Skills:
   - Polars transforms: invoke skill ml4t-polars-patterns
   - Features: invoke skill ml4t-compute-features
   - Diagnostics: invoke skill ml4t-evaluate-factor
   - Backtest: invoke skill ml4t-run-backtest

2. Libraries:
   - Use `from ml4t.engineer import compute_features, labeling`
   - Use `from ml4t.diagnostic import analyze_signal, Evaluator`
   - Use `from ml4t.backtest import Engine, Strategy, BacktestConfig, DataFeed`
   - Do NOT hand-roll custom simulation loops or ad-hoc backtesters.

3. Goal for this session:
   [DESCRIBE YOUR HYPOTHESIS / TASK HERE]
```

---

## 🛠️ Phase-by-Phase Execution Checklist

### Phase 0: Pre-Flight Verification
- [ ] Confirm `ml4t.*` packages resolve:
  ```bash
  uv run python -c "import ml4t.engineer, ml4t.diagnostic, ml4t.backtest; print('ML4T Ready')"
  ```
- [ ] Read `AGENTS.md` and `docs/research_sessions.md`.

### Phase 1: Thesis Freezing & Data Gate
- [ ] Define the thesis spec: `config/research_sessions/<session_id>.yaml`
  - Explicit economic mechanism
  - Pre-registered falsifiers & stopping rules
  - Root-relative data paths (< 100 MB, < 1,000,000 rows)
  - Realistic costs (maker/taker fees + slippage + funding)
- [ ] Freeze spec:
  ```bash
  uv run python scripts/research_session.py init --spec config/research_sessions/<session_id>.yaml --root .
  ```
- [ ] Audit data gate:
  ```bash
  uv run python scripts/research_session.py check --session <session_id> --root .
  ```
  *(Must output `"status": "PASS"` with 0 issues).*

### Phase 2: Feature Engineering (`ml4t.engineer` & `ml4t-polars-patterns`)
- [ ] Lazy evaluation with `pl.scan_parquet()`.
- [ ] Time-series features vectorized with `.over("symbol")` in a single `.with_columns()` block.
- [ ] Cross-sectional features vectorized with `.over("timestamp")`.
- [ ] Use `ml4t.engineer.compute_features()` for library factor catalog.
- [ ] Zero Python UDFs (`.map_elements()`).

### Phase 3: Factor Diagnostics (`ml4t.diagnostic`)
- [ ] Compute Information Coefficient (Spearman Rank IC) using `ml4t.diagnostic.analyze_signal()`.
- [ ] Inspect IC decay curve across forward periods ($15\text{m}, 60\text{m}, 240\text{m}, 1440\text{m}$).
- [ ] Check quantile spread monotonicity and $IC\_IR$ stability.

### Phase 4: Event-Driven Backtesting (`ml4t.backtest`)
- [ ] Subclass `ml4t.backtest.Strategy` (implement `on_start`, `on_data`, `on_end`).
- [ ] Assemble `DataFeed(prices_df=..., context_df=...)`.
- [ ] Set `BacktestConfig`:
  - `allow_short_selling = True`
  - `share_type = ShareType.FRACTIONAL`
  - `commission_type = CommissionType.PERCENTAGE` (explicit taker fee, e.g. `0.0004`)
  - `slippage_type = SlippageType.PERCENTAGE` (explicit slippage, e.g. `0.0002`)
- [ ] Run through `Engine(feed, strategy, config).run()`.

### Phase 5: Audit Ledger Recording
- [ ] Save metrics artifact to `run_log/<session_id>/<trial_id>/result.json`.
- [ ] Record trial in research session ledger:
  ```bash
  uv run python scripts/research_session.py record \
    --session <session_id> \
    --trial <trial_id> \
    --status completed \
    --artifact run_log/<session_id>/<trial_id>/result.json \
    --root .
  ```
- [ ] Verify session report:
  ```bash
  uv run python scripts/research_session.py report --session <session_id> --root .
  ```
