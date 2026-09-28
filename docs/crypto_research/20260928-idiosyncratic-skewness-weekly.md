# 20260928 Idiosyncratic Skewness Weekly

## Conclusion
**INCONCLUSIVE.** The pre-registered idiosyncratic-skewness candidate could not be evaluated reliably because the remote execution connector lost stdout after the deterministic processes completed. No success or failure is inferred.

## Source
Liu, Yakun & Chen, Yan (2024), *Skewness risk and the cross-section of cryptocurrency returns*, International Review of Financial Analysis 96, DOI 10.1016/j.irfa.2024.103626.

## Hypothesis
Lower lagged market-residual skewness should predict higher subsequent weekly cryptocurrency returns. This is the source-faithful idiosyncratic-risk adaptation of the earlier total-skewness test.

## Pre-Registration
Manifest: `run_log/crypto_research/runs/20260928-idiosyncratic-skewness-weekly-manifest.json`.

Three windows were fixed before execution: 14, 30, and 60 completed UTC days, with 30 days canonical. Base one-way cost was 10 bps with 2x and 3x stress tests planned.

## Universe / Methodology
Point-in-time Binance USD-M USDT perpetual universe. Weekly Monday rebalance, top 50 by lagged trailing-30-day quote volume. Residual skewness used a causal trailing single-market-factor beta estimated only from completed days.

## Execution Failure
The exact runner was executed more than once because the connector returned an internal failure while the process continued. Later process inspection showed the jobs exited, but stdout was not recoverable. No structured result was produced by the runner itself.

## Multiple-Testing Audit
The 3 pre-registered parameter variants are counted. Cumulative crypto-search trial count is now **115**.

## Decision
**INCONCLUSIVE.** Do not rerun with altered parameters or infer a result from the missing output. Continue with a materially different hypothesis.

## Reproduction
`uv run python -m scripts.run_crypto_idiosyncratic_skewness --root <BINANCE_UM_PERP_STORE>`
