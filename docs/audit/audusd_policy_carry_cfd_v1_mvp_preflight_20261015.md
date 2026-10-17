# AUDUSD policy-rate carry — MVP source preflight

Date: 2026-10-15 (Asia/Bangkok)  
Candidate: `AUDUSD_POLICY_CARRY_CFD_V1`  
MVP decision: **INCONCLUSIVE — BLOCKED_DATA (pre-backtest)**  
Research status: **EXPLORATORY / NOT_APPROVED**  
Protected final test: **NOT ACCESSED**

## Outcome

Stop before a ResearchPhase 3 diagnostic or native backtest. The candidate's
specified economic outcome is *monthly AUDUSD total return including actual
broker-applied overnight swap credits/debits*. The required historical
directional Dukascopy Bank SA rollover inputs were not found in the inspected
repository or canonical local stores. They cannot be replaced with the
RBA-minus-Fed policy-rate spread, contemporary posted swap rates, synthetic
zero swaps, or close-only price returns.

This is **not** an economic REJECT. Profitability, Sharpe, Calmar, drawdown,
trade count, and bootstrap intervals are **not estimated**. No research
execution, financial transaction, or holdout trial occurred.

## Input and workspace identity

- User-supplied thesis: `thesis_candidate(1).yaml`; SHA256
  `15a07be47ca7464023d471f133c193bf38a390055aeff8251d6b77accc1b5e5a`.
- Companion handoff: `research_brief_and_handoff(1).md`; SHA256
  `dac0f21a3df89fa160c5845949c1a6344fa8fac38dc4e6572cde9b048546abc0`.
- Repository: `/home/quant/dev/quant/quant-research`.
- Inspected branch: `local-first-main-sync-20261014`; HEAD `9525f35`.
- Existing tracked modifications: `CONTEXT.md`, `src/research_session.py`,
  `tests/test_catalog.py`, `tests/test_research_session.py`. Many unrelated
  untracked research artifacts also exist. They were preserved.
- Requested prompt `docs/prompts/gemini_to_ml4t_mvp.md`: **NOT FOUND**
  in this checkout. The current `docs/research_operations.md`,
  `docs/research_sessions.md`, `docs/architecture/market_scope_policy.md`
  and `AGENTS.md` supplied the fallback governing workflow.
- The source YAML sets `execution_approval: false` as a discovery-stage
  field. The present user authorized research inspection. No broker order
  or protected final test was authorized.

## Evidence and mandatory source gates

| Gate | Direct evidence inspected | Result |
| --- | --- | --- |
| Historical applied broker swaps | Local `ml4t-data/.data/store` directory inventory and targeted repository searches found no AUDUSD signed daily Bank SA swap ledger, policy-level history, or reconciled rollover account statements for 2015–2024. | **BLOCKED_DATA — decisive** |
| Broker rollover semantics | Dukascopy Bank SA's official overnight policy describes daily rollover close/open, swap-adjusted reopening prices, account-activity-dependent Regular/Advanced/Premium policy and nonuniform settlement adjustments. Bank carries its own cost on top of the reference rates. | Rate-spread proxy **cannot** stand in for actual applied financing. |
| Exact tradable product | YAML leaves margin-FX-versus-CFD, broker product ID, lot step, multiplier, tick, and broker fees unverified. Official Bank materials distinguish JForex forex accounts, MT4/MT5 and CFDs. | **BLOCKED_DATA** |
| Quote provenance | Current `forex_minute_AUDUSD` metadata says `provider=london_strategic_edge`, `provider_id=lse`, `canonical_write_authority=london_strategic_edge`, source `AUD/USD`, frequency `1m`, store identity `985b0cd7ff1b4bc6deee3204f72a8565a8dae073ca537f8110981eb80011b3ff`. Earlier Gold/FX intake calls the source Dukascopy; this disagreement has not been reconciled at partition level. | **UNQUALIFIED SOURCE** |
| Historical quote schema | Read Parquet schema only from a 2018 AUDUSD partition: `timestamp` UTC, `symbol`, `open`, `high`, `low`, `close`, `volume`. No executable `bid_open` / `ask_open` fields or financing ledger. | **BLOCKED_DATA** for market-order executable entry |
| Legacy Gold/FX snapshot | `data/processed/gold_fx_trend_diversification_20261015/AUDUSD_NY17_daily_2013_2024.parquet` exists, with a prior qualification report claiming 3,107 eligible daily closes. It is a 17:00 NY daily quote snapshot, not the required 10:01 NY minute bid/ask or rollover statement. | **INSUFFICIENT** |
| Policy-rate point-in-time | RBA and Fed sources named in YAML are plausible official references, but their exact release/effective timestamps and backward-asof monthly joins are not materialized or audited for this trial. | **NOT QUALIFIED** |
| Native library environment | Installed `ml4t-engineer==0.1.4`, `ml4t-backtest==0.1.7`, `ml4t-data==0.1.0b14`. `ml4t.engineer.compute_features`, `ml4t.backtest.Engine` and `DataFeed` import; the latter exposes optional bid/ask field mapping. A compliant historical broker financing adapter was not verified. | **API ENTRYPOINTS CONFIRMED; FULL CAPABILITY UNKNOWN** |

