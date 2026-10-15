# Agent-first ML4T research: human operating guide

**Audience:** Research owner using ChatGPT Web as the principal research engineer, with optional coding-agent support.
**Scope:** `/home/quant/dev/quant/quant-research`. Use this guide for new strategy ideas, research continuation, and promotion decisions.

This guide defines an **operating policy**, not new CLI commands, automatic gate bypasses, or a claim that every recovery feature is implemented. The current repository contracts, `AGENTS.md`, `docs/research_sessions.md`, market policy, and frozen session evidence remain authoritative.

## 1. Default workflow: three modes

| Mode in the prompt | Use when | Minimum work | Research-lead decision |
| --- | --- | --- | --- |
| **MVP Research** (default) | A new hypothesis or published strategy needs a cheap reality check | One testable economic hypothesis, source identity, baseline, falsifier, bounded trial, native/approved features, native executable backtest where relevant, costs, causal fills, independent audit, trial record | **REJECT / INCONCLUSIVE / VALIDATE** |
| **Validation** | An MVP survives its predeclared economic and technical gates | Chronological development/validation split, source and session robustness, cost stresses, relevant subperiod/regime analysis, uncertainty, selection/trial accounting and independent audit | **REJECT / REVISE AS A NEW TRIAL / PROMOTION CANDIDATE** |
| **Promotion** | A validated candidate may justify final-test, paper, or deployment preparation | All applicable seven ResearchPhases; frozen selection rule, independently verified holdout procedure, full reproducibility, risk and execution controls, paper evaluation when appropriate | **REJECT / BLOCKED / APPROVED FOR THE NEXT EXPLICITLY AUTHORIZED GATE** |

**Do not ask the user to approve each research phase.** Use one prompt for an autonomous bounded program. Escalate only when the proposed action changes the economic thesis, uses a protected holdout, trades capital, requires unavailable critical source/credentials, or performs destructive work. A research-process pass does not imply a profitable strategy or trading approval.

**Default stopping rule:** If a properly audited MVP fails its predeclared economic falsifier, report **REJECT** and stop costly validation. Do not tune until Sharpe is positive. Record changes prompted by outcomes as new trials, not retroactive corrections to the original experiment. If evidence is invalid, report **INCONCLUSIVE** or **BLOCKED** instead of forcing a number.

### Relationship to the original seven phases

These are still the repository's **ResearchPhases**:
1. Thesis.
2. Data.
3. Alpha/event study (only diagnostics relevant to the thesis).
4. Backtest.
5. Chronological validation.
6. Robustness.
7. Independent audit and decision.

MVP completes the required *safety and research validity checks* from these phases at small scope; it does not claim that advanced Phase 5 or Phase 6 evidence exists. Validation deepens the relevant tests. Promotion requires the full applicable gates. The seven **PipelineStages** in `src/pipeline.py` are a separate implementation taxonomy. Do not require ML modeling, cross-sectional IC, CPCV, or labels for a price-only single-instrument thesis unless they help answer the actual question.

## 2. Who does what

| Owner | Authority |
| --- | --- |
| **Human** | Supplies the thesis or strategy and constraints; authorizes protected holdouts, material hypothesis changes, capital, credentials, and destructive actions. |
| **Gemini thesis author (optional)** | Develops economic hypotheses and draft rules. Its handoff is research input, not an approved execution permit or verified native API contract. |
| **ChatGPT Web principal engineer and research lead** | Inspects the real repository and data; resolves necessary implementation details; registers experiments; implements native ML4T features and backtests directly through DevSpace; tests, debugs, audits evidence, and makes the final research decision. Owns the end-to-end work. |
| **Codex (optional executor)** | Handles bounded long-running, computationally heavy, or independent tasks when this offers a clear advantage. Codex does not take over the main engineering or research decision by default. |
| **Specialist subagents (optional)** | Perform narrow independent checks, such as numerical parity, execution timing, cost assumptions, and cash/equity reconciliation. ChatGPT integrates and verifies their findings. |
| **tmux / existing control plane** | Persistent bounded jobs, frozen research identities, `RunPermit`, append-only attempts, `Casefile` and fail-closed checks. Do not claim interrupted same-attempt recovery unless verified in the installed revision. |

ChatGPT is the final research verifier. A worker's message that it is finished is not evidence. **No live orders** follow from an MVP, Validation, or Promotion result without separate explicit authorization.

## 3. What to put in a new research prompt

Only the following are normally needed:

