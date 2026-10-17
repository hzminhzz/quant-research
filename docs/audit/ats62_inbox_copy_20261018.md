# ATS inbox — 62-thesis source copy (2026-10-18)

**Scope:** original-source duplication only. This is *not* executable thesis compilation,
source-claim verification, strategy qualification, protected market-data access, or
permission to place trading orders.

## Source identity and conservation

- Input: user-provided `ats_theses_all_62_cycles(1).zip` (copy only).
- Original ZIP SHA-256 (computed from uploaded bytes before transport):
  `8cb0e4be32aa52bcf6cf41e05d62c361e083e139a2fad8908ff397ba0ac0f349`.
- The original ZIP was **not moved or deleted**. The repository commits the
  original source *members*, not the ZIP binary.
- Transport: checksum-verified compact `tar.xz` containing identical original
  two-file member bytes, SHA-256
  `aa060becec59c2622a51cbc40d9eff3f793b4f475bc024e825c18871e82c7d00`.
  Transport used a gitignored VPS staging directory.
- Member-set digest (sorted relative filename / SHA-256 pairs):
  `e3b6dfd1dd2c8d4dbd770f3d85ce6ccc3062b01c0ef244933a6bbaae1f76dbfa`.
- Full **124 individual member SHA-256 fingerprints** recorded in
  [the machine-readable manifest](ats62_inbox_copy_20261018.json).

## Verified copy results

| Invariant | Observation |
| --- | --- |
| Input thesis pairs | 62 unique directories; one `thesis.yaml` and one `brief.md` each |
| Files newly copied to `research_inbox/` | 124 |
| Existing seven ATS handoffs overwritten | 0 |
| Resulting inbox folders | 69 |
| Resulting `thesis.yaml` files | 69 |
| Resulting `brief.md` files | 69 |
| Same-member re-import | 124 identical; 0 additional copies |
| Descriptive capture command | 69 `THESIS_CAPTURED` |
| Research-ready / backtest approved | Not claimed |
| Holdout reads / orders | None |

The 62 newly copied original sources have the nested research schema
(`identity`, `markets_and_data`, `deterministic_strategy_specification`,
etc.), not the seven older flat ATS handoff schemas. Their contents were **not
rewritten or normalized**. The legacy strict-handoff regression now scopes its
schema validation to the seven originally qualifying handoffs. The separate
capture path checks source preservation for the full inbox.

## Boundaries

The original archive remains in the user's uploaded files. Its exact
members are committed under `research_inbox/<source_id>/` on an isolated
feature branch. The source byte checks establish integrity, not validity
of source economic claims. These descriptive theses must not be handed
to executable `quant.py ingest` or to the execution queue without independent
schema/protocol qualification.
