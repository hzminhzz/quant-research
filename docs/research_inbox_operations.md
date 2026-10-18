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
publisher `scripts/research_source_publication.py`. After the candidate pairs
are staged, checked for source novelty, and committed on a clean task-owned
`research/<name>` branch based on current `origin/main`, run:

```sh
.venv/bin/python scripts/research_source_publication.py publish --factory ml --run-id <unique-hourly-invocation-id>
# Valid no-new-source outcome after a documented screen:
.venv/bin/python scripts/research_source_publication.py no-op --factory general --run-id <unique-id> --reason 'all sourced candidates were duplicates'
```

Use `--repo PATH` for the isolated checkout; use the Python interpreter from the
main repository's virtual environment if the worktree has none, with
`PYTHONPATH` set to the checkout root. The script checks committed new two-file
pairs, strictly validates flat handoffs or source-only admission, refreshes
remote research refs to detect candidate-ID collisions, and refuses stale
main bases, unsafe paths, modified existing sources, remote ref collisions,
merged histories and dirty tracked work. It non-force-pushes only the chosen
research branch, reconciles ambiguous push responses against exact remote SHA,
and verifies both file hashes before returning `REMOTE_PUBLICATION_VERIFIED`.
A successful schema check is **not** ATS ingestion, model training or execution
approval. Mechanism-level novelty still requires research review.

Each invocation writes an exclusive, fsynced JSON receipt to the shared main
checkout `run_log/source_publications/<factory>/`, regardless of success,
publication block or no-op. The receipt includes run identity, timestamp,
branch, code/source hashes, transport attempts, remote SHA, verification,
reason, and zero authorized scientific/protected/order effects. Exit codes:
`0` verified publication or explicit documented no-op, `2` publication blocked,
`3` receipt persistence failed. `NOT_PUBLISHED` is *never* a success. Preserve
failed drafts and use a new invocation ID for each retry; receipts are immutable.
Do not run this command for the ATS scientific runner, merge to main, or infer
canonical queue admission merely because a remote discovery branch exists.
Future hourly discovery must publish exactly `research_inbox/<candidate_id>/`
with `thesis.yaml` and `brief.md`, and must not claim a valid handoff when the
validator is unavailable or rejects the input.

This command is separate from `quant.py ingest`, which translates a complete
cross-sectional thesis into an executable `CandidateSpec`. Handoff validation
does not establish source claims, qualify data or costs, authorize a backtest,
approve execution, or grant trading authority. Keep the unverified status and
limitations visible; resolve blockers through the normal research evidence
process before considering any later stage.
