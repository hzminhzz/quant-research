# Plain Cross-Sectional Binance Funding — Phase 4 Terminal Audit

**Session:** `crypto_xs_plain_funding_phase4_20261015_v1`  
**Classification:** EXPLORATORY / NOT APPROVED  
**Terminal decision:** **REJECT**  
**Decision reason:** frozen base-cost maximum drawdown gate failed by 0.3468 percentage point.

## Outcome

The Phase-3-qualified plain funding factor converts into a strongly profitable native event-driven portfolio on the frozen 2020-06-01 through 2023-12-31 development period. It is profitable at base costs, remains profitable at 2x execution friction, has positive realized funding carry, and the funding accounting is insensitive to the one-minute mark convention.

Phase 4 nevertheless **REJECTS** the candidate under the preregistered contract because the base-cost maximum drawdown is **-35.3468%**, worse than the frozen **-35.00%** limit.

The threshold is not relaxed after observing PnL. This result must not be relabeled VALIDATE.

## Inherited Phase 3 evidence

Phase 3 was not rerun or reselected for Phase 4. The inherited frozen signal evidence was:

- mean 48h cross-sectional Rank IC: **0.038819**
- HAC t-stat: **5.036**
- first chronological half IC: **0.061160**
- second chronological half IC: **0.016478**
- eligible 48h cycles: **654**
- minimum point-in-time breadth: **23**

Signal, universe, 48h cadence and 5-long/5-short construction were carried unchanged into Phase 4.

## Phase 4 data repair and provenance

The prior MVP was blocked because historical `/fapi/v1/fundingRate` often returned null settlement `markPrice`.

Phase 4 repaired this without using ordinary trade OHLCV:

1. Derived **39,971** funding events that could affect frozen portfolio positions across **140** symbols.
2. Derived **1,621** required symbol-month mark-price partitions.
3. Downloaded **1,621/1,621** official Binance USD-M public `markPriceKlines` monthly archives at 1-minute cadence.
4. The public archives contained **370** exact required minute gaps across 37 symbols / eight dates.
5. Repaired **369/370** missing minute requirements from Binance's official `/fapi/v1/markPriceKlines` REST endpoint, appending only absent rows and retaining archive rows unchanged.
6. The sole unresolved event-minute mark was LITUSDT funding at **2023-02-24 00:00:00.015 UTC**. Official 1m/1h mark archives and REST had no 00:00 mark while the official **2023-02-23 23:59** mark close existed at **1.36722164**. Before any portfolio PnL was observed, the Phase 4 contract froze a one-row prior-minute-close fallback for this event only.
7. Final proxy coverage: **39,970 event-minute opens + 1 flagged prior-minute-close fallback = 39,971/39,971 resolved events**.
8. All prior-minute closes required by the sensitivity arm were present.

The compact official mark evidence is:
- `data/processed/crypto_xs_plain_funding_phase4_20261015_v1/required_funding_mark_1m.parquet`
- SHA256: `4553106ab31f438c60e01fe8d1532d3dd93302ddca41504887c0f71e8215384a`

The event-level accounting evidence is:
- `data/processed/crypto_xs_plain_funding_phase4_20261015_v1/required_funding_events_with_marks.parquet`
- SHA256: `c07e8a7ccae02a16a2a0e50673832a924be7bbdd32dcdb062be925c80fe92c08`

External archive/REST lineage and acquisition-script identities are sealed in:
- `data/processed/crypto_xs_plain_funding_phase4_20261015_v1/mark_source_manifest.json`
- SHA256: `14b5a24352a53e5e52567009e66e5859c6364f42eb94182c745955b580b62e12`

The frozen research-session data audit returned **PASS** across all nine declared datasets. Pre-PnL execution coverage also verified **19,494/19,494** required decision/fill/open/close/flatten symbol-time keys. No missing-price `USE_LAST` fallback was enabled.

## Frozen portfolio contract

- Initial research capital: **$100,000**
- Rebalance cadence: **48 hours**
- Long: five lowest trailing-24h funding names, **+10% target each**
- Short: five highest trailing-24h funding names, **-10% target each**
- Target gross exposure: **1.0**
- Target dollar net exposure: **0.0**
- Fractional quantities
- Native `ml4t.backtest`
- Decision: 00:00 UTC
- Fill: next 01:00 open
- Base execution friction: **5 bps commission + 4 bps slippage per side**
- 2x stress: **10 bps commission + 8 bps slippage per side**
- Actual canonical funding rates with official Binance mark-price proxy
- No stops or post-result parameter changes

## Native Phase 4 results

