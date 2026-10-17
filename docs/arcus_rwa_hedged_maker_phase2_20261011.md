# Arcus RWA cross-venue delta hedge — Phase 2 feasibility audit
Date: 2026-10-11 (Asia/Bangkok). Status: **PHASE_2_FEASIBILITY_COMPLETE / INPUTS_PARTIAL / EXPLORATORY / NOT_APPROVED**.
Phase 1 authority: `docs/arcus_rwa_hedged_maker_phase1_20261011.md`.
Scope: Read-only inspection of `/home/quant/dev/hummingbot`, public authenticated-free exchange endpoints, and official venue fee/access documentation. No live order, bot restart, deposits, position mutation, source-code edit, holdout test or reward claim.

## Executive decision
**Lighter Standard perp is the preferred first external hedge for Arcus SPY/QQQ**, conditional on account authorization and executable liquidity/basis/funding tests. **Aster Pro USDT perpetual is the fee-bearing fallback**, subject to adding or testing a connector. **Robinhood Wallet is an access layer, not a distinct independent hedge execution venue**; its perp route accesses Lighter where eligible, and its Stock Tokens are generally unleveraged long assets rather than a frictionless short. No confirmed production hedge is ready today.

This project is NOT the previous metals-grid design. Do not use `docs/audit/metals_dual_grid_mvp_20261010.md` as a prior or an input; inventory is managed dynamically, not by anchored grid levels. Phase 1 remains the controlling thesis.

## 1. Hummingbot actual code and runtime (verified read-only)
Repo `/home/quant/dev/hummingbot` at HEAD `36d9c64ab`, branch `master`, 12 commits ahead of origin/master. **Working tree dirty**, including modifications to `arcus_fair_value_mm.py`, `domain/quote_policy.py`, related tests, and unrelated untracked files. Leave all untouched.
- Existing native connectors: `hummingbot/connector/derivative/arcus_perpetual/` and `hummingbot/connector/derivative/lighter_perpetual/`. No Aster or Robinhood derivative connector found in this checkout.
- Existing Strategy V2: `controllers/market_making/arcus_fair_value_mm/arcus_fair_value_mm.py`; existing configs `conf/controllers/arcus_mvp_{spy,qqq,nvda,sndk}.yml`.
- SPY config checked: Arcus `SPY-USD`, `observation_only: false`, `leverage: 10`, per-side nominal `quote_notional: 200`, `max_abs_inventory: 0.15` SPY (~$117 at $779), `market_loss_limit: 50`, `account_loss_limit: 100`. **The base-asset inventory limit can clip below the nominal $200 side quote**. These are current config values, not newly approved sizes.
- Controller tracks Arcus positions and cancels/adjusts passive quotes. It uses public Hyperliquid `XYZ:SP500-USD` for a ratio-anchored *pricing reference*; it does **not** place external hedge orders, follow Arcus fills into Lighter, perform cross-venue position reconciliation, or maintain independently enforced 12h aging/hedge funding ledger. Existing market/account loss logic can pause quotes; it is not a cross-venue emergency unwind manager. Existing market-pair reference is not proof of economic instrument equivalence.
- Hummingbot API Docker container **running**, but `docker ps -a` showed latest `arcus-live-mm-3pairs-20261008-102607` **Exited (137)** three days earlier. No active Hummingbot trading-instance container observed in `docker ps`. The old `run_log/arcus_mm_lighter_rwa_report.json` may say `status: running` but is stale relative to container inspection. **Do not infer live bot is running**. Do not restart without request.
- Targeted no-trade tests using `/home/quant/anaconda3/envs/hummingbot`: `pytest -q test/hummingbot/strategy_v2/controllers/test_arcus_fair_value_mm.py test/hummingbot/connector/derivative/lighter_perpetual/test_lighter_perpetual_api_utils.py` => **28 passed, 6 unrelated Pydantic warnings** (2026-10-11). Unit tests do not establish authenticated Lighter connectivity or hedge placement.

## 2. Instrument discovery on public live endpoints
Data fetched in one read-only sampling session 2026-10-11, not a historical representative execution study.

| Instrument | Arcus contract and state | Arcus market ID | Lighter Standard perp | Lighter market ID | Aster Futures V3 symbol |
|---|---|---:|---|---:|---|
| S&P 500 ETF exposure | SPY-USD ONLINE | 23 | SPY-USDC (raw SPY) | 128 | SPYUSDT TRADING |
| Nasdaq-100 ETF exposure | QQQ-USD ONLINE | 24 | QQQ-USDC (raw QQQ) | 129 | QQQUSDT TRADING |
| Nvidia | NVDA-USD ONLINE | 28 | NVDA-USDC (raw NVDA) | 110 | NVDAUSDT TRADING |
| Gold-linked | GLD-USD ONLINE | 20 | XAU-USDC **not GLD** | 92 | XAUUSDT / XAUUSD1 **not GLD** |

