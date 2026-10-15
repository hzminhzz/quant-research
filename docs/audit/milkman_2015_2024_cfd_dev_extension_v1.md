# Milkman four-candidate index-CFD extension (2015–2024)

**Date:** 2026-10-14. **Research status:** EXPLORATORY / NOT_APPROVED.
**Decision:** Do not promote, deploy, or add to the incumbent portfolio.

## Outcome

Executed **40 pre-registered case-year attempts** across four unrejected
Milkman strategies. **38** were re-executed and independently reconciled.
The other **two are BLOCKED_DATA** because historical full overnight
Globex sessions are unavailable in 2016 and 2017.

All runs used the installed native `ml4t-backtest.Engine`, registered
`ml4t-engineer.compute_features` indicators, broker fills and position/equity
accounting. **No stock, CME futures or options-return replication is claimed.**

| CFD price-rule adaptation | Eligible annual books | Closed trades | Positive / negative / zero years | Mean annual net return |
| --- | ---: | ---: | --- | ---: |
| Legend's Buy Day, ES CFD | 8/10 | 89 | 4 / 4 / 0 | +0.0301% |
| Legend's EMA, NQ CFD | 10/10 | 134 | 5 / 4 / 1 | +0.0663% |
| Bilbo Box v2, NQ CFD underlying only | 10/10 | 121 | 4 / 6 / 0 | +0.1216% |
| Swing Golden Gate, ES CFD | 10/10 | 19 | 6 / 3 / 1 | +0.0724% |

**These are NOT continuous ten-year CAGR, compounded NAV or annualized
portfolio Sharpe values.** Each calendar-year trial starts a NEW $100,000
native broker account, holds approximately 10% index-CFD price exposure,
and uses nominal 2 bps commission plus 2 bps slippage **per side**.
The average of annual account returns is displayed, not summed/compounded.
The spread, financing, actual CFD contract/currency mapping and market impact
were not calibrated. The available returns are too small and inconsistent to
justify an independent portfolio-diversification allocation.

## Every registered development year

Each value is net return followed by closed trade count. The status
`BLOCKED` means a data failure, NOT a zero-return backtest.

| Year | Legend's Buy Day | Legend's EMA | Bilbo Box v2 | Swing Golden Gate |
| --- | --- | --- | --- | --- |
| 2015 | -0.138% (4) | 0.000% (0) | +0.557% (8) | +0.301% (3) |
| 2016 | BLOCKED_DATA | -0.060% (11) | -0.040% (10) | -0.257% (2) |
| 2017 | BLOCKED_DATA | +0.022% (19) | +0.583% (13) | 0.000% (0) |
| 2018 | +0.060% (10) | +0.268% (22) | -0.154% (11) | +0.100% (2) |
| 2019 | -0.191% (5) | -0.000% (12) | -0.077% (16) | +0.200% (2) |
| 2020 | +0.718% (10) | -0.032% (8) | +0.317% (19) | +0.172% (1) |
| 2021 | +0.202% (12) | +0.172% (15) | +1.170% (10) | +0.128% (1) |
| 2022 | -0.383% (23) | -0.274% (16) | -0.345% (5) | +1.073% (4) |
| 2023 | -0.236% (12) | +0.113% (12) | -0.572% (17) | -0.265% (1) |
| 2024 | +0.209% (13) | +0.454% (19) | -0.224% (12) | -0.728% (3) |

For Legend's Buy Day, 2022 Q1 appeared positive in the earlier MVP.
The complete independent **2022 calendar year** was negative, -0.383%.
This is observed development history, not an unseen performance test.

## Data qualification and registered correction

Original immutable program and code:

- `config/milkman_2015_2024_cfd_dev_extension_v1.yaml`
- `config/milkman_source_to_cfd_features_20261014.yaml`
- `scripts/run_milkman_extended_2015_2024.py`
- Original first 40 attempts: `run_log/milkman_cfd_2015_2024_dev_extension_v1_retry1/`.
  All six data-gate failures remain recorded as `failed.json`.

