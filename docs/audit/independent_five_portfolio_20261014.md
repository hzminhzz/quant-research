# Independent Five — Correlation, Risk Contribution, and Multi-Strategy Portfolio

**Date:** 2026-10-14. **Decision:** exploratory evidence supports a
diversified prototype; **NOT APPROVED FOR LIVE TRADING**.
The five strategies remain independent and **are NOT part of Shannon-20**.

## Source contracts and method

Reference template: the user-supplied original `portfolio.py` for the
Shannon 20-strategy collection, with daily normalized return streams,
strategy correlations, capped allocation comparisons, daily rebalancing
without cross-portfolio turnover costs, and separate train/future periods.

Inputs: native `ml4t-backtest==0.1.7` equity ledgers from
`run_log/independent_five_full_history_20261014`. All backtest
source data and original strategy parameters unchanged.

Methodology: ML4T portfolio/risk, backtest-overfitting, walk-forward,
transaction-cost and lookahead guardrails. `ml4t.diagnostic.api.PortfolioAnalysis`
provides official Sharpe, CAGR/annual return, Sortino, max drawdown,
Calmar, VaR and CVaR for combined *daily after-cost sleeve return streams*.
No alternative execution simulator is used.

**Common calendar**: Jan 1, 2020 to Oct 9, 2026, 1,768 weekdays,
prior to the repository's Oct 12 protected boundary.
BTC is 24/7 on UTC days; ES closes at New York 17:00.
As in the Shannon template, Saturday/Sunday BTC PnL moves to the
following business day, but weekend **returns are geometrically
compounded**, not summed. Missing closed ES business days are 0%.
This alignment is an analytical proxy, not synchronized position PnL.
UTC calendar-day correlations are also saved as a cross-check.

Use returns from the native final equity stream, **not cumulative
prices/equity**, for correlations. Inputs each had 100k independent
capital and after-cost native account accounting.

## Daily correlation matrix (2020-2026)

| | BTC Pivot | BTC Donchian | Three Red | Slope | RSI30/50 |
|---|---:|---:|---:|---:|---:|
| BTC Pivot | 1.000 | 0.573 | 0.060 | 0.031 | 0.048 |
| BTC Donchian | 0.573 | 1.000 | -0.064 | -0.042 | -0.042 |
| Three Red | 0.060 | -0.064 | 1.000 | 0.331 | 0.333 |
| Slope | 0.031 | -0.042 | 0.331 | 1.000 | 0.377 |
| RSI30/50 | 0.048 | -0.042 | 0.333 | 0.377 | 1.000 |

BTC equal-weight **market cluster** versus three-strategy ES equal-weight
cluster have only **0.012** daily Pearson correlation (and 0.012
in 2023+). Group exposure, not arbitrary five-strategy count, is
the useful diversification axis.

**Conditional co-activity**: both strategies traded on the same
business day for only 116 days of Slope/RSI; among those days the
conditional return correlation is **0.925**. Three Red/RSI:
90 jointly active days and **0.769** conditional correlation.
BTC Pivot/Donchian: 842 jointly active days and **0.744**.
Thus low unconditional correlation often comes from intermittent
exposure, not independent price risk in joint market stress.

**Rolling and regime sensitivity**: BTC Pivot/Donchian 252-day
correlation median **0.66**, p10 **0.06**, p90 **0.84**.
Slope/RSI median **0.47**, p10 **0.23**, p90 **0.66**.
Post-2022 daily Pivot/Donchian is **0.619**, Slope/RSI **0.546**
versus **0.542** and **0.309** respectively during 2020-22.
Both same-market groups became *more* correlated in later historical
observations. Weekly correlations: Pivot/Donchian **0.634**;
Slope/RSI **0.476**. The portfolio is closer to **two market
risk clusters** than five independent underlying markets.

## Analytical multi-portfolio comparison

Starting capital 100,000 (common portfolio analytical equity scale).
Daily rebalance of *already cost-adjusted native strategy return streams*.
This DOES NOT rerun the five strategies inside one combined broker account
and DOES NOT charge an additional capital-transfer/rebalance fee.

| Allocation | Total return 2020-Oct2026 | Sharpe | MDD | Calmar | CVaR 95%, daily |
|---|---:|---:|---:|---:|---:|
| EW five: 20% each | +118.09% | 1.075 | -11.07% | 1.061 | -1.48% |
| 50/50 BTC-ES, equal within groups | +141.83% | 1.013 | -15.06% | 0.891 | -1.82% |
| 50/50 BTC-ES, inverse-vol within groups (2020-22 only) | +133.98% | 1.041 | -13.34% | 0.966 | -1.66% |
| **Market-group equal-risk training 2020-22** | **+70.45%** | **1.240** | **-6.58%** | **1.200** | **-0.86%** |
| RSI alone benchmark | +43.76% | 0.821 | -7.91% | 0.672 | -0.93% |

The market-group equal-risk rule was **added after initial equal-capital
risk-contribution diagnostics**; it is EXPLORATORY and not proof of
prospective optimality. Within each group, weights are equal. Group
capital budgets use inverse volatility of the two group baskets
measured in 2020-22 only; maximum 35% per sleeve. No Sharpe
optimization or future data used for weight determination.

