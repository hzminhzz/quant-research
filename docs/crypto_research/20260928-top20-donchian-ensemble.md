# Crypto Research Run - Top-20 Donchian Ensemble

## Conclusion

**INCONCLUSIVE.** The exact preregistered top-20 liquid Donchian ensemble again exceeded the 300-second command limit before returning development statistics. The retry used a loader-only optimization: one streaming panel scan replaced per-symbol parquet loading, while strategy rules, universe rules, sizing, costs, dates, and gates were unchanged.

## Hypothesis

Diversifying a fixed nine-horizon long-only Donchian trend ensemble across the dynamic top 20 liquid eligible crypto assets may stabilize idiosyncratic trend timing.

## Pre-Registration

The original manifest remains authoritative: `run_log/crypto_research/runs/20260928-top20-donchian-ensemble-manifest.json`.

No strategy parameter, lookback, universe threshold, cost assumption, or validation threshold was changed for the retry.

## Execution Evidence

- Original runner: timed out at 300 seconds.
- Resume runner: `scripts/run_crypto_top20_donchian_resume.py`.
- Resume change: data-loader optimization only.
- Resume outcome: timed out at 300 seconds.
- Exploratory OOS consumed: **no**.
- New statistical trials from retry: **0**.

## Decision

**INCONCLUSIVE**. Resume this exact specification only in an execution environment that can run longer than the current command limit; do not alter parameters based on the timeout.
