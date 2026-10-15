# Dual-mode research operations

## What runs now

The shared runtime implements canonical development/protected partitions,
PIT feature compilation, exact sampled-prefix tests, native IC/HAC, native
candidate/baseline backtests, selection-family DSR, beta/stop gates, single-use
holdout claims, casefiles and a derived leaderboard. The interactive Workbench
uses the same implementations and cannot obtain a factory holdout claim.

The exact `crypto_xs_funding_velocity_dislocation_basket_v1.yaml` was not found in
the supplied files, Library search, original repository scan or GitHub search.
The `.example.yaml` in `config/candidates/` is explicitly prompt-derived. Its
formulas and assumptions are not attributed to the missing original thesis.
Do not report an exact-candidate backtest from this example.

## Current VPS checkout

```bash
cd /home/quant/.devspace/worktrees/quant-research-25440f7a
export PYTHONPATH="$PWD"
PY=/home/quant/dev/quant/quant-research/.venv/bin/python
```

This isolated worktree reuses the existing installed interpreter. The original
working tree is unchanged. `uv.lock` has been regenerated offline; no dependency
was installed or upgraded during this work. A fresh checkout can use the locked
project environment, but the recorded qualification platform is Linux/Python
3.14 with the versions in the verification report.

## Discover and compile sources

```bash
"$PY" scripts/quant.py discover \
  --store /home/quant/dev/quant/ml4t-data/.data/store/

"$PY" scripts/quant.py build \
  --output data/vault/funding_velocity_development \
  --start 2019-09-01 --end 2026-01-01 \
  --spread-bps 0 \
  --spread-assumption 'Frozen research assumption; spread is included in execution slippage' \
  --funding-mark-policy trade_open_proxy \
  --funding-time-tolerance-ms 1000
```

Omitting `--symbols` discovers all supported source names rather than using a
current exchange listing. The consolidated hourly Binance layout is
`crypto_futures_ohlcv_1h_BINANCE_UM_PERP/symbol=.../year=.../month=...`.
Standalone hourly/minute stores are also discovered; their venue identity must
be explicitly qualified rather than guessed from a ticker. Sources without
funding are listed as exclusions, not converted into zero-carry instruments.

Ingestion works per symbol and writes a new immutable snapshot. Use a new output
directory for a different snapshot. It does not overwrite prior files or claim
that discovered historical symbols constitute a complete delisting archive.
The observed inventory had 864 consolidated hourly symbols and 530 funding
directories, with 530 matching pairs. This is not evidence of 660 matched pairs.

Funding rate is an event impulse, never a forward-filled hourly cashflow. Raw
source timestamps remain in the sidecar. The declared tolerance normalizes small
post-boundary timestamp jitter to a modeled pre-open settlement. This is not
proof of the exchange's exact settlement eligibility clock. The last recorded
interval supplies a causal staleness bound; it is not a known future schedule.

`trade_open_proxy` fills absent settlement marks from that bar's opening trade
price and labels each substituted mark. `observed_only` retains missing marks,
so simulation cannot pretend to know a required settlement notional. Quote
spread and mark proxies remain assumptions in the casefile.

The build command defaults to development only. A separate, trusted ingestion
job can add `--include-protected` and an exact end date such as `2026-10-01` to
write both kinds of partitions into a new snapshot. This is a data-ingestion
operation, not permission for a research callback to inspect those rows. No
real protected-history build was executed in this implementation session.

CFD cash-session ingestion is available through the same builder:

```python
from src.data_vault import PanelBuilder

builder = PanelBuilder(raw_store, new_snapshot_directory)
manifest = builder.build_cfd(
    source_root=exact_cfd_source_directory,
    symbol="DUKASCOPY_USATECH_CFD",
    source_identity="Explicit broker/product/source identity",
    start="2025-01-01",
    end="2026-01-01",
    exchange_calendar="XNYS",
    source_bar_seconds=60,
    bar_seconds=1800,
    spread_bps=2.0,
    spread_assumption="Example cost assumption; replace with source-qualified spread",
    carry_assumption="Cash-session research view; no unobserved overnight swaps assumed",
)
```

This selects a calendar-defined research view, not the entire broker's dealing
calendar. It keeps quote/tick-volume semantics. Optional scalar swap events
require explicit rates and marks. Asymmetric long/short swaps, point-denominated
broker charges, and settlement outside the selected view need an appropriate
execution adapter; they are not silently converted into this scalar schema.
The currently qualified autonomous execution path is the synchronous
cross-sectional perpetual-basket model, not every legacy CFD strategy.

## Four-stage factory

```bash
"$PY" scripts/quant.py validate \
  config/candidates/crypto_xs_funding_velocity_dislocation_basket_v1.example.yaml

"$PY" scripts/quant.py run \
  config/candidates/crypto_xs_funding_velocity_dislocation_basket_v1.example.yaml
```

`panel_root` must identify the intended certified snapshot. An absolute path is
unambiguous; a relative path is relative to the process working directory.
`run --build-if-missing` can compile a development snapshot first. That option
alone does not materialize protected history or bypass the Stage 4 claim.

