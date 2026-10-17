# ATS-7 frozen qualification plan — 2026-10-17

Status: preregistered engineering and operational acceptance plan. This record precedes ATS-7 evaluation. It is not an order authorization.

## Inspected baseline and scope

Base: `10426fcf227869aa5bfc1e07e8fc8337166e9cf7`, including prerequisite merge `a7827ee09125df0f6a6d0d8d64ec16ac307e9b8e`. Existing connector: `6175a948e6d253ba6f4b610b97b34d8433662e77`. Runtime: Python 3.13.5, ML4T Live 0.1.2, Backtest 0.1.7, CCXT 4.5.64. Preserve original dirty checkouts and all ATS evidence. Do not push.

ATS-6 remains synthetic shadow only. ATS-2 synthetic grants cannot authorize external orders. ATS-3 Path A operator exceptions remain historical exceptions, not new permissions.

The selected feasible provider is Bybit Demo, with separate authenticated Demo REST and public Mainnet market data. Its existing position and journals remain under their existing owner. No new Demo execution authorization binding ATS-7 identity, duration and risk was found. Historical issue #51 described a bounded one-hour run; it is not an ongoing authorization.

The promoted Donchian source is daily Binance perpetual research with unresolved funding, liquidation, spread and selection limitations. The historical Demo wrapper runs its lookbacks on 1m data and changes sizing. It cannot qualify exact strategy identity. The other promoted strategies require equity/index products not qualified by the installed linear crypto adapter. Therefore select an explicitly synthetic native Strategy for engineering. No economic optimization, new strategy search, protected-data access or live orders.

## Minimal ownership decisions

- Native `LiveEngine`, `AuditSafeBroker` and `VirtualPortfolio` own local simulated execution, positions and cash. Local simulation is explicitly native shadow-fill semantics, not provider fills or backtest fill realism.
- The existing Bybit connector owns REST transport and provider intent persistence. Fix only demonstrated provider defects in a separate connector worktree.
- A release manifest binds strategy class/source/parameters/timing, evidence, risk, product, account/environment, terms, feed/calendar, code/lock, observation and operational policy.
- A small release decision journal owns identity, pre-effect admission, control latches and source bindings. It is not a position ledger. Unknown outcomes never permit automatic retransmission.
- A single native risk owner covers one account in one configured risk domain. Reject additional accounts and competing writers; multi-account execution is not qualified. This conservative restriction makes account and global exposure the same enforced cap.
- Separate externally signed authorization is required for external orders, and separate qualification evidence for any strategy release. Trusted issuer files must be outside the worker's write authority. Synthetic/local permits cannot cross this boundary.
- ATS-3 and a separate arithmetic verifier reconstruct evidence; existing Prometheus/Alertmanager/Grafana remain monitoring authorities.

## Frozen evaluation gates

Engineering: all applicable tests must pass, including real process death before/after durable admission; duplicate intents/fills; lost ACK; partial fill, cancel race, rejection and late fill; source/terms/authorization drift; restart with exposure; stale/conflicting account and data; manual/automatic halt; denied resume; risk reduction without zero crossing; rollback preserving obligations; notification failure and service death. At most one economic dispatch per immutable execution identity. Original failed attempts remain recorded.

Provider: verify current official documentation, installed implementation, authenticated GET observations and archived original executions separately. Absence of a record is not proof of no exposure. Qualification is capability-specific. No new provider execution claims without authorized original observations. Only linear one-way Market/Limit semantics can be considered; unsupported stops/hedge mode remain denied.

Native regression: all ATS-2/3/4/5/6 tests and dual-mode regressions, existing native execution/risk/recovery tests where their source dependencies exist, connector tests, task lint, managed feature policy and `git diff --check`. Preserve optional real-fixture skips and pre-existing unrelated lint debt explicitly.

Independent arithmetic: exact execution-ID deduplication; cash + signed fills - commissions + financing; positions and equity against native/original provider records; mark provenance and account currency explicit. Tampered events must fail.

Operational observation: minimum **28 real elapsed days**, with at least one full strategy rebalance/round-trip cycle, current source identity, continuous supervised health records, at least 99% expected completed bars, zero unresolved execution/account discrepancies, zero unauthorized effects, no unreviewed loss-limit breach, and a delivered operational notification. A real incident remains recorded and must be adjudicated before acceptance. Replays and fault fixtures cannot count toward elapsed days. Do not change thresholds after seeing results.

Synthetic public-feed observation may run as an engineering soak under this mission, with no credentials and native simulated fills. It does not satisfy qualified-strategy paper observation. If established, report `PAPER_RUNNING` with synthetic/local scope and retain the independent strategy and provider authorization blockers. A qualified strategy's 28-day clock starts only under its own exact release identity and authorization.

## Delivery dimensions

Report engineering qualification, provider capability qualification, paper execution qualification, operational observation and live authorization separately. Use QUALIFIED / PARTIALLY_QUALIFIED / RUNNING / BLOCKED, with exact identities and evidence. No four-week completion claim at startup. No live canary, capital change, position flatten, credential scope expansion or remote push.

## Methodology loaded

Installed primary-checkout `.agents/skills/ml4t-{live-trading,production-readiness,kill-switch,monitoring-alerting,agent-governance,run-backtest}/SKILL.md`, plus the available bundled ML4T skill. Repo architecture, rollout, ATS-6 acceptance and ATS-3 audit contracts govern. Illustrative skill flatten examples do not override explicit position ownership or imply guaranteed exits. Native code, not skill snippets, determines actual APIs.
