# Exact migration and pruning map

## Scope and applied changes

The original snapshot contains **505 paths** under `src/`, `scripts/` and
`config/`: 51 source files, 321 scripts and 133 configurations. Their complete
path/status/SHA-256 register is retained in
[`../rebuild_20261015/inventory.md`](../rebuild_20261015/inventory.md).
All 505 original byte hashes were rechecked after implementation; none changed.
The delivered `migration_map.json` and `migration_map.md` expand the per-path
mapping below for all 505 paths, without claiming a line-by-line semantic audit.

**Phase 2 originally relocated twenty-nine historical scripts and frozen session YAMLs under `archive/legacy_v1/`. The 2026-10-17 main integration additionally restores all twenty-nine original CLI/configuration paths as byte-identical compatibility copies while retaining the immutable archive.** No original code or historical result was deleted. These preserved entry points are for historical replay, not new factory research. The original and archived byte hashes are verified together in `tests/test_legacy_archive_safety.py`; no strategy has been retired or declared native-equivalent. The active FOMC source/test dependency also stays at its original `config/research_sessions/` location. See [`archive_inventory.md`](archive_inventory.md) for exact locations and retention explanations.
The new shared route is implemented. Except for the explicitly identified bridge
and imported support file, old call sites remain compatibility surfaces. A target
in this map is not a claim of equivalent strategy behavior or a completed cutover.

## New implemented architecture

```text
scripts/quant.py                         unified new-mode CLI
src/workbench.py                        interactive API using the same runtime
src/data_vault/
    panel_builder.py                    source discovery, canonical snapshots, CFD session views
    vault.py                            bounded development reads, exclusive holdout release
src/engine/
    common.py                           identity, atomic writes, append-only ledger
    spec_parser.py                      executable typed YAML + Python-artifact references
    feature_compiler.py                 native/custom PIT feature DAG and shared verification
    signal_allocator.py                 neutral, deterministic target weights
    backtest_runner.py                  native ML4T lifecycle adapters and protective stops
    accounting_audit.py                 independent vectorized verification, not a simulator
    isolation.py / isolated_worker.py    restricted development callback process
    funnel.py                           four stages, receipts, casefile and derived leaderboard
src/oracle/
    causal_truncation.py                 exact sampled-prefix invariance checks
    stage2_diagnostic.py                native forward labels and candidate/baseline IC/HAC
    stage3_falsifier.py                  native simulations, scoped DSR, beta and stop gates
config/candidates/
    crypto_xs_funding_velocity_dislocation_basket_v1.example.yaml
```

## Named old interfaces and exact destination

