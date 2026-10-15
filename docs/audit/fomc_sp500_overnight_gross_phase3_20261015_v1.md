# Phase 3: FOMC overnight price-only event screen

**Decision: INCONCLUSIVE (signal-only; not backtest)**

**Reason:** Gross proxy result does not meet positive evidence or robust negative falsification.

- Retrospective events: **53**, in **7** years (2018–2024).
- Exact frozen entry/exit: 16:06 ET preceding statement day; 09:36 ET statement day.
- Baseline: exactly one D−7 matched ordinary overnight.
- All prices are Dukascopy bid-only minute BAR OPENS, not executed asks/bids.
- No spreads, fees, swaps, dividends, market impact, funding or live orders.
- This is a new exploratory adaptation. The original CFD BLOCKED_DATA decision remains intact.

## Prespecified gross price results

| Series | Mean (bps) | 95% HAC(2) CI (bps) | Positive events |
|---|---:|---:|---:|
| FOMC overnight | 17.758 | [0.488, 35.028] | 58.5% |
| Ordinary D-7 control | 14.451 | [-6.890, 35.792] | 56.6% |
| Matched increment | 3.307 | [-20.847, 27.461] | 50.9% |

## Annual attribution (gross bid price only)

| Year | Pairs | FOMC (bps) | Control (bps) | Paired (bps) |
|---|---:|---:|---:|---:|
| 2018 | 6 | 0.404 | 25.287 | -24.882 |
| 2019 | 8 | 4.391 | 14.080 | -9.688 |
| 2020 | 7 | 59.091 | 60.095 | -1.005 |
| 2021 | 8 | -21.098 | 20.539 | -41.636 |
| 2022 | 8 | 53.695 | 33.894 | 19.801 |
| 2023 | 8 | -1.467 | -33.236 | 31.769 |
| 2024 | 8 | 30.116 | -11.089 | 41.205 |

## Interpreting signal evidence

- Preregistered standard error: HAC(2). Paired t=0.275, two-sided p=0.7846.
- Lag-1 and lag-2 paired serial correlations: 0.13605307521664578, -0.0819675211085683.
- Average observed positive gross price-move budget per FOMC night: 17.758 bps (NOT a verified after-cost profit margin).
- Significant overlap with published pre-FOMC research through 2023; this does not satisfy independent holdout qualification.
- The matched ordinary overnight controls general index carry only approximately. It does not identify the causal risk counterpart or current Hyperliquid execution.

## Run identities

- Session spec SHA: `95105c5c3fb41577f25e6f48cbbcd6007511b3b136e47f745f8b5ce3234fda48`
- Input endpoint Parquet SHA: `56f356157d808057aecd03a65845ff8bd4047aa391429e6491593dbbf3977390`
- Historical 53-pair source-audit SHA: `a9c461e2e720be5ea0392a39d5a9975698b720ce9bf0c70c6bb7257aefbe7b68`
- Ledger: `run_log/diagnostics/fomc_sp500_overnight_gross_phase3_20261015_v1/event_pairs_gross_proxy.csv`
- Metrics: `run_log/diagnostics/fomc_sp500_overnight_gross_phase3_20261015_v1/metrics.json`

**Boundary:** This is a pre-backtest diagnostic, not native Engine cash/equity accounting. The user's actual perpetual venue has real trading costs and funding and its S&P 500 contract did not trade in 2018–2024. A Phase 3 PASS is not VALIDATE; a weak result is not fabricated as net PnL.
