# Crypto Research Run — Monthly MAX Effect

## Conclusion

**REJECT.** The 30-day MAX factor produced a positive top-minus-bottom development spread (+1.48% per week), but the pre-registered rank-IC condition failed with mean IC -0.0541 and HAC p=0.0206. The relationship was not monotonic in the required direction, so 2024–2025 OOS was not consumed.

## Source

Ozdamar, Akdeniz & Sensoy (2021), *Lottery-like preferences and the MAX effect in the cryptocurrency market*, Financial Innovation, DOI 10.1186/s40854-021-00291-9.

## Pre-Registered Specification

MAX = maximum completed UTC daily return over 14d / **30d canonical** / 60d. Weekly Monday rebalance; long highest-MAX quartile / short lowest-MAX quartile; point-in-time top-80% lagged trailing-dollar-volume universe.

## Development Diagnostics

| MAX window | Mean IC | HAC p | High-minus-low |
|---:|---:|---:|---:|
| 14d | -0.0336 | 0.230 | +0.66% |
| **30d** | **-0.0541** | **0.0206** | **+1.48%** |
| 60d | -0.0513 | 0.0232 | +1.44% |

The fixed gate required positive IC >=0.02, p<0.05, and a positive spread. The canonical signal failed the IC direction and magnitude criteria.

## Data

19 Binance USDT perpetuals, hourly, 2020–2025. SHA256 `f35452fab6b9a32ebc7e773162575ecf582e62ed5cdfaab200f6808060f5f6b8`.

## Methodology Note

An initial zero-observation run identified a rolling-window minimum-observation implementation bug before any factor outcomes were observed. The code was corrected without changing the preregistered windows, universe, or gate. The table above is the first valid factor execution.

## Results

OOS consumed: **No**. OOS Sharpe/DSR/PBO are N/A.

## Multiple-Testing Audit

Previous trials 33; new trials 3; cumulative **36**.

## Decision

**REJECT**

## Provenance

Runner SHA256: `b3532cf8b530596fbf0154b3db33ee075a4b84d19d89da7cf95208bb7e09ea68`.
