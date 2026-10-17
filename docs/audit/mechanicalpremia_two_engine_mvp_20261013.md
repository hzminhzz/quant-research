# Mechanical Premia two-engine MVP — engineered native execution and qualification audit

**Research decision: INCONCLUSIVE. Do NOT promote to OOS validation or live trading.**
**Date:** 2026-10-13.
**Frozen session:** `mechanicalpremia-two-engine-mvp-20261013`.
**Reference:** https://mechanicalpremia.substack.com/p/building-a-multi-strategy-portfolio (Mechanical Risk Premia, 2026-09-01).
**Development only:** [2024-01-01, 2025-01-01), ES and NQ CFD *price proxies*.
**Evidence revision:** `native_research_v2` (the earlier `native_research` outputs are preserved and superseded; first version used conventional averaged 100-ATR median rather than MQL5 sorted ATR[50] upper median).
**Backtester:** installed `ml4t.backtest.Engine` / Broker, with `ml4t.engineer.compute_features` ATR, Bollinger, EMA. Does not use a homemade simulator.
**Price-unit account:** $100,000 notional toy account, fractional quantity, assumed multiplier=1; broker CFD execution **unverified**.

## Results — 2024 bounded development (not OOS)

Costs: assumed 1 bp commission + 2 bps slippage PER SIDE; **spread and overnight financing unavailable/NOT included**. Daily Sharpe and Calmar from `ml4t.diagnostic.api.PortfolioAnalysis` on the daily-equity series (not 1m or per-trade returns). D1-only and both portfolio variants have two positions still open on Dec 31, 2024.

| Variant | Closed trades | Win rate | Final-equity delta ($) | Return | Daily Sharpe | Daily Calmar | Daily max drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H1 only | 88 | 40.91% | +2,762.46 | +2.76% | 0.442 | 0.471 | -4.722% |
| D1 only | 2 | 100.00% | +5,406.05 | +5.41% | 1.263 | 1.777 | -2.444% |
| Portfolio 50/50 risk budgets | 91 | 42.86% | +5,480.21 | +5.48% | 1.072 | 1.982 | -2.222% |
| Portfolio 76.64% D1 / 23.36% H1 | 91 | 42.86% | +5,753.13 | +5.75% | 1.182 | 2.066 | -2.237% |
| Source risk, 1.5x costs | 91 | 42.86% | +4,477.20 | +4.48% | 0.931 | 1.609 | -2.238% |
| Source risk, 2.0x costs | 91 | 41.76% | +3,216.43 | +3.22% | 0.678 | 1.128 | -2.297% |

**Interpretation:** Source-risk beats equal-risk in 2024 daily Sharpe (1.182 vs 1.072), but drawdown is slightly *worse* (-2.237% vs -2.222%). The frozen acceptance requirement of better Sharpe AND better drawdown is unmet. D1 has only two closed winners and two unclosed trades; its estimated statistical edge is undefined. The portfolio's apparent benefit is dominated by sparse daily-sleeve exposure and should not be projected forward. Positive results at 2x assumed direct costs do not cover missing spread/overnight financing or cure an entry-stop defect. Single-year 2024 results do not establish regime consistency, uncertainty intervals, Sharpe significance, or out-of-sample reliability.

## Engineering evidence
- `scripts/mechanicalpremia_native_20261013.py`: source-inspired causal H1 and D1 signal builder and native order strategy. H1 ATR14 / BB40 (2 std), D1 ATR20 / EMA100 / BB10 (3 std). The sorted 100 ATR upper median is reproduced through rolling quantile with `higher` interpolation. No D1 hard stop; ATR20 ghost sizing is retained. Split native instrument identities (e.g. `ES_PROXY_H` and `ES_PROXY_D`) permit simultaneous strategy-specific positions.
- `scripts/run_mechanicalpremia_mvp_20261013.py`: bounded load before 2025-01-01; genuine native ml4t backtest; exports native fill/trade ledger, daily marked-equity and summary under `run_log/research_sessions/mechanicalpremia-two-engine-mvp-20261013/native_research_v2/`.
- `tests/test_mechanicalpremia_native_20261013.py`: four tests (holdout cutoff, feature H1 timing, two-sleeve positions, native next-minute entry) **4 passed**. Original failed assertion concerned naive UTC timestamp returned by native fill API; corrected to compare UTC-normalized datetimes. First development smoke uncovered margin rejections; fixed with conservative per-instrument notional headroom.
- Native engine returned 176 fills / 0 rejects for full-year H1-only. Portfolio source-risk returned 184 fills / 0 rejects, with 91 closed and 2 open positions. Native Broker cash + marked open positions = native equity passed at the final event for all six V2 executions.
- Source-risk net final-equity delta is NOT identical to sum of *closed* trade PnL because two positions remain open. Do not silently force-close or assume these mark values will be realized.