The factory freezes `spec.json`, spec hash, code/environment identity and attempt
registration before observing diagnostics. It runs Stage 1 and Stage 2, and only
continues after their actual checks pass. Stage 3 uses the same frozen rules in
train and validation. A Stage 3 pass permits one Stage 4 read; it is not proof
that the thesis will succeed on that window.

| Terminal status | Exit | Meaning |
| --- | --- | --- |
| `FALSIFIED_STAGE_2` | 0 | The declared signal/baseline falsifier failed. Research completed. |
| `FALSIFIED_STAGE_3` | 0 | Native train/validation economics failed the declared gates. |
| `HOLDOUT_EVALUATED` | 0 | The frozen protected evaluation ran once; inspect its results. |
| `INCONCLUSIVE_*`, `BLOCKED_*` | 3 | Missing or insufficient evidence/data; no qualification claim. |
| `INVALID_*`, `ENGINEERING_ERROR` | 2 | Invalid input or an implementation failure. |

The casefile resides under
`run_log/dual_mode/<candidate_id>/<attempt_id>/casefile.json`.
New-mode events append to `run_log/trial_ledger.jsonl`.
`run_log/leaderboard.json` is a regenerable reference view, not a second ledger.
Keep one configured ledger root for the research workspace; changing directories
does not erase older exposure or justify claiming a new unseen sample.

## Workbench

```python
from src.workbench import Workbench

wb = Workbench("config/candidates/my_candidate.yaml")
prices = wb.load()               # Development files only; no permit.
features = wb.features()         # Native + declarative features, isolated checks.
diagnostics = wb.ic()            # Native train-only candidate/baseline IC and HAC.
result = wb.backtest()           # Exploratory native simulation, not promotion.
path = wb.export_yaml()          # Re-importable thesis_candidate.yaml.
```

A custom callable must retain the canonical rows/columns and return the declared
feature columns and a non-null Boolean `in_pit_universe` mask. It is archived by
hash and evaluated in the restricted worker. Export writes a YAML reference plus
a hashed Python sidecar; it never disguises arbitrary code as a plain expression.
Re-import verifies the artifact and deserializes it only inside the worker.

To replace a feature with declarative code, pass a complete list of feature
objects to `wb.features([...])`. Supported operations include causal lags,
differences, trailing sums/means/standard deviations, arithmetic, conditionals,
and active-universe cross-sectional rank/mean. Operations are an allowlisted
expression tree; YAML strings are not executed.

Native/custom features are verified through one `compile_and_verify` interface.
Existing callers can use `FeatureGateway.compute_runtime` as a compatibility
bridge. Old `ResearchContractV1` calls retain their frozen historical semantics.

## Accounting and causality interpretation

A panel timestamp denotes bar opening; complete-bar features become usable at
bar close. A signal produced for bar t can first fill at the next opening. The
Stage 2 target uses that next opening as entry and a future opening as exit;
outcomes crossing the train boundary or a missing-bar horizon are censored.

Target weights are dollar-neutral at allocation. Quantities are frozen using
signal-close equity/prices, so opening gaps can change realized weights. Native
funding affects cash before that bar's orders. Costs are one-way and spread is
not double charged. Protective stops use the actual episode entry plus/minus the
ATR distance frozen at the signal; increases/decreases do not re-fit that stop.

The matcher first handles opening gaps, then scheduled opening trades, then
intrabar stop touches. This sequencing is regression-tested. A separate
vectorized validator reconstructs cash, funding, holdings and equity from native
fills. It cannot generate substitute trades or silently replace a failed native
engine.

DSR is scoped to the declared selection family and its available aligned daily
return evidence. The candidate is evaluated against the cohort correction,
not against a probability accidentally belonging to the baseline. Incomplete
historical research across other legacy ledgers is not represented as a complete
global trial correction. A single-series PSR is never labeled multi-trial DSR.

## Qualification boundaries

The full four-stage positive path is tested with synthetic data and actual native
ML4T features, diagnostics and simulation, not forced PASS mocks. The rejected
CLI path, Workbench export/replay, sandbox denial, concurrent claims, funding
cashflows, netting, entry-bar stops, opening exits and gap stops are tested too.

A real BTC/ETH engineering regression covers January 1-8, 2025: 336 hourly price
rows, 42 funding events, explicit mark proxies and nine basis points one-way
commission plus slippage. This validates runtime mechanics, not strategy alpha.

Full 530-symbol compilation/runtime capacity and an exact original-candidate
run have not been qualified. The callback worker currently has explicit
120-second CPU and 8-GiB address-space limits. Large jobs need measured resource
qualification; do not call a small fixture a full-universe stress test.

Historical-vintage reconstruction, owner-proof sandboxing, every legacy
strategy migration, asymmetric broker swaps, liquidation and passive queue
models are outside the demonstrated qualification. Original files and old
contracts remain available; see `migration.md` for exact mapping and cutover
status. No live broker request or trading order is authorized by this runtime.