Arcus `GET https://api.arcus.xyz/v1/markets`: `markets[]` returned SPY 24h notional $36,441,093.01 and QQQ $12,632,322.83, NVDA $14,281,292.53, GLD $3,852,503.08. These are turnover, not fill capacity.
- Arcus `/v1/l2OrderBook/SPY-USD?nLevels=5`: best bid/ask $778.84/$778.85 (single sample); QQQ $751.46/$751.47. Market metadata gives both 1-cent tick, $5 min order notional, and different off-hours initial margin fractions: SPY 0.03, QQQ 0.06 in that snapshot. Contract quote USD, collateral per connector USDG; do not assume USDC = USDG for margin.
- Lighter `GET https://mainnet.zklighter.elliot.ai/api/v1/orderBookDetails`: SPY, QQQ, NVDA marked perp. Public per-market `maker_fee: 0.0000`, `taker_fee: 0.0000`, min quote $10, raw size decimals 4 for SPY/QQQ. `orderBookOrders?market_id=128&limit=20` showed initial SPY $778.89/$778.97 (8-cent spread); QQQ market 129 showed $751.92/$751.99 (7 cents). The snapshots were not time-synchronized; implied basis values must NOT be treated as arbitrage profits.
- Aster `https://fapi.asterdex.com/fapi/v3/exchangeInfo` listed SPYUSDT, QQQUSDT and NVDAUSDT all `TRADING`. Public `/ticker/bookTicker` showed SPY $780.14/$780.28; QQQ $751.82/$751.94 (single samples). These are not representative liquidity or verified fill estimates.
- Lighter `/api/v1/funding-rates` returned indicative rows for `exchange=lighter`: SPY/QQQ/NVDA each `rate: 0.000032` at one sample; **verify rate unit and signed payment direction against executed funding ledger before modeling cost**. Aster `/fapi/v3/premiumIndex` for those symbols returned `lastFundingRate: 0` at one sample (not evidence of zero future funding).
- Arcus `markets[]` contained fundingRate, nextFundingAt and per-product margin fields. The Arcus `/v1/fundingRates` URL without a market parameter returned 400; detailed signed historical funding payment archive **not yet audited**. Require timestamps, amount, payer side, collateral transfers and settlement schedule in Phase 2B.

## 3. Verified publicly advertised terms vs unverified reward rules
- Official Arcus blog `https://arcus.xyz/blog/arcus-perpetuals-maker-fees-zero-for-beta` (Aug 4 2026) says perpetual maker fees zero at tiers 0-4 for beta, and base tier taker 0.0225% (2.25bps) during beta. Tiers 5/6 keep negative maker fees (rebates). Changes when beta ends. Dashboard/actual fills are fee authority for the user's tier.
- Aster official `https://docs.asterdex.com/trading/perpetuals/fees-and-specs/fees` says USDT-perp maker 0%, taker 0.04% (4bps); USD1-perp taker 0.005% (0.5bps), but verified SPY and QQQ listings are **USDT perps**. Aster API docs `https://github.com/asterdex/api-docs` recommend Futures V3 and note authenticated V3 operations require a deposit linked to main wallet. **Do not assume USD1 schedule applies to SPY/QQQ**.
- Lighter Standard fees 0/0 confirmed by the public raw SPY/QQQ market API, not any promised free execution: still bid/ask, slip, funding, partial fills and delayed/timed hedges. Native Hummingbot connector can handle MARKET/LIMIT, but live account authentication, balance, order behavior and safe API quota are not yet verified for this user.
- Robinhood official `https://robinhood.com/newsroom/robinhood-accelerates-global-expansion-robinhood-chain-mainnet-stock-tokens-agentic-trading/?lang=en` (Jul 1 2026) describes Robinhood Wallet perps *executed on Lighter* where available. Its reported 2x Lighter points when accessed through Robinhood Wallet is **a distinct Lighter promotion**, not automatically attached to Hummingbot direct API hedge orders and not equivalent to Arcus points. Robinhood-issued Stock Tokens are tokenized debt exposures, not the direct short-perp leg for a long-Arcus hedge.
- Arcus Season 1 rewards and RWA/off-hours incentives have been reported, but **we did not authenticate and verify a binding 12h Arcus rule or linear point allocation**. Third-party anecdotal 220 points/$140 is hypothesis motivation only, not our performance estimate. No point value or token conversion guaranteed. Official Arcus point terms/weekly user-attribution data must be preserved with timestamp before any reward economics conclusion. Avoid wash/self trades or mechanical deposit cycling.
- Official Arcus help center `https://help.arcus.xyz/llms.txt` indexes perp funding, off-hours price bands, margin and liquidation rules. The index is evidence that each must be audited, **not** a substitute for the full rule text.

