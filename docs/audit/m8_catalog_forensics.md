# M8-A catalog forensics

**Observed:** 2026-10-13. **Checkout:** `feat/agent-research-m8` at
`e5d14a7f4b2ee1645d07e8b9cc3e7f47306a859c` before M8 changes.

## Question and method

The question was whether four marked catalog-test failures came from bad
resolver policy, outdated tests, or changed source evidence. I ran
`uv run python -m pytest -q -m data tests/test_catalog.py` against the live
store. The run returned four passes and four failures. I checked each assertion
against `.catalog/research-dataset-catalog.json`, the referenced acceptance
files, and the data-source contract in `ml4t-data`.

The live catalog file SHA-256 is
`8b37902a270c9d8144d27af63d9c56eb3b214bc01b71b3da3e1ecc795b674b4e`.
Its identity is
`ed739ea21a7bc2293116392b6bc948eab1a608955bda83b36e19fde01d3ac1b9`.
The source-readiness table and stable identities are in
[`source_readiness.json`](../../run_log/m8/source_readiness.json).

## Reproduced failures

| Test | Old expectation | Live evidence | Classification |
| --- | --- | --- | --- |
| `test_resolve_accepted_indices` | Accepted index aliases have `accepted_with_exclusions` | DAX, NQ, ES, and Nikkei resolve to current catalog entries with qualification `accepted` | Stale test expectation |
| `test_unqualified_canonical_indices_fail_closed_without_override` | NAS100 is unqualified | NAS100 resolves to canonical `index_minute_NQ`, qualification `accepted`; SPX500 resolves to canonical `index_minute_ES`, qualification `accepted` | Stale alias and qualification expectation |
| `test_resolve_legacy_secondary_requires_explicit_override` | NQ and ES resolve only to secondary legacy datasets | NQ and ES now resolve to canonical Dukascopy CFD datasets | Stale alias authority expectation |
| `test_resolve_data_store_returns_provenance_audit` | DE30 source symbol is `DE30/EUR` | Current DAX catalog source symbol is `deuidxeur` | Stale source-symbol expectation |

These are test-fixture drift, not resolver failures. The catalog does not
identify these index series as CME futures. `contract_level_futures` is false
for the current NQ, ES, and Nikkei entries. The resolver continues to reject
them when a caller requires contract-level futures.

The current catalog also keeps `US30` non-canonical and unqualified. The tests
now check that source against both default fail-closed gates. A separate
catalog fixture checks the independent non-canonical, unqualified, and
contract-level gates without any external data.

## Confirmed stale readiness artifact

The current readiness file SHA-256 is
`f747b8bc303cf5e377d864648d2e39245e31534db8e5d0cd8b3fc44d23da1813`. It names
catalog identity
`229b98a998e04fc268abc7e77ce81552d3aec0885b40650deb3211987db93575`, which
differs from the live identity above. It also labels DAX and Nikkei as London
Strategic Edge datasets. The live catalog and their accepted records identify
Dukascopy sources. The old file still reports broad readiness booleans.

This is a confirmed stale-derived-view defect in the consumer path. Before
this change, `load_readiness_audit` and `is_research_ready` trusted those
booleans without comparing catalog identity. The reader now raises
`CatalogResolutionError` when the readiness identity does not match the live
catalog. It asks the data owner to rebuild the audit. This checkout does not
write to the canonical `ml4t-data` store.

## Source readiness

The separate structured report records exact catalog identities and current
Parquet observations for Dukascopy NAS100, SPX500, and Nikkei CFD series, plus
the Binance USD-M BTCUSDT perpetual candles. All three CFD entries are
canonical and accepted in the current catalog. Their acceptance files have no
blocking days. Their stored timestamps are UTC. The data-source contract
states that Dukascopy timestamps are minute timestamps and provider volume is
requested in `units`. This volume is not centralized CME volume. The exact
meaning of index-CFD volume is not established here, so this report excludes it
from signal use.

Each CFD acceptance record retains five confirmed out-of-session provider
snapshot days. The catalog does not define the broker's cash or extended-hours
calendar. A strategy must use a named calendar and verify every required entry
and exit bar in the selected source. Costs, contract multipliers, lot limits,
and margin rules are also not in the catalog. Therefore, these are eligible
historical CFD price series, not validated broker fills or futures proxies.

The BTCUSDT perpetual is present in a broader accepted Binance hourly store.
The source includes base volume, quote volume, and trade count. The store
readiness evidence records 7,883 exchange gap hours and 18 unavailable
historical symbol-months across the broader dataset. The catalog audit did not
verify BTC-specific funding history, fee tier, margin, or liquidation rules.
It does not qualify a perpetual backtest.

At least one qualified price-only CFD source is available for later work:
`index_minute_NQ`, which is a Dukascopy NAS100 CFD series. It is not an NQ
futures dataset. B1/B3 still require the original PDF, a frozen CFD contract,
verified trading sessions, costs, and an executable source window.

## Changes and verification

- Updated live-store expectations to match current canonical aliases and source
  symbols.
- Added data-free fixture checks for negative authority, qualification, and
  futures-identity gates.
- Made readiness reads fail closed when the audit names an old catalog.
- Kept real-store tests marked `data`; fixture tests run without the live store.

**Next question:** Can the original strategy PDF be made available so that one
price-only rule and its required decision/fill times can be frozen against the
qualified NAS100 CFD source? Until then, this audit does not authorize a
strategy trial.
