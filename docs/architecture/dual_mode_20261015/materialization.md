# Bounded vault materialization

`PanelBuilder.build` discovers the deterministic intersection between the
consolidated `crypto_futures_ohlcv_1h_BINANCE_UM_PERP/symbol=*` tree and
`crypto_futures_funding_*_PERP` directories. Other layouts and unmatched source
names remain visible as exclusions. Directory discovery does not prove full
delisted-symbol or archive completeness.

Builds process one symbol, partition and calendar month at a time. This bounds
the working panel to one source month (funding scans include the two day lookback
needed at month boundaries). Development rows end before `protected_test_start`;
trusted ingestion writes protected rows beneath a separate `protected/` tree.
For the governed snapshot, use development `2019-10-01` through exclusive
`2026-01-01`, then trusted ingestion through exclusive `2026-10-01`.

Each completed slice has an immutable output and a durable receipt under
`.checkpoints/`. Receipts bind the input identity and build parameters to the
output SHA-256 and row counts. Resume verifies these before reusing a slice.
Missing outputs, hash mismatches, corrupt receipts and unreceipted output files
are rejected; completed slices are not rewritten. If a crash occurs *after* a
Parquet publication but *before* its checkpoint receipt is durable, the orphaned
file is intentionally not adopted automatically. Explicit source-and-content
reconciliation is required; this rare publication gap remains a hands-off
resume limitation rather than silently accepting unverifiable data. The final manifest is written
atomically only after the pass finishes. Source or mark gaps remain explicit
exclusions or funding-sidecar missing marks; they are never filled with invented
coverage. Funding sidecars preserve source event timestamps and mark provenance.

The canonical price table retains exactly twelve consumer columns. Source
hashes, event and availability clocks, funding timestamps, and known vintage
limitations remain in provenance and sidecars. This receipt system detects
accidental corruption and supports cooperative resume; it is not an authority
boundary against the filesystem owner.