| Original path | New destination / responsibility | Applied status |
| --- | --- | --- |
| `src/catalog.py` | `src/data_vault/panel_builder.py`, `vault.py`: exact source snapshot and partition authority | New route implemented; old catalog consumers retained |
| `src/market_time.py` | `panel_builder.py`: explicit timezone and calendar-qualified ingestion | New route implemented; legacy imports retained |
| `src/session_calendar.py` | `panel_builder.py`: session labels, bar positions, calendar schedule identity | New route implemented; legacy imports retained |
| `src/features.py` | Existing `src/features/` compatibility package; new requests use `src/engine/feature_compiler.py` | Earlier checkpoint preserved module API; new runtime added |
| `src/labeling.py` | `src/oracle/stage2_diagnostic.py`: native labels for the new next-open endpoint | New endpoint implemented; old specialized labels retained |
| `src/diagnostics.py` | `src/oracle/stage2_diagnostic.py` | New native IC/HAC route implemented; legacy diagnostics retained |
| `src/backtest.py` | `src/engine/backtest_runner.py` plus `accounting_audit.py` | New route never calls the custom legacy simulation |
| `src/models.py` | Retain for model-dependent legacy strategies; future model adapter at the feature/forecast seam | No silent model migration |
| `src/validation.py` | Existing `src/validation/` compatibility package; new economic gates in `src/oracle/stage3_falsifier.py` | Earlier package migration retained; new native DSR route added |
| `src/synthesis.py` | `src/engine/funnel.py`: casefile/leaderboard synthesis; native diagnostic statistics | New route implemented; old reports remain history |
| `src/pipeline.py` | `src/engine/funnel.py` | New factory implemented; legacy/synthetic checkpoint runner retained |
| `src/factory.py` | `src/engine/funnel.py` | Replacement responsibility defined; legacy consumer cutover pending |
| `src/experiment.py` | `src/engine/common.py`, `funnel.py`: one new-mode trial ledger | New ledger implemented; old trials not rewritten |
| `src/research_session.py` | Frozen-v1 compatibility; new specs in `spec_parser.py`, attempts in `common.py` | Historical authority retained |
| `src/validation_status.py` | Historical approval record retained; new stage statuses in casefiles | No deployment approval migration |
| `src/research_control/contracts.py` | Frozen-v1 contract compatibility; new executable model in `spec_parser.py` | No in-place contract conversion |
| `src/research_control/feature_gateway.py` | `FeatureGateway.compute_runtime` delegates to `compile_and_verify` | **Bridge applied**; old `compute` keeps v1 semantics |
| `src/research_control/run_permit.py` | New route uses measured stage evidence and `DataVault.unlock_holdout` | No manual-style v1 permit on new features |
| `src/research_control/attempts.py` | New-mode `common.append_trial` and funnel attempt output | Legacy attempt/recovery records retained |
| `src/research_control/casefile.py` | New-mode `funnel.py`; old Casefile remains a v1 read model | New casefile implemented; no history rewrite |
| `src/research_control/efficiency.py` | Retain as optional agent-efficiency diagnostics | Not an execution gate in the new route |
| `src/research_control/execution.py` | New baskets use `backtest_runner.py`; old synthetic fixture remains compatibility | No arbitrary adapter equivalence claim |
| `src/research_control/m8_cash_calendar.py` | Calendar responsibility in `panel_builder.py`; M8 rule semantics belong in `src/strategies/` | Calendar route implemented; M8 port pending |
| `src/research_control/m8_n8.py` | Future `src/strategies/m8_n8.py` adapter using shared runtime | **Not ported; keep** |
| `src/research_control/dukascopy_native.py` | Data responsibility in `panel_builder.py`; special fill semantics remain named strategy adapter | **Not fully ported; keep** |
| `src/research_control/dukascopy_strategy.py` | Future `src/strategies/dukascopy.py` | **Not ported; keep** |
| `src/research_control/dukascopy_migration.py` | Historical migration evidence/compatibility, separate from the generic vault | Keep history; no replayed migration |
| `src/eow_rebuild.py` | Future `src/strategies/eow.py` | **Not ported; keep** |
| `src/orb_ml_research.py` | Future `src/strategies/orb_ml.py` | **Not ported; keep** |
| `src/orb_raw_optimization.py` | Future `src/strategies/orb_raw.py` | **Not ported; keep** |
| `src/validated_orb_pipeline.py` | Future ORB adapter + shared engine/oracles | **Not ported; keep** |
| `src/patterns.py` | Retain reusable legacy signal definitions; explicit feature adapter where needed | No assumption that a pattern is a generic engine module |
| `src/ftmo_simulator.py` | Retain historical prop evaluation; `src/portfolio/` remains a separate research policy | Not replaced by the new basket runner |
| `src/strategies/independent_seven_data.py` | Same path, byte-identical import from original untracked source | **Imported** to restore reproducible legacy test collection |
| `scripts/research.py` | `scripts/quant.py` for new-mode execution; old discovery/v1 commands remain | New CLI implemented; old CLI retained |
| `scripts/research_session.py` | New specs/attempts via `quant.py`; frozen-v1 operations retain existing CLI | No historical record rewriting |
| `scripts/run_pipeline.py` | `scripts/quant.py run <candidate.yaml>` after strategy representation exists | Original archived byte-identically; script remains historical evidence, not agent entry point |
| `scripts/run_m8_n8.py` | `quant.py` plus a migrated M8 strategy | **Not retired** |
| `scripts/run_m8_cash_session.py` | `quant.py` plus a migrated M8 session strategy | **Not retired** |
| `scripts/run_eow_rebuild.py` | `quant.py` plus a future migrated EOW strategy | Historical runner moved into `archive/legacy_v1/scripts/` via Git rename; EOW strategy is NOT ported |
| `scripts/run_orb_ml_research.py` | `quant.py` plus a migrated model/ORB strategy | **Not retired** |
| `scripts/run_orb_raw_optimization.py` | `quant.py` plus a future migrated ORB strategy | Historical runner archived; specialized ORB strategy is NOT ported |
| `scripts/run_validated_orb.py` | `quant.py` plus a migrated ORB strategy and complete evidence | **Not retired** |
| `scripts/run_btc_eth_relative_value.py` | `quant.py` after exact rule/funding parity is checked | Existing strategy is not silently substituted |
| `config/research_contract_m8_n8_cash_v1.yaml` through `v7.yaml` | Retain immutable historical contracts; new candidate YAML does not require this ladder | **No rewrite or deletion** |

For every other original source/script path, the expanded delivered map retains
its exact path and original byte identity with `legacy_cutover_applied=false`.
Acquisition, repair, forensic, reporting, live/paper and special-engine scripts
are not all interchangeable with a research CLI; retain them until their distinct
responsibility and callers are audited. Every other original configuration stays
at its existing path as historical evidence or an independently versioned input.

The exact `crypto_xs_funding_velocity_dislocation_basket_v1.yaml` was not located.
The example is not a renamed replacement for that missing document. No completed
legacy-port claim is based on its title or on the synthetic four-stage fixture.

## Files outside the 505-path snapshot

`tests/conftest.py` was also copied byte-identically from the original untracked
file to restore test collection. It is not a newly invented skip policy.
`AGENTS.md`, `CLAUDE.md`, the README, dependency declaration/lock and the new ADR
were updated only in this implementation worktree. Raw panels and local test/run
artifacts are not source-code commit inputs.

## Retirement acceptance rule

Retire a runner only after the same source identity, session rules, signals,
entry/exit ordering, stops, cashflows, costs and output evidence reconcile under
the shared path. A successful target-weight synthetic fixture does not establish
that parity for an old stop-entry ORB, M8, live connector or HFT strategy.
The current implementation removes name-based friction for supported new research
without destroying still-needed old capabilities to make the tree look smaller.