- **Mode**: `MVP Research`, `Validation`, or `Promotion`. Omit it to default to MVP.
- **Strategy / source**: Plain rules, published URL/PDF, or economic hypothesis; attach the original document when fidelity matters.
- **Market**: Instrument(s), venue/broker and product class (CFD, perp, spot, futures).
- **Timeframe and evaluation window**: Specify when known; otherwise tell the research lead to choose from *eligible development data*. Do not infer unseen holdout status from dates.
- **Constraints**: Long/short permission, costs, sizing, portfolio/prop limits and any disallowed data/approaches.

The agent derives implementation details from installed library APIs, actual canonical store, repository contracts and source evidence. Do **not** ask the human to manually specify `FeatureGateway`, full YAML, feature signatures, or seven separate phase prompts.

### Copy-ready prompt: new strategy (default MVP)

```text
Mode: MVP Research.
Strategy/source: [rules, PDF, link, or hypothesis].
Market/instrument: [instrument, venue and product type].
Timeframe: [timeframe].
Evaluation: [development dates, or choose eligible local development data].
Constraints: [sides, sizing, costs, exclusions; no live trading].

Act as research lead and orchestrator. Inspect the current repository,
AGENTS.md, past trials, canonical data and matching ML4T skills first.
State the economic mechanism, baseline, falsifier, exact source, causal
signal/fill clock, realistic cost assumptions and smallest decisive trial.
Freeze a bounded research session and trial BEFORE observing outcomes.
Implement and test through DevSpace directly as ChatGPT Web where practical.
Use Codex only for bounded heavy or independent tasks, not as the default owner.
Use verified ml4t-engineer features or certified extensions and genuine
ml4t-backtest execution; do not substitute a homemade simulator.
Independently audit source, feature proof, timing, session hours,
sizing, fills, costs, cash/positions/equity and attempts.
Report trade count, win rate, net expectancy/PnL, daily-equity Sharpe,
Calmar, max drawdown, period breakdown, cost stress and uncertainty
when estimable; label undefined or unverified metrics rather than inventing.
Preserve failures and all trial identities. Do not access protected holdout.
Fix routine failures and continue autonomously within the frozen thesis.
Conclude REJECT, INCONCLUSIVE or VALIDATE with evidence.
Only promote a scientifically valid, economically promising candidate
to a separately accounted validation program. No live orders.
```

### Copy-ready prompt: Gemini thesis to native ML4T MVP

When Gemini has already researched the economic thesis, use the
[Gemini-to-ML4T implementation prompt](prompts/gemini_to_ml4t_mvp.md)
instead of commissioning a second literature review.

Gemini supplies the thesis and draft rule specification. **ChatGPT Web is the
principal engineer and research lead**: it verifies implementation-critical
assumptions against local data and installed ML4T APIs, implements and executes
the registered MVP through DevSpace, audits broker evidence, and makes the final
research decision. Codex is optional for bounded heavy or independent work.

```text
Mode: MVP Research.
Input: Attached Gemini research brief and thesis YAML.
Repository: /home/quant/dev/quant/quant-research

Execute the workflow in docs/prompts/gemini_to_ml4t_mvp.md.
Act as principal engineer and researcher. Do the feature engineering,
native ML4T backtest, tests, debugging, independent audit, and final
research decision directly through DevSpace when practical.
Use Codex selectively, not as the default main worker.
Continue until REJECT, INCONCLUSIVE, or VALIDATE. No live orders.
```

The workflow does **not** re-run Gemini's thesis discovery by default. It
still verifies source identities, native API support, causal timing, costs, and
frozen trial integrity. These technical gates cannot be bypassed by an external
research brief. Preserve the existing seven ResearchPhases and the separate
Validation and Promotion permissions.

### Follow-up prompt: deeper validation

```text
Mode: Validation.
Continue session: [session ID, issue, or research artifact].
Inspect the actual Casefile, frozen spec, all known attempts, logs, tmux
and previous results. Do not start a duplicate job or recreate a session.
Plan the smallest chronological OOS and robustness checks justified
by the MVP, predeclare their trials and cost stresses, and use only
authorized development/validation data. Preserve the protected final test.
Run native validation, independently verify key results and compare against
the frozen falsifier. Report REJECT, REVISE AS NEW TRIAL, or PROMOTION CANDIDATE.
```

### Follow-up prompt: final qualification

