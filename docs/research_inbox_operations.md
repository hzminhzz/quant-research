# Research inbox handoffs

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
Future hourly discovery must publish exactly `research_inbox/<candidate_id>/`
with `thesis.yaml` and `brief.md`, and must not claim a valid handoff when the
validator is unavailable or rejects the input.

This command is separate from `quant.py ingest`, which translates a complete
cross-sectional thesis into an executable `CandidateSpec`. Handoff validation
does not establish source claims, qualify data or costs, authorize a backtest,
approve execution, or grant trading authority. Keep the unverified status and
limitations visible; resolve blockers through the normal research evidence
process before considering any later stage.
