# Mechanical Premia — DE30 -> JP225 substitution | Bounded exploratory test
**Pre-registered 2026-10-14; new thesis variant; no live orders.**
Source rules: https://mechanicalpremia.substack.com/p/building-a-multi-strategy-portfolio
Existing DEV: `mechanicalpremia-original-four-2013-2024-v1`; consumed holdout: `mechanicalpremia-authorized-2025-2026-ytd-v1`.

## Economic hypothesis
DE30 was the largest H1 loss contributor; a Nikkei CFD may have distinct session/volatility regimes and return distributions. Replacing DE30 with JP225 may improve net Sharpe, Calmar and worst within-year drawdown without worse costs. This is **outcome-selected universe modification**, not an independent replication of the published source or fresh OOS.

## Fixed universe
H1: US500, US100, JP225. D1: US500, US100, JP225, EU50. No DE30 anywhere. Source unchanged: ATR14, BB40/2 and last100 ATR rank median for H1; EMA100 ATR20 BB10/3 %B for D1; D1 exit %B>0.8; source portfolio risk allocation D1 76.64%, H1 23.36% and 50/50 comparator. Split each sleeve among 3 H1/4 D1 instruments. Keep same native Engine, NEXT_BAR, NY17 daily, 2xATR trailing, sizing, 1 bp commission+2 bps slippage PER SIDE, same initial-stop gap. No stop repairs or currency conversion introduced here: this is a direct isolate substitution test.

## Chronological windows / predeclared 84-cell trial family
- Annual reset $100,000 synthetic price units per year 2013 to 2025 full. 2026 scored only through 2026-10-11 23:59 UTC. Preceding July1 warmup.
- For each year pre-register H1-ONLY, D1-ONLY, EQUAL-RISK, SOURCE-RISK at 1.0x costs and SOURCE-RISK at 1.5x and 2.0x (84 native runs). EU50 is absent before 2014-06-02. All attempted cells must be retained.
- Compare **paired per-year** against archived same-year DE30 runs using the identical simulation model, quote units and annual reset. Test years including 2025 and 2026 are already observed. All year results exploratory. Baseline do-not-trade.
- Additional evidence: source/provider data eligibility & H1/D1 final cash/fills/trades identity checks, before/after contribution by named instrument, paired annual Sharpe and drawdown across eligible years.
- **Falsifier**: if replacement does not materially improve paired annual performance and cost-stressed performance, reject substitution. If native model incomplete, data invalid or mixed currency conversion dominates, INCONCLUSIVE for executable economics regardless of numbers.
- Do not optimize selection thresholds, timezones or costs after outcomes.
- No 2026-10-12+ market access; no forward test remaining.
- Explicit statuses for failed runs, no fabricated metric, mark 2026 YTD incomplete and year-reset open positions not carried forward.

## Known research limitations
- Native `ml4t.engineer` verified features, native `ml4t.backtest.Engine`; not a custom price simulator.
- Nikkei trading breaks and Tokyo/CFD broker clock differ from NY17 assumption. Apply original fixed 60-minute complete H1 and existing 1000-minute D1 rule to Nikkei; record exclusions rather than relax after seeing PnL.
- Cross-currency PnL (JPY vs USD/EUR), CFD multiplier, overnight financing and quote ASK not modeled; apparent USD NAV is economically invalid for a real multi-CCY portfolio. Evaluate this as signal/proxy comparison only.
- Old universe comparator also mixes USD/EUR; do not call the comparison FX-neutral.