The original eligibility screen applied an unqualified 220,000
minute-per-year threshold to every strategy. This was too broad.
Independent *data-only* inspection found:

| Source year | Raw ES minute rows | Complete full-Globex days | Complete RTH 15m sessions on NQ | Complete selected ETH hourly bars on NQ |
| --- | ---: | ---: | ---: | ---: |
| 2016 | 215,643 | 0 | 251 | 3,072 |
| 2017 | 213,862 | 0 | 249 | 3,055 |

The corrections were frozen **before** the four corrected PnLs were
observed in `config/milkman_2015_2024_extension_data_gate_amendment1.yaml`.

- **Legend's Buy Day:** 2016 and 2017 remain BLOCKED_DATA. No genuine
  Globex session closes could be constructed. Lowering a raw row threshold
  would invent the required overnight information.
- **Legend's EMA:** RTH 26-bar sessions exist. Its 2016 and 2017 trials were
  rerun using the same frozen previous-252-session 80th-percentile threshold.
- **Bilbo Box v2:** usable 04:00–20:00 ET-filtered hourly CFD bars exist.
  Its 2016 and 2017 trials were rerun without assuming missing hours.
  Signals can be studied; full extended-hours stock/options parity remains
  unavailable.

Correction files:
`run_log/milkman_cfd_2015_2024_data_gate_correction_v1/`.
None of the source parquet files or earlier research trials were changed.
The original and corrected trial records remain distinct.

## Economic interpretations and limitations

1. **Legend's Buy Day** — 89 valid CFD trades, 4/8 positive years,
   +0.0301% average annual account return. No robust evidence that this
   overnight setup is profitable after real broker costs.
2. **Legend's EMA** — 134 trades over ten calendar years, but just 5/10
   profitable years. The causal rolling percentile changes the author's
   full-sample lookahead-prone threshold. This is an adaptation, not the
   author's published result.
3. **Bilbo Box v2** — 121 *underlying CFD* trades, 4/10 positive years
   and a negative return in each of 2022–2024. Source options payoff
   remains unobservable without historical options NBBO/expiry/selection.
   Its nominal positive multi-year average is insufficient to claim edge.
4. **Swing Golden Gate** — only 19 closes across ten years, sharply negative
   in 2023 and 2024. The monthly-level short mechanism is sensitive
   to gaps, fills and financing; the low sample count blocks inference.

**Source-equivalence warning:** all four trade different CFD price proxies
instead of the author's CME futures, listed stocks, or options. The
uncalibrated 4bps/side combined costs and reset capital books do not support
actual trading or portfolio allocation. No selection or optimization was
conducted after observing yearly outcomes.

## Verification and evidence

- Machine-readable full 40-cell audit:
  `docs/audit/milkman_2015_2024_cfd_dev_extension_v1.json`.
- Native artifacts per case/year: `prices.parquet`, `signals.parquet`,
  `fills.csv`, `trades.csv`, `equity.csv`, `rejected_orders.csv`,
  `attempt.json` and `report.json`, or `failed.json`.
- Each completed year was verified by an independent auditor for immutable
  input hashes, unique data clocks, zero accessed 2025+ input events,
  native trade PnL versus final equity (within $0.02), broker fill counts
  and native daily marked-equity Sharpe.
- The two intended 2016–2017 Buy Day failures remain explicit, not counted
  as profitable or zero-return years.
- Dedicated calendar tests cover EST and EDT 26-bar RTH construction;
  15 combined feature, engine and extension tests passed during this work.
- Final protected allocation 2025–2026 was never opened or accessed.
- No existing portfolio sleeve, promotion file, deployment or active
  strategy status was modified.

## Research disposition

**Four candidates have terminal findings for this frozen CFD
development-extension trial.** None meets an independent portfolio
diversification qualification gate. Two *data cells* remain
`BLOCKED_DATA` and are not described as passes. No new parameter
search or ML4T-models allocator is authorized.
