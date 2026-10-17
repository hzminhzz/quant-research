# Arcus RWA maker-volume with external delta hedge — Phase 1 decision (2026-10-11)

Status: PHASE_1_DESIGN_FINAL / EXPLORATORY / NOT_APPROVED / NO_LIVE_ACTION.
Decision: Research an **Arcus passive maker inventory + immediate external delta hedge** design, **not a grid**. Neither historical reward profitability nor an Arcus 12-hour scoring rule is verified. Prior metals dual-grid material is explicitly excluded from design evidence.

## Economic objective and mechanism
Arcus venue rewards may compensate for genuinely executed maker RWA notional plus durable exposure, while inventory is hedged on a second venue to reduce price risk. The payment source is **discretionary platform reward allocation**, not trading alpha. The economic thesis only survives if measurable reward efficiency exceeds full trading/hedging/funding/basis/capital costs at plausible point values. Reward-point valuation is unknown; report break-even $ per point rather than assume future dollar value.

### Core policy
- Trade **post-only** on Arcus; cancel/reprice resting quotes only within a rate limit, with reference-price, stale-data and spread checks. No matched/self trades or artificial/manipulative volume. No maker rebate or fill is assumed without evidence.
- Prefer **two-sided risk-conditioned quoting**, but maintain a **single net age-tracked inventory tranche** where possible, with held inventory aged at the lot level. No countertrade may be credited with 12-hour exposure if it flattened net exposure. Quoting stops/reduces when inventory cap or stale external hedge risk is reached. No need to keep quotes live merely for volume.
- On each confirmed Arcus maker fill, hedge only **the net delta change** on a verified *economically equivalent* external contract (initial candidates: Lighter SPY/QQQ, Hyperliquid HIP-3 index exposure; suitability pending Phase 2 contract/price-basis/fee/availability verification). Do not call SP500=SPY or XYZ100=QQQ identical: measure ratio/beta, basis and tracking error before hedge approval.
- Hedging may pay taker fees on the external exchange if that reduces total risk-adjusted cost; no Arcus taker orders for farming. External hedge entry/rebalance/exit, funding and liquidation all count. Partial hedge fills and one-sided disconnects are explicit stress cases.
- Target >=12h holding for intact Arcus net inventory **only if safe**; hedges can rebalance while Arcus remains open. Emergency reduce-only exits, stop-losses and liquidation protection override duration. Inventory aged by real fill timestamp; never pretend a maker candidate is filled or that a 12h exposure qualified for points.
- Select eligible RWA instruments using verified Arcus listings, liquidity, spreads, external cross-venue hedge contract and tradeable calendars. Provisional focus: SPY-USD and QQQ-USD; GLD only if exact listings and matching external hedge validated. Do not hard-code unverifiable pair/venue availability.

## Registered hypotheses and controls
H1: Conditional maker quoting with external delta hedge yields lower drawdown and better net cost per completed Arcus maker notional than unhedged inventory, at the same nominal risk/exposure and selection rules.
H2: Duration >=12h improves observed Arcus points per risk-dollar relative to otherwise comparable short holds; treated as **prospective, unverified** until actual reward observations. It is not an exchange rule in this specification.
H3: Risk-conditioned quotes improve maker-fill markouts and full-cycle costs versus fixed-spread non-grid passive baseline without materially lowering qualified volume.
H4: Hedging reduces risk-adjusted cost after both venues' fees, funding, basis, margin and outages relative to the otherwise identical unhedged strategy.

Pre-register arms:
A: maker-only Arcus passive inventory, external delta hedge, target >=12h (primary).
B: same Arcus policy, unhedged, target >=12h (hedge effect).
C: same as A but eligible shorter target holding, if safe (duration effect; separately identify true age).
D: same as A with fixed spread/reprice schedule (quote policy effect).
E: low-volume, >=48h Arcus maker OI control (capital efficiency).
F: Arcus taker additions allowed only as an **observational historical comparison**, not selected as live strategy; use actual reward/cost records if available, no synthetic points.

## Exact accounting
Log all Arcus confirmed fills with order ID, maker flag, side, price, quantity, timestamp and fee; open/close timestamp, notional, net exposure and age. Separately log external hedge fills, fees, bid/ask spreads, funding payments at timestamps, marked/unrealized/realized price PnL, leverage, liquidation buffer, and cash/margin tied up on each venue. Count gross trade notional and completed notional without double-counting cancels or unfilled resting orders.

