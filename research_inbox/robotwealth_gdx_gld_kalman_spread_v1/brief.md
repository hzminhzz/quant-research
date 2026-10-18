# Kalman Filter Pairs Trading with Zorro and R

**Candidate:** `robotwealth_gdx_gld_kalman_spread_v1`
**Capture status:** THESIS_CAPTURED, descriptive only.
**Primary:** Kris Longmore / Robot Wealth, 2019-10-16, https://robotwealth.com/kalman-filter-pairs-trading-with-zorro-and-r/
**Original market/timeframe:** GDX and GLD exchange-traded funds (not gold futures or CFDs); Daily 1440-minute Zorro bars; reverse at ± one predicted-error standard deviation.

## SOURCE_FACT — Original tested or described rules
- Original executable Zorro script Asset1 GDX, Asset2 GLD, StartDate 20060525, EndDate 2019, BarPeriod 1440.
- State-space R routine with delta=0.0001, Ve=0.01; calculated predicted error e and variance Q; single level MaxTrades=1, Spacing=1.
- On e crossing under -sqrt(Q), long GDX and short beta-adjusted GLD; on e crossing above +sqrt(Q), reverse direction; units 1000 in sample.
- Original sample disables spread, commission, and slippage unless COSTS macro is enabled.

## SOURCE_REPORTED_TEST — Not independently verified
- Article shows Zorro event-driven and earlier vectorized R implementations producing similar hedge ratios, positions and equity curve shapes; does not give net-after-cost returns in readable text.

## LOCAL_INFERENCE — Economic hypothesis and null
An adaptive hedge ratio between GDX and GLD can isolate temporary price divergence between gold-mining equities and physical-gold exposure, with the residual expected to mean revert.

Possible mechanism: A latent linear relationship drifts; Kalman innovations identify relative-price deviations from an updated hedge ratio. Gold mining equities also embed operational/equity risks.

Null: the conditional opportunity has no incremental advantage after baseline and costs. Proposed baseline: Static lagged regression-hedged GDX/GLD spread with the same transition/hold policy.

## ADVERSE EVIDENCE AND SELECTION RISK
- GDX/GLD are not a stable cointegrated pair by construction: miners' equity beta and leverage can cause persistent divergence.
- Default source simulation explicitly zeroes trading costs; reversal events may be sensitive to turnover.
- Zorro bar-close decision versus order fill timing needs native parity verification.

## ORIGINAL vs LOCAL ADAPTATION
Original product and source rules above are preserved. No product substitution, parameter repair, local backtest or deployment is authorized; **ADAPTATION_PROPOSAL: NONE**. The author's cited results are source claims, not reproduced alpha.

## SCIENTIFIC DEEPENING — NOT PERFORMED
Original decision/fill clock: Zorro 1440-minute bars using priceClose; signal is based on current observed price; earliest feasible fill depends on broker/event engine and must be validated, not assumed close.

Causal features: Innovation e=GDX_close-(beta*GLD_close+intercept), Q innovation variance; delta=.0001, observation variance Ve=.01 from published R routine.

Original sizing: Original 1000 portfolio units of GDX vs 1000*Kalman beta units GLD; short locate/margin not stated.

Costs: Source code uses zero spread/commission/slippage by default; realistic two-leg fees, spread, borrow and dividends remain unqualified.

Primary falsifier: Adaptive Kalman spread reversals do not outperform an exposure-matched static hedge / neutral residual benchmark after two-leg trading frictions and borrow.

No Phase 3/4 analysis, holdout access, or price-return calculation was performed. PIT availability, exchange calendar, original data provenance, explicit cost oracle and next-executable-fill semantics must be qualified separately.

## UNKNOWN / BLOCKERS
- Original data adjustment conventions from Alpha Vantage; normalized dividend/split prices
- Kalman warm-start and C++/R update parity; timing of fill vs signal close
- Broker ETF borrow, dividend payments, execution costs and point-in-time availability

## Portfolio overlap HYPOTHESES (not measured correlations)
- Risk driver: adaptive relative-value convergence
- Market: US-listed gold miners ETF vs gold ETF
- Horizon: multi-day relative value
- Expected exposure: paired long/short; residual mining-sector and gold risk
- Likely overlap cluster: ETF pairs mean reversion, not crypto cross-sectional momentum