```text
Mode: Promotion.
Candidate: [session ID].
Review the complete seven-ResearchPhase evidence and trial ledger.
Independently verify the frozen source/feature/execution contracts,
selection criteria, costs, robustness, uncertainty and reproducibility.
If a protected final test must be opened, STOP and obtain explicit approval
before any access. Do not relabel observed data as unseen.
Specify a separate paper evaluation and broker-specific execution
qualification before any proposal for live deployment.
Return REJECT, BLOCKED, or APPROVED FOR THE NEXT AUTHORIZED GATE.
```

## 4. Daily operations and recovery

Run from the project root. These commands are **implemented read-only entrypoints**, not an autonomous `research run` command:

```bash
uv run python scripts/research.py doctor
uv run python scripts/research.py doctor --session <session_id>
uv run python scripts/research.py status --session <session_id>
uv run python scripts/research.py casefile --session <session_id>
uv run python scripts/research.py discover --feature adx
uv run python scripts/research_session.py report --session <session_id> --root .
```

Before continuing existing work, inspect the *actual* `git status`, remote `main`, active agent/tmux sessions, existing attempt records, frozen inputs, logs and artifacts. Reuse a valid workspace and live job. Do not restart a run because the agent interface timed out. If visibility is unknown, fail closed and investigate.

For a **new** registered research session, the executor uses the existing `scripts/research_session.py init/check/record/report` interfaces and the typed contract/`RunPermit` flow. A frozen session is immutable. New economic choices require a new registered session/trial. `scripts/research.py resume` is a **read-only inspection** command; it does not itself launch or recover jobs.

A real process is not complete because tmux shows it running, and a hash match is not proof that a result was produced by the approved engine. Verify native fills, cash, equity, costs, identities, casefile, attempted trials, and final HEAD before claiming a pass. An expired lost worker is not a successful completed attempt; retain terminal failures and count genuine retries.

## 5. Required report and decision

Write a concise report with these dimensions **separately**:

1. **Source and clock**: dataset/vendor/product identity, coverage, timezone, missing bars and data qualification.
2. **Method and feature proof**: native API/extension semantics, numerical parity, warmup, availability and lookahead checks.
3. **Execution correctness**: real native fills, entry/exit clock, broker session, spread/slippage/commission/financing, sizing and independent cash/equity audit.
4. **Economic evidence**: trade count, win rate, expectancy, Sharpe/Calmar/drawdown on a stated daily clock, yearly/regime performance, costs, uncertainty and selection bias where supported.
5. **Research control**: frozen spec/permit/attempt IDs, failed and inconclusive trials, holdout integrity, Git HEAD/CI, blockers and limitations.
6. **Decision**: **REJECT / INCONCLUSIVE / VALIDATE** (MVP), **REJECT / REVISE / PROMOTION CANDIDATE** (Validation), or **REJECT / BLOCKED / NEXT GATE AUTHORIZED** (Promotion).

**Separate:** (a) the correctness of the *research process*, (b) evidence of profitable expected return, and (c) actual broker/execution readiness. A negative strategy PnL can be a correct and useful research result.

## 6. Choosing the smallest useful amount of work

- **Published rules / mechanical breakout / single product:** Start with native price + session feature proof, next-bar execution, explicit costs and a small bounded backtest. Do not invent machine-learning labels.
- **Cross-sectional rank or factor:** Add relevant source-universe proof, group-aware features and appropriate diagnostics such as IC or quantile turnover before expensive trading simulation.
- **ML prediction:** Add point-in-time feature/label checks, chronological out-of-sample prediction and selection-aware validation when a real model is justified.
- **Tick/limit-order market making:** Use an event/queue-aware execution engine and L2/tick data if fill realism requires it. Bar-only fills do not prove queue position.
- **Macro/alternative data:** Establish publication timestamps, revision policy, missingness and point-in-time joins before claiming an edge.

A prompt that says **MVP Research** means *smaller scope*, never weaker source integrity, lookahead controls, trial accounting, or independent audit.

## 7. References and boundaries

- [Thesis/session authority](research_sessions.md)
- [Agent control plane: research phases versus pipeline stages](architecture/agent_research_system.md)
- [CFD/perpetual policy](architecture/market_scope_policy.md)
- [Approved staged implementation](plans/agent_research_system_rollout.md)
- [M8 qualification plan](plans/agent_research_m8_qualification.md)
- [Research contracts and permit interfaces](architecture/research_contracts.md)

This document is the human operational entrypoint. It does not replace any frozen economic spec, vendor policy, repository contract or mandatory ML4T skill.
