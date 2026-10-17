# Mechanical Premia Two-Engine Portfolio — MVP Research Mission
Date: 2026-10-13. Status: PREREGISTRATION INTENT; no outcomes observed.
Source: https://mechanicalpremia.substack.com/p/building-a-multi-strategy-portfolio
Original article: "Building a Multi-Strategy Portfolio (Part 1): Sizing Fast Engines vs. Patient Setups" (2026-09-01).
Original MQL5 source MUST be fetched/archived and fidelity checked; user supplied no MQL5 file.

## Objective and thesis
Test whether long-only equity-index D1 mean reversion and H1 volatility breakout form a complementary portfolio and improve net risk-adjusted daily equity and worst drawdown compared with either standalone sleeve, at the SAME total permitted risk.
Expected mechanisms: medium-term equity drift plus dip recovery for D1; quiet-to-expanding momentum for H1. Two different exits and trading clocks may diversify. Overlapping long equity beta can defeat diversification.

## Bounded exploratory scope
Use LOCAL canonical ES/NQ index CFD/proxy data from ml4t-data or existing processed datasets, only if provenance, contract semantics, timezones, DST, chronological coverage, quote/spread and mapping are verified. Treat CFDS as proxies, NOT CME futures and NOT automatically broker-executable; do not import futures multipliers without evidence. Select the longest well-verified common DEVELOPMENT interval ending strictly before any project-protected holdout boundary. Never touch protected final test dates; if no safe common interval, stop with BLOCKED/INCONCLUSIVE, not fabricated results. No DE30/EU50 for this bounded MVP. 1-minute source aggregated to actual session-aware H1 and D1 bars; respect partial bars and DST.

## Exact source engine rules (fixed, not tuneable)
H1 LONG: ATR14(last closed 1h bar) < median(last 100 closed H1 ATR14); close of previous H1 > UPPER 40-bar Bollinger band, 2.0 SD. Entry after bar closure at next available ask (first eligible next bar), no same-bar filling. Initial protective STOP bid 2x last completed H1 ATR below entry; trailing stop updated no more frequently than available 1m bid reference, monotone nondecreasing, using ONLY last completed H1 ATR. No fixed profit target.
D1 LONG: close(last completed D1) > EMA100; ATR20(last closed D1) < median(last 100 closed D1 ATR20); %B(last closed D1, BB10, 3SD) < 0.2. Exit when last completed D1 %B > 0.8; use next available tradable ask/bid appropriately after decision. Source MQL5 triggers D1 executor every new H1, repeats same prior D1 signal until a position is opened, and uses GHOST stop distance ATR20 for SIZE only, without an actual D1 hard stop. Preserve this distinction, flag true tail risk. Do not silently add protective stop.
H1 BB source iBands CopyBuffer indexes must be audited against MQL5 documented buffer order; ensure actual upper band, not midline.

## Portfolio tests frozen BEFORE observing outcomes
Trial IDs: SOURCE-PARITY; DATA-ELIGIBILITY; H1-ONLY; D1-ONLY; PORTFOLIO-EQUAL-RISK; PORTFOLIO-SOURCE-RISK (76.64% D1 / 23.36% H1 risk budgets). These are a predeclared six-trial family; never optimize variants based on observed profitability. Run source-risk versus equal risk and standalone at identical total 1% nominal per-trade risk budget; enforce explicit gross and concurrent exposure budget, reject/cap infeasible positions and retain attempted orders. Disclose if source sizing cannot be replicated because CFD broker contract details unavailable. Fixed percentages are source hypothesis, not optimized.

## Economic falsifier and verdict
REJECT diversification thesis if source-risk portfolio shows no improvement in net daily-equity Sharpe AND no improvement in max drawdown versus equal-risk variant and standalone comparators within eligible development, or if performance only survives with missing costs, impossible fills or inconsistent quote/contract mapping. INCONCLUSIVE if sample too short, malformed source/clock, costs unavailable, engine lacks required fill semantics, or uncertainty overlaps material zero-effect region. VALIDATE MVP only when native backtest is auditable, cost-stressed positive net expectancy and benefits relative to single-sleeve AND equal-risk approach are stable across chronological development subperiods; validation is separate from holdout and NO live approval.

## Costs, clock and audit
Obtain product-specific documented commission, bid/ask spread, slippage, overnight financing, position size and margin/contract metadata. If absent, label assumed proxy and carry a conservative cost-stress ladder, no execution-validity claim. Signals use close[t]; fills at next permitted tradable observation, not close[t]. Native ml4t.backtest.Engine/DataFeed/Strategy only. Verified ml4t.engineer features or certified numerical-parity extension only; no custom backtest or metric engine. Account for 1min intrabar stop uncertainty and use pessimistic fills where unresolvable. Audit holidays, exchange sessions, DST, open gaps, spread, fills, order side, risk, margin, cash/positions/equity; use source-code spot checks and independent invariants.

## Reporting and preservation
Ledger every planned, failed, inconclusive or completed attempt before interpreting performance. Preserve session ID, source/code/data hashes, ML4T skill identities, versions, config, native engine evidence, metrics, and trial family. Report trades, wins, expectancy, net PnL, Sharpe DAILY equity, Calmar, DD, period breakdown, costs/stress, and uncertainty when estimable. Missing metrics explicitly undefined. Do not cherry pick profitable periods or touch protected holdout. No live orders. Do not modify or stage unrelated dirty files.
