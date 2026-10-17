# Mechanical Premia source-universe extension — preregistered 2013–2024
Date: 2026-10-13. Separate research object from frozen mechanicalpremia-two-engine-mvp-20261013.
Source: https://mechanicalpremia.substack.com/p/building-a-multi-strategy-portfolio
Source engine (unchanged): H1 breakout US500/US100/DE30; D1 mean-reversion US500/US100/DE30/EU50; long-only.

## Objective
Replicate source rules in a four-index Dukascopy CFD **bid-price-proxy** multi-sleeve native ML4T simulation, without touching protected >=2025-01-01. Quantify whether additional 2013–2024 history supports original portfolio diversification beyond the weak 2024-only evidence.

## Inputs and eligibility
- US500 = Dukascopy usa500idxusd, canonical index_minute_ES, start 2013-01-01.
- US100 = Dukascopy usatechidxusd, canonical index_minute_NQ, start 2013-01-01.
- DE30 = Dukascopy deuidxeur, canonical index_minute_DAX, start 2013-09-30.
- EU50 = Dukascopy eusidxeur, canonical index_minute_EUSIDXEUR, start 2014-06-02.
- Canonical authority: /home/quant/dev/quant/ml4t-data/.data/store; only year=2012..2024 for warmup and execution; <=2012 only warmup where present, no scored pre-2013 records. Source files are daily-Hive parquet and acceptance records. Ignore all year>=2025 partitions entirely.
- Input inventory and partition digest captured and checked at runtime. No replacement downloads, no recasting exchange futures as CFDs. Unit exposure and foreign exchange currency conversion are not broker certified.
- Baseline original source 76.64% D1 /23.36% H1 total nominal risk budgets; equal-risk 50/50, each split across eligible instruments 4 D1/3 H1. Risk budget 1% NAV global; native per-instrument leverage and total gross 1.9x cap are research adaptations, not verified source MT5 matching.
- D1 session = 17:00 America/New_York to next 17:00 for all assets, SOURCE CLOCK UNVERIFIED. EUSIDXEUR min >=600 actual 1m quotes per day (chosen before returns, lower than original >=1000 threshold which wrongly blocks it). Other markets >=1000 actual rows; H1 >=60 rows for complete-hour signal bars; zero-volume/stale flags retained in evidence, no synthetic quotes/forward fill. Holidays/short days explicitly excluded by rule. EU50 H1 not traded (article only D1 EU50).
- Signals after last completed bar, native NEXT_BAR open. Source MQL5 ATR14/20, EMA100, BB40/2 and BB10/3, ATR100 rank median upper-middle, H1 trailing 2x ATR, D1 ghost-risk ATR20 with no actual stop. H1 entry-minute stop latency is unresolved and MUST not be called faithful.
- Costs: illustrative 1bp commission + 2bps slippage per side; source uses bid OHLC, asks/spreads and overnight carry unknown. Fixed stressed variants 1.5x and 2x costs on source portfolio. Real broker economic verdict must remain INCONCLUSIVE without these terms.
- Yearly bounded simulations run independently (account reset, positions NOT carried across boundary); evaluate every year 2013..2024 with one-year warmup. Do NOT compound/reset trade-equity as though continuous 12-year backtest. Provide by-year wins, net PnL, equity Sharpe, DD and non-comparability of reset periods.
- Common-history comparison begins after EU50 has 100 complete eligible daily bars following 2014-06-02 (actual warmup-dependent). Report availability-adjusted and common-universe panels separately. Year-end open positions marked, never force-closed as source alteration.

## Seven predeclared trials
1. DATA-QUALIFICATION: canonical identity/acceptance, source, timestamps, completeness, partitions, bid semantics and EUR issue.
2. H1-SOURCE-3: all eligible years for original H1 US500/US100/DE30 only.
3. D1-SOURCE-4: all eligible years for original D1 US500/US100/DE30/EU50 only.
4. EQUAL-RISK-7: 3 H1+4 D1 at equal sleeve weights.
5. SOURCE-RISK-7: 3 H1+4 D1 at fixed 76.64/23.36.
6. COST-STRESS: fixed 1x, 1.5x and 2x cost ladder for SOURCE-RISK-7, no parameter search.
7. NATIVE-AUDIT: native fills, future-bar timing, equity = cash+positions, stops, year-boundary behavior, missingness, full attempt ledger and holdout proof.

## Falsifier and decision
Inconclusive if data/venue conversion or stop-fidelity remains unresolved, or 2013–2024 sample too sparse for any sleeve. No promise of Sharpe>0. If on comparable eligible segments SOURCE-RISK cannot improve daily Sharpe AND drawdown over equal-risk and standalone source sleeves after reasonable costs, reject diversification thesis for these markets. Negative results preserved, no parameter rescue.
No 2025 final test and no live orders. Original session and V1/V2 results immutable.
