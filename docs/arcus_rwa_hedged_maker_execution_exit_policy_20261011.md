# Arcus RWA: confirmed maker fills, Lighter market hedge, and holding policy
Date: 2026-10-11. Scope: engineering specification amendment / NOT APPROVED FOR LIVE.

## Execution order (implemented in local Hummingbot code, no orders placed)
1. Choose the Arcus quote *side* using the cross-venue executable gross entry advantage, initial threshold >=2 bps:
   - Arcus buy at maker bid + Lighter sell MARKET at Lighter bid: gross edge = (lighter_bid - arcus_bid) / lighter_mid * 10,000.
   - Arcus sell at maker ask + Lighter buy MARKET at Lighter ask: gross edge = (arcus_ask - lighter_ask) / lighter_mid * 10,000.
   - Only quote the single highest eligible side; if neither passes, quote neither. Reference, spread, basis, inventory and toxic-flow checks still apply. Gross edge excludes fees/slippage/funding and is NOT net EV.
2. Wait for actual confirmed Arcus maker fill. Account position is authority; use FIFO fill ledger, private position reconciliation and durable no-duplicate hedge target before proposing a Lighter MARKET order. Hummingbot `ExecutionStrategy.MARKET` is required on Lighter.
3. Short Lighter when Arcus bought; long Lighter when Arcus sold. Use exact pending target and lot amount, reconcile exchange positions. For partial fills, hedge confirmed net exposure; no fictitious fill.
4. Hold Arcus inventory (and opposite Lighter hedge) for first 12h per surviving fill lot, subject to protective risk exception. While Arcus nonflat, do not quote new entries (no extra lot resetting timer); do not quote a passive unwind before all surviving lots reach 12h.
5. After all Arcus lots aged >=12h, allow only a reduce-size Arcus maker exit if its instantaneous gross unwind edge is >=0bps. Long Arcus exit: sell at Arcus ask, then buy Lighter MARKET at Lighter ask. Short Arcus exit: buy at Arcus bid, then sell Lighter MARKET at Lighter bid. Exit maker qty <= current Arcus position so quote does not reverse net exposure.
6. At 24h (soft deadline, based on oldest lot only once all lots reached 12h), permit passive Arcus closing quotes regardless of instantaneous unwind edge. This is *not a guaranteed exit by 24h* and does not trigger Arcus taker automatically.
7. Emergency: risk limits and exchange failure override duration economically; production needs separately verified combined-equity funding/cost accounting, reduce-only two-venue emergency unwind, partial failures, stale feeds and market slippage protection. Current prototype **fails closed for new quotes** and needs manual response; it does not auto-flat both venues. Lighter MARKET may suffer uncontrolled price gaps.
8. Holding >=12h is a provisional hypothesis based on observed anecdotes, not independently verified Arcus points eligibility. Report rewards separately; do not infer point value or assume guaranteed boost.

## Verified
Repo `/home/quant/dev/hummingbot`, HEAD `36d9c64abc88c8ca59c9905ba2b04a1c557ac137`.
Changed only task-owned new ArcusHedgedRWA controller, tests, README, and task-owned shadow config/examples.
TDD: existing tests first failed as expected for Lighter MARKET and no additional Arcus quotes, then passed after implementation. Added entry-direction, positive/negative spread, 12h exact expiry, 24h passive soft deadline, reduce-size, and Lighter market close tests.
Full related test suite **56 passed**; 6 unrelated preexisting Pydantic warnings. Live-public REST smoke of revised shadow controller succeeded once for both SPY and QQQ, no order actions.
The longer `ml4t-arcus-hedged-shadow-20261011` tmux session was started earlier using the *previous already loaded* code; it was not restarted or killed. Treat its logs as pre-amendment evidence. Use a new job/manifest after the active session completes for extended observation of new entry policy.

## Blocked prior to live use
Cross-venue collateral and full signed funding/commission ledgers; synchronized depth and slippage calibration for Lighter MARKET; authenticated wallet hedge order roundtrip; external hedge profit PnL reconciliation, frozen risk/stop rules and two-venue emergency flatten; reward terms, permitted incentives; actual paper trade soak. Explicit user authorization required to activate live execution. No commit/push.
