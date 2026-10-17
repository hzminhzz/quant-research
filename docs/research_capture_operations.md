# Research source capture

`scripts/research_capture.py` records source material as descriptive evidence.
It does not produce a `CandidateSpec`, approve research, run a backtest, or
grant holdout access.

Capture one Markdown, text, JSON, YAML, or two-file handoff:

```sh
python scripts/research_capture.py capture research_inbox/<id> --out /path/to/captures
python scripts/research_capture.py batch research_inbox --out /path/to/captures
python scripts/research_capture.py verify /path/to/captures/capture_<hash>.json
```

Each report contains clause-level presence, resolution and source anchors,
unresolved blockers, source identity, and an unkeyed report checksum. The
checksum detects accidental modifications, not a deliberate rewrite. Pin the
report file's SHA-256 in an independently controlled record and verify it with
`verify <report> --expected-report-sha256 <digest>` when authentication matters. Original
UTF-8 bytes are copied under `sources/<source-hash>/` and checked by `verify`.
Existing reports are immutable; changed sources create new identities. Inputs
are bounded to 512 KiB per source file. Symlinks, duplicate YAML keys, unsafe
YAML tags and unexpected handoff files are rejected.

Safely batch-capture an archive of paired folders:

```sh
python scripts/research_capture.py archive ats_theses_all_62_cycles.zip --out /path/to/captures
```

ZIP intake accepts only paired `folder/thesis.yaml` and `folder/brief.md`
files. It validates the whole archive before writing, preserves the original
ZIP by SHA-256, and writes immutable member copies and one report per folder.
Limits are 128 MiB compressed archive, 2,048 entries, 64 MiB expanded total,
512 KiB per file, and a 200:1 per-member compression ratio. Paths must be
ASCII relative paths; links, special/encrypted entries, duplicate paths,
unsupported compression, extra members, invalid UTF-8 and malformed YAML are
rejected.
To verify a folder report, use the normal `verify` command; it also checks the
preserved ZIP bytes against the recorded archive hash.

Nested fields are indexed with exact YAML paths and line evidence. Exact clause
names can be matched at any depth. A small set of likely aliases is surfaced as
an unresolved mapping for review; it is never silently treated as equivalent.
Fields under `identity`, `markets_and_data`, and
`deterministic_strategy_specification` are retained in the report even when no
flat clause maps to them. This preserves the economic idea and its evidence
without inventing executable rules.

Every intake report is `THESIS_CAPTURED`, including structurally complete
ones. The `descriptive_sections_complete` field is informational; source
understanding, semantic fidelity and `RESEARCH_READY` need separate evidence
review and are never inferred merely from field presence. Executability,
backtest qualification and trading approval remain separate ATS decisions.
Default captures write to a sibling `.research_captures/` directory, never
inside the two-file source folder, so repeated capture remains idempotent.

See [the qualification report](research_capture_qualification_20261017.md) for
the seven published handoffs and the strict executable-ingest comparison.
