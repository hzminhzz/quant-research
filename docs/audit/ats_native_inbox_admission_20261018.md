# ATS nested inbox admission — 2026-10-18

**Decision:** source admission and triage implemented; no source qualified for a
native trial. This is not an economic or execution qualification.

## Identity and source preservation

- Isolated branch: `feat/ats-native-inbox-admission-20261018`.
- Base: `origin/main` `4693f96a997c16ece0c66bdd334dba59678127e7`.
- Imported 62 original nested source directories from
  `origin/feat/ats-inbox-62-copy-20261018`, whose source commit is
  `8a5085b4c9c24f3d48f3dac3b32aacc71ee63521`.
- Retained the seven prior flat handoffs and the BTA flat handoff from base.
- Compared all 140 source files against Git blobs: **140 byte-identical, zero
  mismatches**, across 70 candidates.
- Source SHA manifest: `/tmp/ats-inbox-source-sha256.json`, SHA-256
  `7510519135679d77499be2510d1f729c22232cf4b788be82058a8b96ec321e8e`.
  Its canonical 140-file manifest digest is
  `f0562286a0fc99049199180823a6ba1e9a6b9f8d2750f09a524081795866eb0e`.

## Before and after

The supplied baseline for 69 sources was 62 `BLOCKED_HANDOFF`, seven
`BLOCKED_PROTOCOL`, and zero native runs. On `main`, BTA adds one flat event
handoff, giving the reconciled 70-source baseline of 62 schema rejections,
eight protocol blocks, and zero native runs.

The final corpus queue pass used a fresh `/tmp` state root and disabled local
market materialization:

| Measure | Count |
| --- | ---: |
| Captured / admitted | 70 / 70 |
| Nested sources | 62 |
| `BLOCKED_SPEC` / `BLOCKED_PROTOCOL` | 62 / 8 |
| Executable specs / trial starts / verified native runs | 0 / 0 / 0 |
| Stage 1 / 2 / 3 / 4 receipts | 0 / 0 / 0 / 0 |
| Protected reads | 0 |

Each nested source carries `UNRESOLVED_SOURCE`, `CONTRADICTORY_RULES`,
`UNAVAILABLE_DATA`, and `UNQUALIFIED_PROTOCOL`. The clock conflict is explicit:
an hourly source claims `NEXT_BAR` execution at `00:01`. No declared
development-vault manifest or typed nested-source compiler was available.
These are triage blockers, not falsifications. The old seven and BTA stay on the
strict flat path; BTA remains blocked for the existing ATS-4 hourly CFD stop
order/session/cost limitations.

Full queue report: `/tmp/ats-inbox-admission-report-final.json`, SHA-256
`25339f375aa887fe5cdcad88e5851a0de518788a11966e88e7421bd4cfb8679b`.
The queue journal and report contain no trial attempt or Stage 4 entry.

## Verification

- Inbox queue and strict handoff regressions: **39 passed**, three existing
  SHAP deprecation warnings.
- ATS-4 event protocol suite: **44 passed** before final queue-only changes;
  targeted BTA strict event-spec regression: **1 passed** after them.
- Synthetic native development-only Stage 3 positive fixture: **passed**.
- Synthetic native development-only Stage 2 falsification fixture: **passed**;
  Stage 3 and Stage 4 absent.
- Ruff on changed Python files and `git diff --check` excluding preserved source
  briefs: **passed**. The full diff check reports trailing spaces used for
  Markdown hard breaks in the original brief files; they were retained to keep
  all source bytes identical.
- The CLI Stage 2 fixture could not run in this container because Bubblewrap
  cannot create an unprivileged namespace (`ISOLATION_UNAVAILABLE`). The native
  Stage 2 outcome was verified in-process with `isolate=False`; no isolation
  fallback was enabled.

No current source has a complete, contradiction-free, source-verified,
development-data-backed native specification. Therefore no real-market Stage
1/2/3 run was justified. The native positive and negative tests use synthetic
fixtures only and make no economic claim.
