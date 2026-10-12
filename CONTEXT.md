# Research domain language

**Status:** Canonical language for research system design, 2026-10-12.
This file defines terms, not architecture, implementation, thresholds, or
future work. Related terms must retain the same meaning across documents,
agents, reports and software. When a source uses an older ambiguous term,
state which meaning is intended.

## Research intent

| Term | Meaning and useful distinction |
| --- | --- |
| **Thesis** | Falsifiable claim about an economic or market mechanism; not an indicator recipe. |
| **Falsifier** | Predeclared observable evidence that would reject the thesis within a stated scope. |
| **Research Session** | One frozen research intent and its declared trial set. It does not authorize live orders. |
| **Research Phase** | One step in the thesis-to-decision research process, such as alpha diagnostics or chronological validation. Not the same as a pipeline stage. |
| **Pipeline Stage** | Technical transformation such as labeling, feature computation, modeling, or backtesting. A thesis may not require every stage. |
| **Research Capsule** | The logically linked thesis, data, features, plans, trial attempts, evidence, verification and scoped decision for a research question. Not necessarily one physical file. |
| **Research Contract** | Explicit, machine-checkable agreement about required inputs, calculations, assumptions, timing and outputs. |
| **Capability** | An observed and qualified ability of a dataset, library or executor, with scope and evidence. Not an agent's belief or promise. |

## Market data and time

| Term | Meaning and useful distinction |
| --- | --- |
| **Data Source** | Named producer, venue or vendor together with exact product and data semantics. A symbol alias alone is not a source. |
| **Catalog Authority** | Designated source of truth for which dataset identity and qualification a consumer may use. |
| **Source Qualification** | Evidence that a dataset meets a specific research requirement. One dataset may qualify for price-pattern analysis but not execution simulation. |
| **Data View** | Bounded, time-qualified selection from a source, including its accepted sessions and exclusions. |
| **Price Proxy** | Price series used to test a hypothesis about a different or not-directly-tradable product. Its returns are not automatically executable returns. |
| **Tradable Instrument** | Specific product that can actually be ordered, with venue, contract, price increment, settlement, and executable session. |
| **Continuous Future** | Vendor-defined series assembled from multiple expiring contracts. It is not itself a dated contract. |
| **Volume Semantics** | What the numeric volume field represents: executed units, contracts, quote/tick activity, modeled values, or unknown. |
| **Bar Timestamp** | Time label attached to an OHLCV interval; it may mean bar start or completion. |
| **Availability Time** | Earliest time at which every input needed for an observation is known to the strategy. |
| **Decision Time** | Instant at which the strategy may act on eligible information. |
| **Fill Time** | Instant when a native engine or venue actually records execution; it cannot precede the required information and order placement. |
| **Market Session** | Venue/calendar-defined trading interval. Distinct from a research session. |
| **Holdout** | Period reserved for a final, precommitted assessment. It ceases to be unseen when exposed, regardless of later renaming. |
| **Exposure** | Fact that observations, outcomes or selection feedback from a period have already influenced research. This cannot be undone by changing an ID. |

## Features, signals and execution

| Term | Meaning and useful distinction |
| --- | --- |
| **Feature** | Bounded, deterministic derived observation with defined inputs, math, availability and identity. |
| **Native Feature** | Feature whose exact semantics are supplied and verified by an installed feature-engineering library. Matching a name alone is insufficient. |
| **Feature Extension** | Reviewed implementation of semantics the installed native catalog cannot supply exactly. It has the same evidence obligations as a native feature. |
| **Feature Set** | Named collection of feature requests and their resolved implementations, with shared source/time semantics. |
| **Feature Proof** | Evidence of source mapping, execution provenance, numerical semantics and causal availability for feature outputs. |
| **Signal** | Decision-ready observation or state transition derived from eligible features. A signal does not itself constitute an order. |
| **Order** | Instruction to trade a specified instrument under defined price and time conditions. |
| **Fill** | Simulated or real completion of some or all of an order; a candle touching a limit is not proof of a real fill. |
| **Execution Model** | Explicit rules and assumptions by which signals become orders, fills, cash movements and risk exposure. |
| **Execution Proof** | Independent evidence that simulated order sequencing, positions, fills, costs and accounting meet their declared invariants. |
| **Cost Assumption** | Modeled fee, spread, slippage, impact or financing value; it remains an assumption until supported by product-specific evidence. |

## Trials, evidence and decisions

| Term | Meaning and useful distinction |
| --- | --- |
| **Trial** | Declared alternative or research question whose observed result can affect selection. Failed and negative variants still count. |
| **Attempt** | One concrete execution of a trial, including crashes, partial outputs and retries. |
| **Artifact** | Persisted output of an operation, with identity and scope. Its existence does not prove correctness. |
| **Evidence** | Artifact plus relevant provenance and checks that support a specific, limited claim. |
| **Gate** | Mechanically evaluated prerequisite for an operation or conclusion; passing one gate does not imply all other gates passed. |
| **Run Permit** | Authorization for one bounded execution with specified data, code, time, side effects and resource limits. |
| **Verification** | Independent checking of an output against declared invariants and source facts. Different from plausibility review. |
| **Research Decision** | Scoped interpretation of evidence: reject, inconclusive, or supported within observed conditions. |
| **Deployment Approval** | Separately authorized permission to use a strategy in a live environment. Research completion or profitability never grants it automatically. |
| **Casefile** | Agent-facing, regenerable view of the authoritative record and next safe action. Memory and summaries cannot override evidence. |
| **Blocker** | Unmet prerequisite with a named reason and a safe remedy or explicit external dependency. |
| **Uncertainty** | Known limits on what evidence can establish, including sample variance, missing data, selection bias and execution realism. |

## Status distinctions

- **PASS:** The stated mechanical check succeeded. It is not approval.
- **COMPLETED:** The operation or trial attempt terminated with an artifact.
  It does not imply the thesis succeeded.
- **FAILED:** A declared operation or verification did not meet its contract.
- **BLOCKED:** A prerequisite or permission prevents valid progress.
- **INCONCLUSIVE:** Evidence is insufficient to choose between competing
  research interpretations; the operation itself may have completed.
- **RUNNING:** A worker is active; no result is implied.
- **NOT_APPROVED:** No live deployment authorization has been established.

A report must identify the **object whose status is stated**. For example:
`source qualification: PASS` and `deployment: NOT_APPROVED`
can both be true.