Primary measurable outcome: **risk-adjusted all-in cost per $1 million executed eligible Arcus maker notional**, with drawdown and unhedged exposure constraints. Secondary: daily effective notional per committed USDC, time-integrated Arcus OI, fill/hedge lag and completed-cycle inventory-age share. Prospective points efficiency: observed weekly Arcus points / combined locked capital and observed points / actual eligible maker notional. Report cost per point, break-even $/point and net profit for *explicit* reward valuation scenarios; do not claim that platform scoring is known.

Total economics = Arcus trading PnL + external hedge trading PnL + signed Arcus funding + signed hedge funding - all venue execution costs - financing/borrowing/transfer costs + separately labeled *scenario* points value. Distinguish ex-reward and including-hypothetical-reward economics. Cross-venue basis and collateral fragmentation must be observable.

## Risk budget and falsifiers
Research scenario (not permission to trade): evaluate $1,000 combined equity, max total gross exposure $2,000, per-instrument gross cap $1,000, target net delta <= 15% of combined equity during healthy operation, and max risk-equity loss $100. These are preregistered pilot **scenario assumptions**, not confirmed safe live sizing and not changes to existing account-wide/controller limits.
- Hard stop if >$100 cumulative loss or drawdown in model; halt new orders on unhedged delta beyond threshold, unexpected hedge latency, stale prices, inconsistent position reconciliation, insufficient margin, or loss of any venue connectivity. Emergency reduce-only/market unwind is allowed; model worse-case slippage/gap; no assertion hard stop prevents losses beyond $100.
- Reject cost-economics claim if primary all-in *ex-reward* loss worsens after hedging without sufficiently lower risk, or if net inventory/hedge basis causes unacceptable tails.
- Block Phase 4 profitability judgment where order-book/queue/actual maker fill evidence, contract equivalence, funding or signed fees are absent. OHLCV touched limit does not establish fill or maker eligibility.
- Reject 12h reward multiplier hypothesis if matched prospective allocation observations show no replicable improvement; if observations inadequate, label INCONCLUSIVE, not PASS.
- If reward allocation is discontinuous or unknown, do not infer $-denominated EV. Use break-even valuation and uncertainty bands. Reward points are not cash until realized.
- Do not optimize the strategy for deceptive/wash volume, self-trades, or rule circumvention.

## Phase 2 input gate (must verify; not claimed now)
1. Arcus official current terms: genuine maker order/fill eligibility, RWA boosts, minimum-duration policy, account restrictions, wash-trade bans, fee tiers, contract specs, lot/tick, funding and settlement/session times.
2. Actual Arcus live-account historical fills and weekly points attributions if available; distinguish others' anecdotal 220 points/$140 from our reproducible results; verify 12h holding at lot/net level.
3. Exact Lighter/Hyperliquid contract mappings, tick and funding regimes, executable bid/ask and order book depth, margin/liquidation, rates, hedge execution latency and API support; reject non-equivalent proxies.
4. Canonical minute market and order-book histories; fill simulation must incorporate queue uncertainty, adverse selection and conservative missed fills; no fabricated maker eligibility.
5. Proposed chronological periods, already-seen dates and genuinely unobserved final window: preserve existing protected holdouts. Prospectively record weekly reward evidence after frozen policy.

## Research governance / operational boundaries
Seven phases: (1) thesis and preregistration, (2) source/data/contract gate, (3) causal exposure, fill/holding studies, (4) native ml4t Engine event backtest or explicit BLOCKED when matching/queue cannot be modeled, (5) chronological/prospective validation, (6) basis/funding/outage/fee/reward refutation, (7) independent audit and adopt/reject/inconclusive/blocked recommendation. All future trials predeclared; failures and inconclusive results retained; final holdout never retested or relabeled. Comply with AGENTS.md and docs/research_sessions.md; use installed ML4T skills and native Engine, not custom backtest loops.
This Phase 1 is a **strategy decision/specification freeze**, not a native CLI `research_session.py init` freeze: the exact Arcus data identity, verified costs, contract mappings and legitimate untouched holdout are missing. Prepare a schema-valid session in Phase 2 and call init only when those exist; do not create an immutable knowingly blocked session now. Never start/modify live Arcus, existing Hummingbot bot, orders or collateral without distinct user authorization. Preserve unrelated dirty work. No source code/backtests yet.
