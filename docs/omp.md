# OMP for quant research

Start OMP from this repository:

```bash
/home/quant/.bun/bin/omp --cwd /home/quant/dev/quant/quant-research
```

OMP reads `.omp/config.yml` as the project configuration. Global credentials,
provider selection, model roles, and interface settings remain unchanged.
The configuration targets the installed OMP version, 18.4.0.

## Research configuration

- Use high reasoning effort for the main session.
- Limit worker concurrency to four. This limits simultaneous work on this
  eight-core machine. It is a starting limit, not a performance benchmark.
- Use the project's Python environment and a persistent Python kernel.
- Show diagnostics after edits. Read full source text without automatic summaries.
- Save compaction handoffs to disk.
- Discover project skills. Read applicable ML4T procedures before quant work.

The 61 official ML4T skills are installed under `.agents/skills/`.
They link to a pinned local checkout at
`/home/quant/.cache/ml4t-skills-f0ea019`.
Upstream revision: `f0ea01919e0c517cd9b1e014724a520facd8a742`.
The reviewed installer replaced no existing skills.
Keep that checkout while using these links. To move the project to another
machine, install the same revision there or use the official copy installer.
Do not update skills during a frozen experiment.

## Memory

OMP has built-in memory backends. This project selects Mnemopi, a local
SQLite backend, with project-scoped automatic retention and recall.
Embeddings and memory model calls are disabled. This configuration avoids
an embedding download or a separate memory service. Recall quality with
these settings is not benchmarked.

Memory helps recover preferences, decisions, failure causes, and next questions.
It is not the source of truth for market data, trial counts, or strategy results.
Use frozen session specifications and registered artifacts for those facts.
Treat recalled statements as references. Check them against current evidence.
Do not retain credentials, private keys, or raw licensed datasets.
Keep research outcomes marked `EXPLORATORY` or `NOT_APPROVED` as applicable.
Automatic retention does not guarantee that every decision is saved.
Record important decisions in the research session evidence.

Automatic skill generation is disabled. Changes to research procedures require
explicit review and evidence. Follow the ASD-STE100 writing rules in
`docs/research_sessions.md`.

## Apply the ML4T memory design

The [Chapter 24 memory notebook](https://github.com/stefan-jansen/machine-learning-for-trading/blob/main/24_autonomous_agents/03_state_and_memory.ipynb)
separates run state, tool traces, and long-term recall. Keep these layers separate:

| Layer | Purpose | Current implementation |
| --- | --- | --- |
| Working context | Information available to the model this turn | OMP context and compaction |
| Research run records | Frozen specification, declared trials, identities, and outcomes | Research-session CLI and registered artifacts |
| Tool trace | What was called, including failed and empty results | OMP session records; link relevant records to trial evidence |
| Long-term recall | Stable decisions and lessons across sessions | Project-scoped Mnemopi |

Before a handoff, record the current question, decisions, unresolved questions,
evidence references, and check results in a versioned research artifact.
Record retrieval time separately from publication or data-availability time.
Use a declared as-of time for historical analysis. Record unsuccessful searches.
When resuming, load the frozen specification and all recorded trial outcomes.
Verify identities before rerunning work. Append new decisions and checks.
Do not overwrite earlier evidence or treat already-observed data as unseen.

Before a research conclusion, inspect three properties:

- **Coverage:** The required evidence and benchmark are present.
- **Freshness:** Time-sensitive observations satisfy the declared age limits.
- **Cutoff consistency:** Evidence was available at the decision or forecast cutoff.

Choose these requirements for the thesis. The notebook's news-forecast defaults
are not universal strategy thresholds. If evidence is insufficient, report an
unresolved conclusion and name the missing evidence.

These are research instructions, not new automated gates. The current session
CLI checks file identities and declared data requirements. It does not implement
the notebook's full typed evidence state, freshness gates, or ablation replay.
Mnemopi retention and OMP handoff files do not fill that gap.
An executable extension should add explicit evidence timestamps, gate results,
checkpoint round-trip tests, and replay without live APIs. Test missing, stale,
post-cutoff, and conflicting evidence before relying on that extension.
