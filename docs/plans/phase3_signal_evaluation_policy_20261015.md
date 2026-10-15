# Execution plan: Phase 3 signal-evidence gate for MVP research

**Status:** Implemented and verified on VPS (2026-10-15).
**Repository:** `/home/quant/dev/quant/quant-research`.
**Starting HEAD:** `dd11af4` on `local-first-main-sync-20261014`; `origin/main` at `144132cd` when inspected.
**Scope:** Research operating documentation and narrowly scoped documentation regression checks. Preserve unrelated dirty/untracked research.

## Objective

Make ResearchPhase 3 a documented, pre-backtest evidence boundary for each *new* MVP research session. Distinguish (a) signal/economic predictiveness, (b) execution/backtest correctness and (c) later chronological Validation mode. Choose evidence appropriate to the actual strategy, rather than mandating cross-sectional IC or machine learning for price-only rules.

## Implementation steps

1. **Freeze the Phase 3 plan before observing outcomes.** Amend `docs/research_sessions.md` with the predeclared diagnostic question, baseline, decision/availability clock, forecast/label horizon, costs feasibility, overlap/dependence policy, criteria, holdout restrictions and dedicated `diagnostic` trial declaration. Do not expand `SessionSpecV1` or re-freeze existing sessions.
2. **Make Phase 3 explicit in the MVP operator contract.** Update `docs/research_operations.md` default mode, stage descriptions, copy-ready prompt, default decision sequence, mandatory report, and strategy-specific routing. A completed Phase 3 record must precede a normal full backtest. The documented exception is an explicit predeclared `NOT_APPLICABLE` outcome with a reason a bounded native execution test is more diagnostic.
3. **Define one small evidence template.** Add `docs/phase3_signal_evaluation_template.md` to capture `PASS`, `FAIL`, `INCONCLUSIVE`, or `NOT_APPLICABLE`, precise signal/fill clock, baseline, key statistics, dependence, costs and limits. Require immutable result artifacts under `run_log/diagnostics/<session_id>/` (outside the session control directory) and register them with the existing `scripts/research_session.py record` interface. A terminal record means the artifact exists, not that the diagnostic passed.
4. **Make the guide visible to agents.** Add a short cross-reference in `AGENTS.md` without duplicating the detailed methodology or changing agent ownership/approval policies.
5. **Verify and publish.** Add compact contract regression tests covering all statuses, honest exceptions, trial/artifact paths and holdout guardrails. Run scoped tests and diff checks; stage only task-owned files; commit and publish without including the unrelated four existing local commits or dirty/untracked work.

## Decision semantics

- **PASS:** Frozen signal-level criteria pass. Phase 4 native backtest is justified, but profit and deployability remain unknown.
- **FAIL:** Frozen signal-level economic falsifier passes its evidentiary requirements against the thesis. Stop normal Phase 4 research and report `REJECT`; do not rescue by tuning.
- **INCONCLUSIVE:** Evidence is too weak/invalid to decide. Record why and stop or run a previously justified bounded **native** execution experiment where it resolves the uncertainty. Never relabel this as Phase 3 `PASS`.
- **NOT_APPLICABLE:** A prespecified fixed-horizon/IC screen would not test the stated payoff mechanism (for example path/queue-dependent exits). Record the pre-result reason and the smallest native execution trial required. This is a documented exemption from the screen, not an economic pass.
- **Existing/retrospective research:** Preserve previous verdicts. Any post-backtest signal study is retrospective evidence, not preregistered validation.

## Guardrails and non-goals

- No universal numeric IC, hit-rate or PnL threshold. The frozen strategy thesis sets the criteria.
- No new backtest engine, database, model, registry schema, services or runtime hard gate.
- No protected final holdout access, new trading orders, publication of credentials, or edits to existing frozen specifications.
- Use native ML4T diagnostic primitives where applicable; a single-asset event study need not be cross-sectional IC.
- Report docs-policy enforcement honestly: this work improves the agent operating contract, not a newly implemented runtime `RunPermit` rule.

## Acceptance checks

1. New sessions can follow Phase 1-2 -> Phase 3 evidence decision -> Phase 4 native execution -> Validation/Promotion, with no invented mandatory model stage.
2. The four terminal Phase 3 decisions and fail-closed outcomes are unambiguous.
3. N/A and inconclusive allow only justified, bounded native execution while explicitly preserving uncertainty.
4. The session v1 `diagnostic` record process uses existing accepted artifact paths; no new schema keys.
5. All targeted regression tests pass and no unrelated diff is staged or committed.

## Execution evidence

- Added one documented Phase 3 operating decision and one reusable evidence template.
- Reused the existing diagnostic trial / external artifact recording process. No new SessionSpecV1 fields, runner or native backtest code.
- Verified `62 passed` in `tests/test_phase3_signal_evidence_policy.py`, `tests/test_research_session.py`, and `tests/test_market_scope_policy.py` (three upstream SHAP deprecation warnings).
- Scoped Ruff lint and formatting, plus `git diff --check`, passed.
- This plan does not claim a hard runtime RunPermit enforcement check. It defines the mandatory agent operating policy and a regression-tested record route.
