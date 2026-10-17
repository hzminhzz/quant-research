# Candidate 3: US500 + US100 only — Mechanical Premia source H1 + D1

**Research object:** mechanicalpremia-us500-us100-2013-2026-v1. New, frozen before C3 outcomes; no live trading.
**Purpose:** Fair three-way comparison with archived C1 original DE30/EU50 and post-selected C2 JP225/EU50. Same canonical Dukascopy 1m provider, bars, native ML4T indicator and execution semantics, dates, costs, portfolio risk budgeting.

## Hypothesis and falsifier
Removing non-US index sleeves may eliminate weaker breakout signals and extra session/FX heterogeneity. **Do not assume removing instruments increases returns or diversification.** Falsify the C3 improvement thesis if cost-stressed mean annual return, matched-year daily-equity Sharpe and drawdown do not improve vs C1/C2, or performance is concentrated in one observed regime. This is exploratory and entirely seen data, NOT virgin OOS validation.

## Fixed universe and weights
- H1: US500, US100; D1: US500, US100. Do NOT carry DE30, JP225, EU50.
- Unchanged H1: last completed H1 close > upper BB(40,2), ATR14 below 100-bar rank median; H1 2x ATR trailing stop.
- Unchanged D1: completed D1 close > EMA100, ATR20 below its 100-day median, BB(10,3) %B<0.2; D1 exit %B>0.8, no hard stop.
- Source risk: H1 sleeve 23.36% / D1 sleeve 76.64% of nominal 1% risk, divided equally among two respective instruments. Equal-risk benchmark 50/50. 1.90x overall gross-notional cap shared across four virtual sleeve legs, same native broker methods.
- Initial H1 STOP attaches one 1m callback late in prior code; intentionally unchanged for comparative isolation. No feature optimization, margin strategy variation, timezone tuning or signal edits.

## Dates, costs, research boundary
- Scored calendar years 2013–2025 and 2026 YTD [2026-01-01,2026-10-12). Previous-year July1 warmup only.
- Hard prohibition reading market data at or after 2026-10-12. Original 2025+ final holdout was explicitly consumed by earlier user request; now historical exploratory evidence, not pristine.
- 1x native direct cost = 1bp commission + 2bps slippage PER SIDE; source-risk 1.5x and 2x. Bid spread, actual broker rollover financing, contracts and margin details still unqualified.
- Independent annual $100,000 price-unit backtest reset; preserve 2026 open position mark, no cross-year carry. Report yearly series and mean/median annual, positive years, exposure, win rate, daily equity Sharpe, Calmar, maximum intra-year DD. Do not invent full-horizon CAGR/Sharpe from resets.

## Predeclared 84 cells and acceptance
14 annual years × [H1-only, D1-only, equal-risk portfolio, source-weighted portfolio, source-weighted 1.5x costs, source-weighted 2x costs]. Use only `ml4t.engineer.compute_features` registry and native `ml4t.backtest.Engine`. Freeze before any C3 outcome. Retain failed attempts, logs, file identities. Reject certification if entry/fill time causality, Broker cash+positions=equity, data identity, cost or complete trial accounting fail. Compare C1/C2/C3 on same year basis. No future-date backfill, no hidden parameter rescue.