References:
- Dukascopy Bank SA overnight policy: https://www.dukascopy.com/swiss/english/cfd/cfd-overnight-policy/
- Dukascopy rollover mechanics and the warning that displayed rates do not
  necessarily represent effectively applied rates:
  https://www.dukascopy.com/wiki/en/forex-cfds/account-management/rollovers/
- Source repository evidence:
  `docs/audit/gold_fx_trend_diversification_intake_20261015.md`
  and `data/processed/gold_fx_trend_diversification_20261015/data_qualification.json`.
- Canonical metadata:
  `/home/quant/dev/quant/ml4t-data/.data/store/.metadata/forex_minute_AUDUSD.json`.

## Frozen design preserved from the proposed thesis

No variant was tested or revised. The proposal remains: development
2015-01-01 to 2024-12-31 UTC; first eligible NY FX session each month;
10:00 NY decision using official RBA/Fed levels public by 16:00 NY
of the prior completed FX session; first legal fill no earlier than
10:01 NY; signed target of 10,000 AUD with no monthly turnover when the
target remains unchanged; baseline cash, comparator always-long AUDUSD;
real daily broker costs, calendar/value dates and direction-dependent swaps.
The proposed primary metric is monthly after-cost PnL relative to a fixed
USD 100,000 book. A six-month moving-block bootstrap and four independent
signed exposure episodes are required for positive evidence.

The specified `acceptance_and_stop_rules.before_execution` says that
unavailable historical directional broker swaps, unqualified execution
product, or missing causal bid/ask fills result in `BLOCKED_DATA` and
must stop before any native trial. No zero-swap diagnostic or replacement
broker/product was attempted.

## Research control and next admissible action

- **Source gate:** FAIL (required inputs unavailable or unverified).
- **ResearchPhase 3:** NOT RUN; no registered signal diagnostic result and
  no artificial PASS/FAIL/NOT_APPLICABLE claim.
- **ResearchPhase 4 / native Engine:** NOT RUN; no synthetic PnL, no metrics.
- **Research session / RunPermit:** NOT REGISTERED; inputs cannot satisfy
  the thesis's pre-execution data qualification gate.
- **Trial count for this candidate in this execution:** 0.
- **Holdout:** no 2025+ market-price rows, policy-signal outcomes or
  backtest results queried; the 2018 Parquet schema and existing
  prior-development qualification report were inspected.
- **Code and unrelated files:** not modified.
- **Final MVP decision:** **INCONCLUSIVE (BLOCKED_DATA)**; not `VALIDATE`,
  not economic `REJECT`, and not deployable.

To unblock **this exact thesis**, obtain an authoritative 2015–2024
Dukascopy Bank SA AUDUSD historical long/short rollover record: applied
swap pips or reconciled USD cashflows, settlement/value dates, historical
account-policy tier (Regular/Advanced/Premium), holiday multipliers and
broker fees. Then establish the exact bank product/account and verifiable
entry-side bid/ask at the specified monthly clock, and source the actual
publication/effective chronology for both policy rates. Re-run the source
gate before freezing one preregistered Phase 3 diagnostic and any permitted
native Phase 4 trial. If these inputs remain unavailable, close this
candidate as untestable with this broker; do not call it unprofitable.
