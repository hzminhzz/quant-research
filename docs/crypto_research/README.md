# Recurring Crypto Research Operator

This branch is the durable home for scheduled crypto-strategy discovery and backtesting.

## Safety boundary

- Branch: `research/crypto-auto`
- Never modify or merge `main` automatically.
- The source checkout at `/home/quant/dev/quant/quant-research` may contain unrelated dirty work. Preserve it.
- DevSpace worktrees do not contain git-ignored Parquet data. Use the configured external data root from `config/crypto_research.yaml`.
- Every strategy/parameter variant is a statistical trial. Preserve failures.
- The recurring operator must not consume sealed confirmation data.

## Sealed confirmation boundary

At infrastructure setup on 2026-09-28, `BTCUSD_5m_2022_2026.parquet` contained 478,914 rows from 2022-01-01 00:00 UTC through 2026-09-21 23:55 UTC.

Rows at or after **2026-09-22 00:00 UTC** are reserved for explicit manual confirmation. The recurring operator may detect that newer data exists but must not use its values for discovery, parameter selection, backtesting, ranking, or robustness tests.

## Persistent artifacts

- Registry: `run_log/crypto_research/registry.jsonl`
- Per-run structured evidence: `run_log/crypto_research/runs/`
- Operator state: `run_log/crypto_research/state.json`
- Human-readable reports: `docs/crypto_research/`

## Preflight

Run before every scheduled research cycle:

```bash
uv run python scripts/crypto_research_preflight.py
```

It must report `READY`.

During initial scaffolding only:

```bash
uv run python scripts/crypto_research_preflight.py --allow-dirty
```

## Run contract

One scheduled invocation researches one primary hypothesis and finishes with exactly one classification:

- `REJECT`
- `INCONCLUSIVE`
- `BLOCKED_DATA`
- `EXPLORATORY_PASS`
- `PROMOTE_TO_MANUAL_CONFIRMATION`

No scheduled run may declare a strategy production-ready or automatically trade/deploy it.
