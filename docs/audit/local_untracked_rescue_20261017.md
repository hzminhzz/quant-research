# Original-checkout untracked rescue — 2026-10-17

## Scope and verdict

**Verdict: PRESERVED (local-only).** The nonignored untracked content that the
original checkout had accumulated during the 2026-10-14/15 local-first session
was archived into version control on this branch. Nothing was modified,
rewritten or qualified. This record grants no research approval, holdout
release, deployment or live-trading authority.

| Identity | Value |
| --- | --- |
| Original checkout | `/home/quant/dev/quant/quant-research` |
| `main` before | `041477be` — `merge(ats): integrate ATS-0–8 with native dual-mode ML4T (#61)` |
| `main` after | `4ab8b1a6` — `feat: development-only ATS research inbox factory (#63)` (= `origin/main`) |
| Archive branch | `rescue/local-untracked-20261017` (= `main` plus one additive commit) |
| Archived files | 5705 pre-existing + this record (one commit) |
| Excluded local-only files | 84 (3 journals, 28 raw panels, 53 bulk equity dumps) |

## Observed state before the rescue

- `main` was one commit behind `origin/main`; no tracked file was modified or
  deleted, so the only worktree deviation was untracked content.
- `git status --porcelain` reported **932 untracked entries**, but that output
  collapses untracked directories. The true untracked file count under
  `-uall` was **5789**, of which **5705** remained after the 84 local-only
  exclusions below.
- Distribution of the 5705 archived files: `run_log/` 4549, `promote/` 442,
  `scripts/` 280, `docs/` 218, `config/` 98, `tests/` 96, `src/` 11,
  `ops/` 10, `SESSION_TEMPLATE.md` 1. By extension: 2782 `json`, 1798 `csv`,
  431 `py`, 243 `log`, 208 `md`, 105 `yaml`, 27 `png`, 24 `jsonl`, 22 `sh`,
  plus assorted text/exit-code/`.head` marker files. Total 341.2 MiB.
- Working-tree mtimes were 2026-10-14/15, i.e. these are leftovers of the
  earlier local-first session, not products of the `git pull` that moved this
  checkout onto the ATS-0–8 `main`.
- No hardcoded credential was found: the matches for `api_key`/`token`/`secret`
  in archived scripts are `os.environ[...]` reads, and the test fixtures use
  synthetic values.

## Provenance of the bytes

`refs/stash` (`e9980395`, "On main: pre-origin-main-integration-local-source-20261014",
2026-10-14 12:19) carries a third parent `16f1371f` — an *untracked files*
snapshot of 5,422 paths taken at that time.

| Class | Count |
| --- | --- |
| Archived paths also present in that snapshot | 5388 |
| — of which byte-identical | 5384 |
| — of which different | 4 |
| Archived paths absent from that snapshot | 317 |

The four diverging paths are `promote/INDEX.md`, `promote/one_bar_nq_30m/README.md`,
`scripts/run_one_bar_shadow_xyz100.py` and `tests/test_one_bar_shadow_xyz100.py`;
the working-tree bytes were archived. The 317 paths absent from the snapshot
were created later in the session (mtimes 2026-10-14 12:xx through 2026-10-15 09:xx).
The stash is a single local-only ref, so before this branch that snapshot was the
only git-side copy of the content it held, and the other 317 paths had none.

## Action taken

1. `main` fast-forwarded to `origin/main` (`041477be` → `4ab8b1a6`); no
   collision with untracked paths, no history rewritten.
2. Local-only artifacts were excluded from the archive and left on disk, hidden
   from `git status` by patterns appended to `.git/info/exclude` (local to this
   clone, not shared):
   - `/.propr_*.db` — 3 transient worker/intent journals.
   - `/data/hftbacktest/` — 28 raw exchange panels, ~22 GiB.
   - `/run_log/milkman_*/**/equity.csv` — 53 bulk equity dumps, 728.6 MiB.
   These are raw, transient or regenerable artifacts; retaining them in a source
   commit would violate the repository rule against committing raw panels and
   bulk run artifacts. Promote the patterns to `.gitignore` via a reviewed change
   if they should be shared. Archived content is the remaining 341.2 MiB.
3. The 5705 pre-existing paths, plus this record, were committed unchanged on
   `rescue/local-untracked-20261017`.
4. The main worktree was returned to `main`, so it is now clean and
   byte-identical to `origin/main`.

## What the archive is not

- It is **not** a qualification, a runnable-base guarantee, or a parity claim.
  Most archived scripts/configs were inventoried, not line-audited, and several
  refer to data partitions that are absent or local-only.
- It is **not** a substitute for the open gate in
  `docs/architecture/rebuild_20261015/verification.md`: legitimate original
  untracked dependencies still have to be reconciled deliberately (consumer
  review, parity evidence) before a supported base can be declared.
- Two tracked files in `main` keep path dependencies the clean tree does not
  satisfy: `scripts/ats7_notify.py:14` reads
  `ops/ml4t_monitoring/deploy/alertmanager.yml` (gitignored, retained on disk),
  and `tests/test_dukascopy_real_parity.py:31` reads
  `run_log/vwap_pullback_adx_dukascopy_20261012_v1/development`, which now lives
  only on this archive branch (that test is `-m data` and skips when the
  directory is absent). Restore any archived path with
  `git checkout rescue/local-untracked-20261017 -- <path>`.
- The 2026-10-14 stash still exists untouched; this branch does not replace or
  drop it.

## Verification

- `git status --porcelain` empty on `main` at `4ab8b1a6`.
- Archive branch tip is `main` plus exactly one commit;
  `git diff --name-status main..rescue/local-untracked-20261017` reports `A`
  entries only, with no modification or deletion of tracked paths.
- Archived content was staged from the working tree, so it equals the pre-cleanup
  bytes by construction; the four paths that differed from the stash snapshot
  are listed above.
- Byte comparison against `16f1371f` used a temporary `GIT_INDEX_FILE` seeded
  with `git read-tree 16f1371f` and re-added from the working tree, then
  `git diff-index --cached`; it is reproducible from this branch.
