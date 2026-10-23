# Research inbox handoffs

For the resumable, development-only batch queue, see
[Research Inbox Factory operations](research_inbox_factory_operations.md).

Use `python scripts/quant.py validate-handoff` to validate every published
candidate, or pass one staged candidate directory to validate it **before**
publication. Admission checks the exact two-file envelope, strict allowed
ATS thesis root vocabulary, required descriptive sections, stable identity,
unapproved status, non-placeholder source IDs and HTTPS references, duplicate
YAML keys, and local repository path references. CI runs the validator on the
published inbox. A successful result is `HANDOFF_VALID_UNVERIFIED`: it permits
research triage and implementation planning only. This is not
`quant.py validate` (an executable protocol), and is not a native backtest.

Source URL presence and syntax are not proof of source reachability, factual
claims or an independent reproduction. Any non-portable VPS data-catalog
inspection is retained rather than silently deleted, but counted under
`external_local_claims_unverified`; GitHub CI does not contain the VPS store.
The research lead must verify source claims and actual market provenance at
its proper gate. Preserve all raw sources, versions and adverse evidence.

Publish via an isolated research branch after a prepublication validator pass;
never overwrite an existing candidate or discard untracked staging evidence.

## Hourly source publication reliability CLI

The three descriptive thesis factories (general, crypto, ML) share the bounded
publisher `scripts/research_source_publication.py`. It is the publication step
only: it does not stage candidates, write theses or run science. Direct
execution by absolute path bootstraps this checkout itself, so it works when
`PYTHONPATH` contains only the pinned connector path (as in CI) and from any
working directory; no repository `PYTHONPATH` entry is required. Use
`--repo PATH` for an isolated checkout.

### Hourly integration contract (general, crypto and ML)

1. Create an isolated worktree/checkout on a clean task-owned
   `research/<unique-name>` branch based on the current `origin/main`. Fetch
   `origin` first; do not rebase or force-push an existing published branch.
2. Commit exactly `research_inbox/<candidate_id>/` pairs containing
   `thesis.yaml` and `brief.md`: 1-8 pairs, added files only, no merge commits,
   at most four commits over `origin/main`. Do not modify an existing candidate,
   do not discard raw sources or untracked staging evidence, and leave tracked
   worktree files byte-identical to the commit.
3. Run the publisher by absolute path from any working directory; pass the
   isolated checkout explicitly:

   ```sh
   <quant-research>/.venv/bin/python \
     <quant-research>/scripts/research_source_publication.py publish \
     --repo <isolated-checkout> --factory ml --run-id <unique-hourly-invocation-id>
   ```

4. Exit `0` with `REMOTE_PUBLICATION_VERIFIED` is the only publish success.
   The CLI has already verified the live base SHA, pushed without force, and
   re-read both payload hashes from the exact fetched remote commit. Do not
   merge the branch yourself.
5. When a factual screen found no novel source, record it instead of inventing
   a candidate:

   ```sh
   <quant-research>/.venv/bin/python \
     <quant-research>/scripts/research_source_publication.py no-op \
     --repo <isolated-checkout> --factory general --run-id <unique-id> \
     --reason '<what was screened and why nothing was novel>'
   ```

   A no-op requires no research branch and no clean worktree, and exits `0`
   with `NO_NOVEL_SOURCE`.
6. Exit `2` with `NOT_PUBLISHED` is blocked, never success. Read `reason` and
   `error_type`, preserve the branch and staging evidence, fix the stated cause
   and retry with a new invocation ID. Never bypass a block by deleting
   receipts, editing committed sources to match the worktree, force-pushing or
   publishing from a stale `origin/main`.
7. Exit `3` `RECEIPT_FAILED` means the outcome could not be durably recorded.
   Treat the invocation as unauthorized and unresolved even if the remote ref
   moved, and record manual recovery.

Before any push the script strictly validates the pair (flat capture,
source-only or nested source admission, or `HANDOFF_VALID_UNVERIFIED`), rejects
out-of-scope or incomplete pairs, dirty tracked work, unsafe branches and
non-descendant histories, prunes and refreshes only
`refs/remotes/origin/research/*`, refuses a candidate ID already present on
another remote research branch, and refuses an existing remote ref at a
different SHA. Ambiguous transport responses are reconciled against the exact
remote SHA; a stale base blocks instead of rebasing.

### Receipts and authority

Each invocation writes an exclusive, fsynced JSON receipt to the shared main
checkout `run_log/source_publications/<factory>/`, regardless of success,
publication block, no-op or unexpected failure. The receipt includes run
identity, timestamp, branch, head and base SHAs, candidate validation kinds and
per-file SHA-256, transport attempts, remote SHA, readback verification,
reason/error type, its own path, and zero authorized effects. Receipts are
immutable; never edit or delete one.

`REMOTE_PUBLICATION_VERIFIED` proves only that the bounded pair is committed and
readable at an exact remote research branch SHA. It is **not** ATS ingestion,
queue admission, model training, a backtest, a protected/holdout read,
deployment or trading authority; each of those requires its own gate
([factory operations](research_inbox_factory_operations.md)). Mechanism-level
novelty and source claims still require research review. A successful schema
check must never be reported as a valid handoff when the validator is
unavailable or rejected the input.

This command is separate from `quant.py ingest`, which translates a complete
cross-sectional thesis into an executable `CandidateSpec`. Handoff validation
does not establish source claims, qualify data or costs, authorize a backtest,
approve execution, or grant trading authority. Keep the unverified status and
limitations visible; resolve blockers through the normal research evidence
process before considering any later stage.