## Gate failures and blocking deviations
1. **DATA-ELIGIBILITY: FAILED.** Frozen `ES_PROXY` and `NQ_PROXY` identifiers disagree with input `symbol` fields `ES` and `NQ`. The frozen `data/processed/_manifest.json` refers to 7 unrelated LSE datasets; it does not certify these two input files. Vendor, instrument mapping, CFD quote currency, lot size, spread, financing, holidays and verified broker trading clock are not proven. Hourly bars require all 60 minutes; daily aggregation uses an *assumed* 17:00 New York session and excludes days under 1,000 observed minutes. Partial sessions and tick semantics have not been broker-verified.
2. **SOURCE-PARITY: FAILED.** MQL5 economic rule and indicator definitions are extracted, but a complete immutable original-code archive and exact broker session mapping remain absent. **Critical**: current native H1 protective stop is submitted on the callback after entry fill; price can cross the required protective stop during the entry minute without an exit. Native order fill accounting is real, but source fill *fidelity* is not certified.
3. **COSTS: UNQUALIFIED.** Commission and slippage are synthetic bps; no observed bid/ask, CFD financing/rollover fees or actual lot/multiplier. Mark positive results as illustrative, not executable.
4. **BENCHMARK: INSUFFICIENT.** Only 2024 eligible in the *frozen inputs*. Both proxies have ~325k minute rows before 2025, not 8 years of data as originally assumed. Only one development calendar year is observed, and D1 has two closed trades.
5. **HOLDOUT HYGIENE: STRICT METADATA BREACH.** Price/feature/strategy code loaded observations strictly before 2025-01-01. However the repository's `research_session.py check` scanned the frozen **full files** and emitted file-level end timestamps and row totals including 2025. No 2025 prices, feature values, strategy outcomes, or performance were evaluated by this research run, but the session's rule against *any* 2025 inspection was breached at the metadata level. **Do not certify 2025 as pristine unseen for this session.** Record the exposure; a future promoted program must define genuinely unobserved final-test data and get explicit approval.
6. **SOURCE MEDIAN CORRECTION:** First run outputs under `native_research/` used averaged median rather than MQL5 `sorted[50]` upper-middle. V2 changed feature semantics before the rerun. These are TWO observed versions; count both in selection audit. V1 remains preserved, and V2 was not selected by profitability.
7. **OPEN-POSITION RISK:** Daily dip sleeve has no actual protective stop by source design. Forced broker liquidation, overnight holding costs and tail losses are not adequately modeled. The native mark-to-market is not a completed liquidation PnL.
8. **TRIAL-LEDGER:** Native executions are post-freeze source-compatible engineering/diagnostic artifacts. `completed` means an execution occurred, not a scientific pass. Do not promote until source and data gates are corrected through a newly registered, eligible research program.

## Decision
**INCONCLUSIVE**: the rules are implemented, tested and backtested in the required native libraries, but source, broker, 2024-only evidence, exact fill/stop timing, and protected-holdout governance prevent a scientific VALIDATE or a Promotion Candidate. The documented 2024 portfolio improvement is insufficient to satisfy its full frozen acceptance criteria. Do not optimize the source-risk split or open the holdout to rescue it.

## Next research action, only as a NEW frozen program
Qualify the correct canonical Dukascopy ES/NQ CFD inputs with matching contract identity, 2017–2024 coverage if available, genuine broker sessions/financing and registered source-to-adaptation mapping. Correct entry-minute stop evaluation via a tested native lifecycle hook or position-rule integration. Freeze the new source/data/cost identity and trial accounting BEFORE any newly eligible outcome observation. Preserve all V1/V2 evidence and the metadata exposure record.
