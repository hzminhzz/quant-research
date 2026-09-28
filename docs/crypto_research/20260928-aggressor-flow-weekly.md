# 20260928-aggressor-flow-weekly — REJECT

## Conclusion
**REJECT.** Development gate failed; OOS not consumed.

## Source
https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7301919

## Hypothesis / mechanism
Persistent aggressor-side buy pressure contains informed-flow information; perpetuals with higher trailing taker-buy imbalance outperform those with lower imbalance over the following week.

- Strategy family: `aggressor_order_flow`
- Research archetype: `not specified`

## Pre-Registration
The exact candidate specification is preserved in `run_log/crypto_research/runs/20260928-aggressor-flow-weekly-manifest.json`. Parameter variants are counted as statistical trials; no post-hoc winning variant is promoted.

## Universe and data
Binance USD-M USDT perpetuals first listed by 2021-12-31, point-in-time availability, excluding BTCDOMUSDT

## ML4T Engineer Usage
This cycle used the repository's leakage-control conventions and direct transparent feature construction where appropriate. No feature-catalog sweep was used as a strategy generator.

## Signal Diagnostics
```json
{}
```

## Results
- Classification: `REJECT`
- Development gate passed: false
- OOS consumed: false
- Success-gate candidate: undefined
- Trial accounting: `{"previous_parameter_trials":51,"new_parameter_trials":3,"cumulative_parameter_trials":54}`

```json
{
  "72": {
    "metrics": {
      "annualized_sharpe": -0.3117609275082484,
      "total_return": -0.07155886181025328,
      "max_drawdown": -0.18241820019842891,
      "n_weeks": 104
    },
    "by_year": {
      "2022": {
        "total_return": 0.06575954486887237,
        "sharpe": 0.6709950406857469
      },
      "2023": {
        "total_return": -0.1288455799811956,
        "sharpe": -1.3128624230696804
      }
    }
  },
  "168": {
    "metrics": {
      "annualized_sharpe": 0.03882814327558334,
      "total_return": -0.0037679851025300692,
      "max_drawdown": -0.17145193810259207,
      "n_weeks": 104
    },
    "by_year": {
      "2022": {
        "total_return": 0.006430025424360553,
        "sharpe": 0.11236383900832242
      },
      "2023": {
        "total_return": -0.010132856005156343,
        "sharpe": -0.04094798567751746
      }
    }
  },
  "336": {
    "metrics": {
      "annualized_sharpe": 0.36883967104128,
      "total_return": 0.07881823257474219,
      "max_drawdown": -0.15582967657737823,
      "n_weeks": 104
    },
    "by_year": {
      "2022": {
        "total_return": 0.07583740151257157,
        "sharpe": 0.6293153541964103
      },
      "2023": {
        "total_return": 0.0027707077835184,
        "sharpe": 0.08085494267618801
      }
    }
  }
}
```

## Breadth / Contribution
Universe symbols reported: 139. Asset contribution details, when available, remain in the structured result rather than being truncated here.

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
- Runner: `scripts/run_crypto_aggressor_flow_weekly.py` or the exact runner named in the manifest/result.
- Manifest: `run_log/crypto_research/runs/20260928-aggressor-flow-weekly-manifest.json`
- Structured result: `run_log/crypto_research/runs/20260928-aggressor-flow-weekly-result.json`

## Provenance
Generated from the durable preregistration and structured result without changing the research decision.