**Frozen market-group equal-risk allocation:**
- BTC Pivot Breakout: **8.91%**
- BTC Donchian: **8.91%**
- Three Red ES: **27.39%**
- Slope ES: **27.39%**
- RSI30/50 ES: **27.39%**

**Risk concentration matters more than capital weight:**
- Equal-capital EW five uses 40% BTC capital but BTC supplies
  **91.8% of full-window portfolio variance**: Pivot 59.3%,
  Donchian 32.5%, all ES only 8.2%.
- Market-group risk-balanced uses 17.82% BTC capital but BTC
  supplies **55.1% of full-window variance** (44.9% ES).
- Group-risk-balanced BTC risk rises to **68.1%** in reviewed
  2023-25 data, despite unchanged 2020-22-trained weights.

### Chronological held-weight comparison

| Portfolio | 2020-22 Sharpe | 2023-25 Sharpe | 2023-25 MDD | 2026 YTD Sharpe |
|---|---:|---:|---:|---:|
| Equal five | 1.411 | 0.715 | -11.07% | 1.050 |
| Group risk-balanced | 1.491 | 0.888 | -5.24% | 1.474 |

**2023-25 is already observed history, NOT a sealed final test.**
Group-risk-balanced post-2022 (2023-25) total return was
**+15.96%** versus EW five **+24.10%**. It exchanges absolute
return for lower portfolio volatility and better drawdown.

### Rebalancing is a key execution qualification blocker

The user's original Shannon-20 analyzer also uses daily rebalancing
with **no separate rebalancing fees**. We reproduced that explicitly,
then examined a **static initial-capital ownership** aggregation, with
the five native sleeve accounts left to drift without cross-sleeve
rebalancing.

| Allocation | Model | Total return | Sharpe | MDD |
|---|---|---:|---:|---:|
| Equal five | Daily rebalance analytical | +118.09% | 1.075 | -11.07% |
| Equal five | Static initial capital | +123.6% | 0.720 | -32.0% |
| Group risk-balanced | Daily rebalance analytical | +70.45% | 1.240 | -6.58% |
| Group risk-balanced | Static initial capital | +75.40% | 0.776 | -15.52% |

Restoring constant capital weights would imply *approximately*
**69.5% annual one-way portfolio turnover** for EW and **44.4%**
for group risk-balanced under a frictionless transfer assumption.
This measures theoretical capital transfers only; it is not an
independently validated broker execution-cost calculation. Some
transfers may occur as cash, while cross-asset margin and
collateral constraints may require more real trading.

### Native-sleeve execution friction sensitivity (after observing baseline)

Ran 10 additional native ML4T Engine experiments using exact frozen
price/signal artifacts with 2x and 3x both commission and slippage.
Each scenario's final native equity streams were recombined with
the SAME frozen portfolio weights. No additional portfolio-rebalance
fee charged.

| Model | Base return | 2x return | 3x return | 3x Sharpe | 3x MDD |
|---|---:|---:|---:|---:|---:|
| Equal five | +118.09% | +105.86% | +94.32% | 0.922 | -13.8% |
| Group risk-balanced | +70.45% | +61.01% | +52.09% | 0.980 | -6.7% |

This is useful cost sensitivity, **not** complete crypto funding,
ES spread, or capital-transfer cost qualification.

## Interpretation and next action

1. **Keep all five as separate research entries**, not as Shannon
   members. Strongest diversification is between BTC and ES.
2. **Retain equal-five as no-fitting benchmark** but do not label it
   equal-risk: it is 92% BTC variance.
3. **Use group-risk-balanced as a research allocation candidate**;
   it has the best analytical Sharpe, drawdown and downside tail
   among the fixed comparisons, plus superior 2023-25 reviewed
   risk metrics.
4. Do **NOT** treat this as a deployable five-sleeve execution
   portfolio. Exact SPY ETF source parity, BTC perpetual funding,
   broker-specific financing, shared-account margin, true net
   rebalancing costs, simultaneous same-symbol orders and source
   rule parity are still missing.
5. No valid new unobserved holdout was opened. Strategies were
   selected using 2020-22 positive Sharpe; the number of earlier
   author-level trials is unknown.

## Reproducibility

```sh
uv run python -m scripts.analyze_independent_five_portfolio_20261014
uv run python -m scripts.audit_independent_five_portfolio_20261014
uv run python -m scripts.stress_independent_five_portfolio_20261014
uv run python -m pytest -q -o addopts='' \
  tests/test_independent_five_portfolio_20261014.py \
  tests/test_independent_seven_native_features.py
```

Results:
`run_log/independent_five_correlation_portfolio_20261014`.
This directory deliberately mirrors names familiar from the
Shannon-20 package: `gewichte.csv`, `korrelation.csv`,
`risikobeitrag.csv`, `kennzahlen_portfolios.csv`,
`kennzahlen_strategien.csv`, `strategie_renditen.csv`,
`portfolio_renditen.csv`, plus richer regime correlation,
static capital and cost stress JSON records.

`audit.json`: all matrix, cutoff, weight, portfolio-equity identity,
risk-contribution and native-ML4T-metric integrity checks PASS.
This audit is NOT a claim that combined portfolio market fills
were re-simulated, source instruments replicated, or a true untouched
holdout passed.
