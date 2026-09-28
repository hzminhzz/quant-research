# Crypto Research Run — Abnormal-Day Intraday Momentum

## Conclusion

**REJECT.** The source-inspired dynamic-trigger strategy passed its pre-registered 2021–2023 development gate, but failed untouched 2024–2025 OOS. Canonical k=2 net OOS Sharpe was 0.083 with -20.4% total return and -60.0% max drawdown after 3 bps one-way costs.

## Source

Caporale & Plastun (2020), *Momentum effects in the cryptocurrency market after one-day abnormal returns*, Financial Markets and Portfolio Management, DOI 10.1007/s11408-020-00357-1.

## Pre-Registered Specification

Dynamic abnormal-day trigger using the prior 60 completed UTC days; k=1.5 / **2.0 canonical** / 2.5; enter next hourly open after first same-day threshold crossing and exit at next UTC day open; causal top-80% trailing-dollar-volume universe; equal weight active signals.

## Development

| k | Net Sharpe | Net return | Triggered asset-days |
|---:|---:|---:|---:|
| 1.5 | 0.455 | -11.7% | 2,712 |
| **2.0** | **0.803** | **+302.8%** | **1,343** |
| 2.5 | 0.868 | +586.3% | 758 |

The canonical rule passed the fixed development gate.

## Untouched OOS

Canonical k=2, 2024–2025:
- Net Sharpe: **0.083**
- Total return: **-20.4%**
- Max drawdown: **-60.0%**
- 2x-cost Sharpe: -0.135
- 3x-cost Sharpe: -0.354
- 2024 Sharpe: 0.285
- 2025 Sharpe: -0.148

Neighbor base-cost Sharpes: k=1.5 = -1.053; k=2.5 = 0.625.

## Robustness

- Excluding BTC/ETH: Sharpe -0.038
- One extra hour entry delay: Sharpe -0.131
- Removing strongest contributor SUI: Sharpe -0.255

## Multiple-Testing Audit

Current-family DSR probability 0.191; haircut Sharpe -0.513. Previous trials 39; new 3; cumulative **42**. PBO N/A for the three-threshold preregistered family.

## Decision

**REJECT**

## Provenance

Runner SHA256: `e7c031badb4188b8028f3d8db0577f989aa783c609bc31782277b8d36838b918`.
