# Arcus RWA cross-venue hedge — Phase 3 engineering handoff (2026-10-11)

Status: **ENGINEERING PROTOTYPE COMPLETE / SHADOW-ONLY / NOT LIVE-READY**.
Prerequisites: `docs/arcus_rwa_hedged_maker_phase1_20261011.md`, `docs/arcus_rwa_hedged_maker_phase2_20261011.md`.

## Executed
Implemented in the existing, separate Hummingbot repository `/home/quant/dev/hummingbot`:
- `controllers/market_making/arcus_hedged_rwa/arcus_hedged_rwa.py` — new Strategy V2 controller and config.
- `controllers/market_making/arcus_hedged_rwa/ledger.py` — atomic, durable FIFO Arcus lot-age and pending Lighter hedge-intent checkpoint.
- `controllers/market_making/arcus_hedged_rwa/examples/{spy_shadow,qqq_shadow}.yml` — checked-in candidate example paths (still untracked in working tree).
- `conf/controllers/arcus_hedged_{spy,qqq}_shadow.yml` — installed task-owned shadow profiles in gitignored runtime config folder.
- `test/hummingbot/strategy_v2/controllers/test_arcus_hedged_rwa.py` — positive and negative focused unit tests.
- `controllers/market_making/arcus_hedged_rwa/README.md` — detailed technical evidence and deployment blockers.

Existing production Arcus controller, configs, live orders and collateral were not modified by this task. Git working tree already had dirty concurrent changes; preserved. New work remains local and **uncommitted**.

## Engineering design
- Reuses native Arcus Strategy V2 maker logic; uses fresh same-ticker Lighter order book as pricing reference rather than old index anchored ratio.
- Registers Arcus+Lighter connectors in the controller market set. Reads actual private position states, never assumes confirmed fills from an OHLCV touch.
- FIFO Arcus fill events from `MarketEvent.OrderFilled`, trade-ID dedup, 12h lot age, 12h opposite quote suppression.
- Lighter hedge target = negative Arcus signed units times **provisional** 1:1 ratio; marketable-limit orders with strict price collar, book freshness, spread, basis, notional checks.
- One pending hedge at a time with durable intent before outbound action, confirmation through private positions, cooldown, timeout/manual reconciliation. No speculative duplicate after restart.
- Current config defaults to `observation_only: true`, `hedge_execution_enabled: false`, `execution_authorized: false`, `hedge_contract_verified: false`. New controller cannot place orders under the supplied profiles.

## Verification
At Hummingbot HEAD `36d9c64abc88c8ca59c9905ba2b04a1c557ac137`, ran:
```
/home/quant/anaconda3/envs/hummingbot/bin/python -m pytest -q \
 test/hummingbot/strategy_v2/controllers/test_arcus_hedged_rwa.py \
 test/hummingbot/strategy_v2/controllers/test_arcus_fair_value_mm.py \
 test/hummingbot/connector/derivative/lighter_perpetual/test_lighter_perpetual_api_utils.py
```
**42 PASSED**, six existing Pydantic deprecation warnings. Also confirmed on-disk shadow configs and Python syntax; `git diff --check` returned success. Pure unit tests are not exchange execution verification.

## Gaps / next gates
- Need *independent* cross-venue risk accounting for realized/unrealized PnL, actual funding and commissions, liquidation/collateral, order timeout/cancellation, rejects and partial fills, independent emergency unwind.
- Need canonical synchronized venue data, exact SPY/QQQ underlying/corporate action exposure mapping, empirically calibrated hedge ratio, 12h scoring validation, actual authenticated Lighter connector smoke in isolated no-trade mode. Not yet done.
- Need prospective shadow-only soak/restart fault-injection and authenticated account reconciliation before any paper/live deployment.
- Original scientific Phase 3 event-study evidence has **not** been completed; this document only closes the user-requested engineering slice. Phase 4 backtesting and full Phase 3 empirical gate remain BLOCKED.

Research outcome: **ENGINEERED / NOT APPROVED**. No live orders, instance restarts, commits or pushes.
