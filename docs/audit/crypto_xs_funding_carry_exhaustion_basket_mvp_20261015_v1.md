# Cross-sectional funding carry + exhaustion MVP — independent terminal review

**Terminal decision: INCONCLUSIVE.** The exact frozen Top-40 experiment did not satisfy its data contract, so the observed adverse signal statistics cannot be promoted to a formal rejection of that exact thesis.

## Verified evidence

- Frozen development window: 2020-06-01 through 2023-12-31. No 2024+ observation was loaded or scored.
- The matched point-in-time panel has 654 decision dates. Cross-sectional breadth is 23 minimum, 40 median, and 40 maximum.
- **65/654 decision dates have fewer than 40 matched eligible contracts.** The first full 40-name decision is 2020-10-05, but changing the start now would be a new post-outcome trial.
- Candidate exhaustion score: mean 48h Spearman IC **0.015643**, IC IR **0.0572**, HAC t-stat **1.463**, p **0.1438**, 652 usable IC periods.
- Naive unconditional funding-sort baseline: mean IC **0.031523**, IC IR **0.1631**, HAC t-stat **4.083**, p **0.0000501**, 654 periods.
- An independent SciPy/statsmodels recalculation reproduces candidate mean IC **0.015642817433095965**, HAC SE **0.010688880073109704**, and HAC t-stat **1.463466455428667**.
- Label clock audit passes: every entry label is decision +1h and every exit label is entry +48h. Latest decision is 2023-12-29.
- Focused causal tests pass 4/4.

## Source corrections

Gemini's source assumptions were not fully correct. Canonical Binance 1h OHLCV starts on 2020-01-01, not 2019, and the local store contains 528 funding dataset directories rather than the claimed 660+. More importantly, the canonical funding stream has 565 non-8h events in 2022 and 13,511 in 2023. Before freezing the session, the feature was corrected to sum **all actual funding settlements observed in the trailing 24 hours** instead of assuming exactly three settlements.

## Research-control finding

The repository v1 session checker returns BLOCKED for the bounded panel files. It treats repeated timestamps across symbols as duplicates/global sorting failures, expects a single instrument symbol per file, and refuses the 1,276,518-row 2023 price panel because its audit bound is 1,000,000 rows. These are panel-contract/audit-interface limitations, not proof that the per-symbol data are corrupt. They still prevent a formal session-audit PASS.

The observed candidate signal also fails the frozen HAC t-stat threshold of 2.0 and is weaker than the naive funding baseline. That is adverse exploratory evidence. However, the true Top-40 coverage failure takes precedence: the exact preregistered experiment was not observed on all dates.

## Execution decision

No portfolio backtest was run. This is intentional. Running a native event-driven portfolio after the diagnostic/data gate failed would violate the fail-fast MVP contract. No start-date shift, universe relaxation, threshold change, or protected-period access was used to rescue the thesis.

A future test requires a **new preregistered trial** with a prospectively chosen eligible start or another explicitly justified data contract, plus a panel-compatible immutable audit representation. This completed run must remain INCONCLUSIVE.
