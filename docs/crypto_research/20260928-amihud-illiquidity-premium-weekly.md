# 20260928-amihud-illiquidity-premium-weekly — REJECT

## Conclusion
**REJECT.** Development gate failed; OOS not consumed.

## Source
https://onlinelibrary.wiley.com/doi/full/10.1002/ijfe.2431

## Hypothesis / mechanism
Higher lagged Amihud illiquidity predicts higher subsequent weekly cryptocurrency returns.

- Strategy family: `amihud_illiquidity_premium`
- Research archetype: `cross_sectional_factor`

## Pre-Registration
The exact candidate specification is preserved in `run_log/crypto_research/runs/20260928-amihud-illiquidity-premium-weekly-manifest.json`. Parameter variants are counted as statistical trials; no post-hoc winning variant is promoted.

## Universe and data
Each Monday 00:00 UTC, eligible Binance USD-M USDT perpetuals with complete lagged feature history; retain top 100 by lagged trailing-30-day quote volume before illiquidity sorting. No future-survival filter.

## ML4T Engineer Usage
This cycle used the repository's leakage-control conventions and direct transparent feature construction where appropriate. No feature-catalog sweep was used as a strategy generator.

## Signal Diagnostics
```json
{
  "14": {
    "n_weeks": 104,
    "mean_ic": 0.0026656493403364786,
    "ic_ir": 0.015403600424684834,
    "top_minus_bottom": 0.003995719861420354
  },
  "30": {
    "n_weeks": 104,
    "mean_ic": -0.009213051813147955,
    "ic_ir": -0.05048191925976764,
    "top_minus_bottom": 0.00032126129103129177
  },
  "60": {
    "n_weeks": 104,
    "mean_ic": -0.015204553577087455,
    "ic_ir": -0.079804098712099,
    "top_minus_bottom": 0.004375051291064467
  }
}
```

## Results
- Classification: `REJECT`
- Development gate passed: false
- OOS consumed: false
- Success-gate candidate: false
- Trial accounting: `{"previous_parameter_trials":71,"new_parameter_trials":3,"cumulative_parameter_trials":74}`

```json
{
  "14": {
    "metrics": {
      "annualized_sharpe": 0.5045236289111419,
      "total_return": 0.14008947413012462,
      "max_drawdown": -0.13498308709504558,
      "n_weeks": 104,
      "mean_gross_leverage": 1,
      "turnover": 53.610784313725496
    }
  },
  "30": {
    "metrics": {
      "annualized_sharpe": -0.07034297749951132,
      "total_return": -0.051252440540335065,
      "max_drawdown": -0.1998171619494884,
      "n_weeks": 104,
      "mean_gross_leverage": 1,
      "turnover": 40.676797385620915
    }
  },
  "60": {
    "metrics": {
      "annualized_sharpe": 0.5608217416877722,
      "total_return": 0.18226560069860587,
      "max_drawdown": -0.09400054681131065,
      "n_weeks": 104,
      "mean_gross_leverage": 1,
      "turnover": 29.285294117647062
    }
  }
}
```

## Breadth / Contribution
Universe symbols reported: 609. Asset contribution details, when available, remain in the structured result rather than being truncated here.

## Robustness
```json
{}
```

## Failure Analysis
Development gate failed; OOS not consumed.

## Multiple-Testing Audit
All preregistered variants remain counted. DSR/PBO are reported in the structured result when meaningful; development-gated candidates do not claim confirmation evidence.

## Decision
REJECT. No automated deployment or production-readiness claim.

## Reproduction
- Runner: `scripts/run_crypto_amihud_illiquidity_premium_weekly.py` or the exact runner named in the manifest/result.
- Manifest: `run_log/crypto_research/runs/20260928-amihud-illiquidity-premium-weekly-manifest.json`
- Structured result: `run_log/crypto_research/runs/20260928-amihud-illiquidity-premium-weekly-result.json`

## Provenance
Generated from the durable preregistration and structured result without changing the research decision.