## 4. Ranking and operational architecture
**1. Lighter Standard, same-asset perp (SPY first, QQQ second).**
Strength: zero quoted explicit taker fees, actual SPY/QQQ/NVDA listed, local Hummingbot derivative connector and testnet, no new connector development. Weakness: market/mark differences, 1h funding, possible Standard-tier latency/rate limits, liquidity off-hours, separate USDC collateral. Selection CONDITIONAL.
**2. Aster V3 USDT perp same ticker.**
Strength: same ETF symbols and API, potential independent venue fallback. Weakness: actual baseline taker 4bps each executed hedge side and no checked-in Hummingbot connector. An Aster direct adapter would increase implementation and operational cost. Reserve as contingency after Lighter stress tests.
**3. Robinhood Wallet.**
Not an independent perp liquidity source versus Lighter; wallet routes perps through Lighter. Stock tokens don't solve short hedge directly. Use separate optional experiment for eligible **spot** reward route, not the automatic primary hedge.

### Recommended existing-Hummingbot integration (design only)
One **new Strategy V2 coordinator/controller** with an Arcus quote policy **plus a fill-driven HedgeExecutor** using `lighter_perpetual`:
1. Listen to Arcus confirmed fills and position stream; keep idempotent fill IDs and net inventory by lot, with timestamp/age.
2. Reconcile Arcus and Lighter positions before any hedge target; store durable desired and confirmed hedged delta. Compute mapped hedge quantity from contract multiplier/exposure *verified* in Phase 2B, not ticker equality alone.
3. Execute hedge against Lighter actual BBO/available top-N depth, with marketable-limit/price collars, max lag/notional, funding-aware rebalance threshold; quantify residual market beta and basis. Reject if market stale or open risk would breach cap.
4. Rate limit Arcus maker quotes when hedging unavailable. Idempotent restart recovery is mandatory (don't duplicate external short).
5. Track combined risk across independent USDC and USDG collateral, margin safety, funding on both, emergency manual/automated reduce-only flatten; quote pause != position liquidated.
6. Prevent accidental shortening of required net Arcus inventory-age; do not count a roundtrip or individual filled child orders as a continuous 12h *net* position when the net position flattened.

**Do not simply add a `hedge_connector` string to the existing Arcus controller and assume the Hummingbot V2 executor handles atomic cross-venue fill; require reconciled state machine, restart behavior and tests.**

## 5. Gate results and next decisive actions

| Check | Verdict |
|---|---|
| Arcus SPY/QQQ/NVDA/GLD actual API product identity | PASS |
| Lighter SPY/QQQ matching *ticker* and public connector | PASS |
| Aster SPY/QQQ matching ticker, V3 public feed | PASS |
| Direct Robinhood Wallet differentiated hedge exchange | NO |
| Native user-account Lighter authenticated hedge order/reconcile path | NOT TESTED |
| Verified costs, trading-size execution book history, off-hours spread distribution | PARTIAL |
| Signed timestamped funding and basis history | BLOCKED |
| Exact product oracle/corporate-action equivalence, margin, stop behavior | BLOCKED |
| Arcus official 12h reward criterion and retrospective user reward matching | UNKNOWN |
| User's existing Arcus bot actively running at inspection | NO (exited container observed) |
| Phase 2 research inputs sufficient for truthful prospective logging | PARTIAL |
| Sufficient for full executable historical phase 4 PnL or live hedge | NO |

**Next decisive question:** Can SPY/QQQ Arcus passive fills be mirrored through *authenticated* Lighter Standard account at tolerable real bid-ask/funding/basis/latency and without hedge-order/restart failure? Collect bounded read-only synchronized books/funding + our own historical Arcus maker fills and available point attribution. Verify fee tier and actual collateral before completing the `research_session.py init` immutable freeze. Existing dirty work and exposed holdouts remain untouched.

Sources: official Arcus blog, official Aster docs/GitHub, official Robinhood newsroom, public Arcus/Lighter/Aster exchange API GET endpoints (snapshots), Hummingbot local source and tests. No data was modified or traded.
