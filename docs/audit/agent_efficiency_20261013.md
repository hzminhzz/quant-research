# M7-B agent efficiency and versioned regression evidence

**Measured 2026-10-13 on the canonical VPS.** Reproduce from the M7-B worktree:

```bash
uv run python scripts/benchmark_casefile.py \
  --root /home/quant/dev/quant/quant-research \
  --session vwap_pullback_adx_dukascopy_20261012_v1 \
  --samples 9 --verify-corpus

uv run pytest -o addopts= -p no:cacheprovider tests/test_agent_efficiency.py -q
```

The observed result is pinned in [agent_efficiency_metrics_20261013.json](agent_efficiency_metrics_20261013.json). The executable benchmark is `src/research_control/efficiency.py`. It compares two read-only API workflows on the same frozen source and latest-attempt ledger:

- **Fixed baseline:** existing legacy `status` plus separate `AttemptLedger.latest()` lookup (two API calls). This is a measured reconstruction of the two-call workflow, not a contemporaneously captured pre-rollout production baseline.
- **Casefile:** one `build_casefile()` call, returning the same frozen spec hash/data declaration, declared trial count, and latest attempt identities/statuses (one API call).
- **Cold** means first invocation in an already initialized Python process, not process startup or a cold VPS boot. **Warm** means nine repetitions on the same host. Both include filesystem and runtime visibility work as implemented.
- The benchmark checked `polars.read_parquet` and `polars.scan_parquet`; both paths performed zero market-data Parquet reads. This is not a claimed optimization because neither path is designed to read market data.

## Current nine-sample observations

| Metric | Fixed baseline | Casefile | Interpretation |
| --- | ---: | ---: | --- |
| Python API calls per defined task | 2 | 1 | One fewer call in this fixed workflow; not an LLM tool/token measure |
| First-call latency | 21.0216 ms | 9.0403 ms | One host-local observation per path |
| Warm median | 21.0813 ms | 9.8812 ms | 53.1% lower for this task and run |
| Warm p95 estimate | 22.0980 ms | 10.3374 ms | Order statistic from nine samples; not a population estimate |
| Market-data Parquet reads | 0 | 0 | Explicitly instrumented; no improvement claimed |
| Latest attempt identities in measured session | 0 | 0 | The live frozen session had no attempt records at measurement time |
| Full-dataset hashes requested | 0 | 0 | No full data hash was part of either workflow |

The frozen source is identified by spec SHA-256 `0d62ce1ee4d2d17e493c17ab242bc2ce1bc2bd475e9c146973ecc2ff663f1d2e` and the declared data path `data/processed/vwap_adx_dukascopy_2026_1m.parquet`. Installed versions: `ml4t-engineer==0.1.4`, `ml4t-backtest==0.1.7`. The managed contract requests **1 native ADX** and **5 approved extensions**, with **0 unmanaged features** in that contract. Extension count does not imply native equivalence or reduced market-data costs.

## Fixed executable task corpus

`tests/test_agent_efficiency.py` contains 13 passing tests for this M7-B run:

| Classification | Cases | Verified |
| --- | --- | --- |
| Positive | native ADX; approved VWAP extension; native conservative execution and cash audit; safe recovery and duplicate-launch prevention | 4/4 passed |
| Adversarial | wrong LSE/NQ source; future-feature availability leak; false native VWAP; missing frozen session; unsafe take-profit-first fill; fabricated worker success | 6/6 rejected |
| Real failure regression | Wilder ADX warmup checked against independent TA-Lib | 1/1 passed |
| Casefile schema regression | terminal artifact is linked through the actual `record.artifact.path` record envelope | 1/1 passed |
| Benchmark invariant | authoritative source/trial/attempt identities match; raw Parquet reads remain forbidden | 1/1 passed |

Observed policy false decisions in this small deterministic corpus: **0 false failures among 4 positive tasks** and **0 false acceptances among 6 adversarial tasks**. These counts are not general error-rate estimates.

The duplicate-launch fixture issued five identical reservations while the first lease existed; all five returned `BLOCKED`. A visible active job returned `RESUME` for the same attempt. These are deterministic synthetic checks, not five observed VPS scheduler failures. The managed regression corpus generated no live trades and did not launch a worker.

## Versioned historical defects

1. **Native OCO sibling ordering:** the installed `broker.submit_bracket` selected take-profit first on a bar that crossed both stop and target. `tests/test_native_execution.py::test_native_default_bracket_is_rejected_when_both_levels_touch` checks that the independent auditor rejects this outcome; the positive task checks explicit stop-before-limit submission.
2. **ADX warmup seed offset:** the prior Wilder recurrence differed by 46 leading rows on the pinned Dukascopy source, with maximum absolute ADX difference 1.3363. The correction uses period-minus-one initialization. `tests/test_agent_efficiency.py::test_regression_wilder_initialization_matches_independent_talib` compares all valid values to TA-Lib and checks the first output at index 27.
3. **Terminal artifact record envelope:** `session_status()` wraps terminal records under `record`; the Casefile now reads `record.artifact.path`. The new test creates a real terminal record using `record_trial()` and verifies that the artifact path appears in `evidence_refs`.

## Limitations

- No real-money trades, live execution, or production qualification.
- The protected holdout was not opened, reset, or relabeled.
- This measures one narrow information-retrieval task, not end-to-end research quality, human/agent time, LLM tokens, compute cost, execution velocity, Sharpe, or market edge.
- Nine warm timings are correlated and too few for a significance claim. Cold values are not process-cold.
- Legacy status performs repository and runtime inspection that Casefile does not reproduce internally; latency reflects the actual API paths, not identical internal work.
- Zero measured market reads is expected in both workflows. Timing can vary with CPU load, filesystem cache, tmux visibility, and attempt count.
- No improvement is claimed beyond the observed narrow workflow. All research remains `EXPLORATORY` / `NOT_APPROVED`; no live-trading authority is added.
