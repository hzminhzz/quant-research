# Phase 2 cutover — measured verification and limitations (2026-10-15)

## Reproducible source and code identity

- Worktree branch: `feat/rebuild-20261015-governed-core`; original requested base: `827731d`.
- Source store: `/home/quant/dev/quant/ml4t-data/.data/store/`.
- The original candidate was **not supplied**. The run uses the explicitly labeled **prompt-derived example** at
  `config/candidates/crypto_xs_funding_velocity_dislocation_basket_v1.example.yaml`;
  the source identity is not exact thesis parity.
- Vault: `data/vault/full_530_20261015`.
- Final immutable-manifest digest: `69ed952e9dee296bf0a24de9fce819fdc515f32926f783874da56fd8650a242f`.
- Partition boundary: `2026-01-01T00:00:00Z`. The research runner read development only,
  through exclusive `2026-01-01`; 2026 protected data were never opened.
- Final run casefile: `run_log/dual_mode/crypto_xs_funding_velocity_dislocation_basket_v1_example/20261015T160541-70e970628c/casefile.json`.
  Casefile SHA-256: `5495600279ed7cf9d371abb5f395610a48d1788a4b5acc20becdf27196d4e255`.
  Recorded runtime code hash: `9e0dcfdc40699616bfbce2ade77a5cf951239410a3f00c4d00ec82c05c7befab`, independently verified to match the final working source files.
  These artifacts are intentionally ignored from Git, not copied as alleged live evidence.

## Full matched-source ingestion

The exact BINANCE_UM consolidated 1h OHLCV/funding directory intersection is
**530 USDT-margined *_PERP symbols**. One symbol-month at a time is compiled,
checkpointed, source/output-hashed, and partitioned by the protected boundary.
Unicode venue names use deterministic ASCII **directory hashes**, while preserving
their original Unicode symbol names in data and manifest.

| Partition | Symbols with one or more bars | Price rows | Funding event rows |
| --- | ---: | ---: | ---: |
| Development 2019-10-01 to 2026-01-01 (exclusive) | 484 | 8,296,320 | 1,424,591 |
| Protected 2026-01-01 to 2026-10-01 (exclusive) | 520 | 3,308,516 | 747,985 |

Union of development and protected symbols: **530/530**. Only 474 symbols overlap
both sets (46 are protected-only and 10 development-only).
This is **not** a claim of continuous history or historical survival completeness.
The final manifest has 32,314 entries and 28,697 exclusions: 28,363 unavailable or
invalid month/source slices (`BLOCKED_DATA`) and 334 price-only/mismatched names
(`EXCLUDED_SOURCE`). An excluded month is never backfilled with invented bars.
Some historically old dates in the target interval do not exist for the source.

## Verified factory outcome (final manifest)

Execute:
```bash
NUMBA_DISABLE_JIT=1 POLARS_MAX_THREADS=4 \
  /home/quant/dev/quant/quant-research/.venv/bin/python \
  scripts/quant.py run \
  config/candidates/crypto_xs_funding_velocity_dislocation_basket_v1.example.yaml
```

| Stage | Outcome | Measured evidence |
| --- | --- | --- |
| 1 — PIT, causality, data and allocations | **PASS** | 8,296,320 development rows; 484 historical symbols; sampled prefix-invariance checks |
| 2 — Signal/HAC IC vs baseline | **FALSIFIED_STAGE_2** | 28,360 temporal observations; 48-lag HAC, all three preregistered gates fail |
| 3 — ML4T native basket simulation | **NOT EXECUTED** | Rejected by mandatory Stage 2 stop; **no real Stage 3 net PnL, Sharpe, beta, stops, or DSR can be claimed** |
| 4 — protected holdout | **NOT OPENED** | Casefile `holdout_access=false` |

Stage 1 evidence SHA-256:
`9d0ca20487e5a1ea1b4213eb6c92d3c5ca8ebd225462e8502aa1335cf9b53e3f`.

Stage 2 evidence SHA-256:
`1ac20616fd7e30ab4319adad4a763601d7f29794bcb79048b14ff1184cc4456b`.

| Signal | Mean IC | HAC t-stat | p-value |
| --- | ---: | ---: | ---: |
| Negative 24h funding velocity | 0.0048749444 | 1.2916644 | 0.19648 |
| Negative static 24h funding level (baseline) | 0.0222984350 | 3.8982947 | 0.0000971 |

Freeze assumptions: 5 long / 5 short, 48h rebalance, 3×ATR initial stop,
9 bps **one-way** modeled commission+slippage (18 bps roundtrip),
source funding settlement intervals (not forced to 8h). This set was **not**
measured in Stage 3, because Stage 2 rejected the candidate. Do not describe
it as a successful native backtest.

## Other engineering checks

1. Feature-worker process keeps Bubblewrap network/filesystem isolation. It
   replaces cumulative `RLIMIT_CPU=120` with a 600-second **parent wall-clock**
   deadline, and raises `RLIMIT_AS` to 64 GiB so Arrow virtual reservations
   do not appear as physical 8-GiB exhaustion. It caps Polars workers at four
   threads. A real isolated Polars 500-symbol/360,000-row rolling and
   cross-sectional test passes.
2. `quant.py ingest SOURCE -o CANDIDATE.yaml` accepts explicit, typed raw
   research fields or a complete `candidate_spec`. It validates the output
   and rejects unmapped/prose-only executable rules rather than inventing them.
3. Twenty-nine tracked historical paths (fourteen one-off Python runners, fifteen
   session YAMLs) were quarantined byte-identically via Git rename into
   `archive/legacy_v1/`. Nine referenced legacy paths, including the active FOMC session YAML, remain as
   compatibility dependencies. The original 505-file inventory remains
   retained; this **is not** a claim that all 505 files were physically moved.
4. Stage 3 DSR now counts prior attempts from the global `(market_scope,
   label_horizon_bars)` ledger, including failed/early research attempts,
   and requires at least ten prior attempts **plus ten distinct historical return series aligned to the candidate** (the current candidate and its baseline do not count as priors).
   Lacking sufficient evidence is `INCONCLUSIVE`, never a first-trial PASS.
   Unknown correlation for unmatched attempted trials receives a conservative
   trial-count penalty.
5. The optional prop sizing overlay is disabled by default. It uses
   Prague-calendar day transitions, the previous completed midnight mark,
   and bounded tapering toward a daily -5% of initial-balance floor, overall
   -10% floor and +10% target. This is research-only sizing, not a guaranteed
   no-breach controller; gaps, stale marks and real broker rules require
   separate qualification.

## Boundaries

This cutover establishes bounded ingestion and negative full-scale **Stage 2**
research qualification, **not** an end-to-end profitable Stage 3/4 promotion.
The funding and execution approximations are documented. Previously exposed
2026 market research cannot be made unseen by a new vault.
