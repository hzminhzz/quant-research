# Crypto Research Run — 60-Day Cross-Sectional Reversal

## Conclusion

**REJECT.** The pre-registered 60-day canonical reversal signal failed the development gate: mean rank IC 0.0158 with HAC p=0.574. The 30-day and 90-day neighbors were also weak or wrong-signed. The 2024–2025 OOS was not consumed.

## Source

Victoria Dobrynskaya, *Cryptocurrency Momentum and Reversal*, The Journal of Alternative Investments, DOI 10.3905/jai.2023.1.189.

## Pre-Registered Specification

Formation windows 30d / **60d canonical** / 90d; weekly Monday rebalance; long past-loser quartile and short past-winner quartile; point-in-time top-80% trailing-dollar-volume universe; 3 bps one-way base costs.

## Development Diagnostics

| Formation | Mean IC | HAC p | Loser-minus-winner |
|---:|---:|---:|---:|
| 30d | -0.0054 | 0.833 | -1.44% |
| **60d** | **0.0158** | **0.574** | **+0.38%** |
| 90d | -0.0022 | 0.945 | -0.46% |

The fixed gate required IC >=0.02, HAC p<0.05, positive spread, and at least 100 observations. The canonical signal failed both the magnitude and significance requirements.

## Data

19 Binance USDT perpetuals, hourly, 2020–2025. SHA256 `f35452fab6b9a32ebc7e773162575ecf582e62ed5cdfaab200f6808060f5f6b8`.

## Results

OOS consumed: **No**. OOS Sharpe, cost sensitivity, DSR and PBO are N/A.

## Multiple-Testing Audit

Previous trials 30; new trials 3; cumulative **33**.

## Decision

**REJECT**

## Provenance

Runner SHA256: `8f7eb104f317bb5d44d2abdfa8fabff61e8b8832eacfafd113328c6052d42ec5`.