| Arm | Total return | Net PnL | Daily Sharpe | Max DD | CAGR | Calmar |
|---|---:|---:|---:|---:|---:|---:|
| Base costs + funding | **+1,581.15%** | **+$1,581,152** | **2.170** | **-35.35%** | **119.93%** | **3.39** |
| 2x costs + funding | **+801.66%** | **+$801,662** | **1.732** | **-38.05%** | **84.86%** | **2.23** |
| Base costs, no funding | **+350.05%** | **+$350,049** | **1.258** | **-42.37%** | **52.22%** | **1.23** |

Base-cost yearly returns:

| Year | Return |
|---|---:|
| 2020 partial | +128.71% |
| 2021 | +145.36% |
| 2022 | +29.15% |
| 2023 | +132.03% |

Native execution evidence:
- base fills: **9,747**
- rejected native orders: **0**
- base commission: **$221,576**
- base slippage: **$177,261**
- maximum observed gross exposure / equity between rebalances: **1.399x**

The maximum observed exposure is an ex-post path statistic, not a changed target: target gross remains 1.0 and can drift between 48h rebalances as prices and equity move.

## Funding attribution

Primary realized funding cashflow using the frozen mark proxy:

**+$945,566.47**

Prior-minute-close sensitivity:

**+$945,594.97**

Difference:

**+$28.50**, or approximately **0.0030%** relative to primary funding contribution.

The funding contribution keeps the same positive sign, so the preregistered mark-sensitivity gate passes.

The base funding-aware portfolio exceeds the no-funding arm by **$1,231,103** in terminal PnL. This difference is larger than the direct $945,566 funding transfer because funding mutates native equity and therefore changes subsequent target-weight sizing. It must not be interpreted as a second independent funding cashflow.

The no-funding portfolio remains strongly profitable, indicating that the development-period result contains a substantial price component in addition to funding carry.

## Frozen Phase 4 gates

| Gate | Requirement | Result | Status |
|---|---:|---:|---|
| Base net return | > 0 | +1,581.15% | PASS |
| Base daily Sharpe | >= 0.50 | 2.170 | PASS |
| Base max DD | >= -35.00% | **-35.3468%** | **FAIL** |
| Realized funding | > 0 | +$945,566 | PASS |
| 2x-cost net return | > 0 | +801.66% | PASS |
| Mark sensitivity | same funding sign | positive / positive | PASS |

The drawdown miss is approximately **0.3468 percentage point**. Per the frozen contract, any failed gate yields Phase 4 **REJECT**.

## Runtime recovery and independent verification

The original frozen runner completed all three native arms, then failed before terminalization because Polars refused a sensitivity join between:
- funding-ledger timestamp: `datetime[us, UTC]`
- frozen mark timestamp: `datetime[ms, UTC]`

No native arm was deleted or rerun.

A separate artifact-only recovery cast both join keys to canonical millisecond UTC precision, computed the already-preregistered sensitivity formula and applied the original frozen `gate()` function. The original frozen runner was **not modified**.

Frozen runner SHA256:
`0e0d226fd9a1fd543612182764063b497dd24c772d70fbd47eddaa9da47af650`

Current runner SHA256:
`0e0d226fd9a1fd543612182764063b497dd24c772d70fbd47eddaa9da47af650`

They match exactly.

Independent verification then re-read saved fills, equity and funding ledgers, recomputed commissions, slippage, funding totals, daily Sharpe, max drawdown and the frozen terminal gate. It independently reproduced:

**REJECT — base-cost max drawdown breaches frozen threshold.**

Evidence:
- `run_log/research_sessions/crypto_xs_plain_funding_phase4_20261015_v1/phase4/terminal_decision.json`
- `run_log/research_sessions/crypto_xs_plain_funding_phase4_20261015_v1/phase4/independent_verification.json`
- `run_log/research_sessions/crypto_xs_plain_funding_phase4_20261015_v1/phase4/recovery_metadata.json`

## Research interpretation

**Verified:** the simple cross-sectional funding factor has strong development-period signal and portfolio economics under the tested execution model.

**Verified:** the strategy survives doubled execution friction by a large margin.

**Verified:** funding carry is large and robust to the preregistered one-minute mark-price sensitivity.

**Verified:** a substantial price-only component remains without funding.

**Verified:** the frozen Phase 4 qualification fails solely on its maximum-drawdown gate.

**Unknown:** performance on 2024-2025 validation data; those observations remain unopened.

**Unknown:** production capacity, liquidation/margin behavior under exchange-specific leverage rules, and live execution slippage beyond the frozen small-account bps model.

## Decision

**REJECT Phase 4 v1.**

Do not weaken the 35% drawdown threshold or relabel this run. Given the unusually strong economics and narrow risk-gate miss, the reasonable continuation is a **new preregistered risk-control/sizing hypothesis**, not a post-hoc threshold change. Any such trial must be a new session and should preserve 2024+ as sealed until the revised development contract is frozen.
