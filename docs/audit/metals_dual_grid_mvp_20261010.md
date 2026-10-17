# Lighter XAU/XAG dual-grid A/B — 2026-10-10

**Status: EXPLORATORY. Not approved for live trading.**

## Decision

Arm A had the higher preregistered completed-maker-volume-per-drawdown
metric. Arm B scored 1,804.8833. Arm A scored 1,869.0041. B scored
64.1208 lower, or 3.43% below A.

This result does not support either arm for deployment. Both arms breached the
$200 drawdown stop. Both lost about $200 from $600 initial capital. The result
is a volume-screening outcome, not evidence of profitable trading. Do not
select A for live use from this comparison.

## Frozen study and data

- Session: `metals_dual_grid_mvp_20261010`.
- Classification: `EXPLORATORY`; approval: `NOT_APPROVED`.
- Frozen config: `config/research_sessions/metals_dual_grid_mvp_20261010.yaml`.
- Config SHA-256: `1c5d042291eecfb290258b2c12741f2cda5074face1481a29c9ec3834a7cadf5`.
- Frozen spec SHA-256: `d4790a520bb6de18ddebfbc89dddb50fdbd43b42f24e4bb3751634fa337beb95`.
- Frozen runner SHA-256: `e3ae23aa8b9b7d19666592c1d305d5bdccb94a4116f2ad3fb244f295b6b88599`.
- Source: saved Lighter CCXT XAU/USDC:USDC and XAG/USDC:USDC OHLCV.
- Source partitions: 20 monthly Parquet files. The frozen spec records each
  partition SHA-256 and byte size.
- Paired 2-minute artifact: 373,898 rows from 2026-01-22 16:00 UTC through
  2026-10-09 07:36 UTC. It has 165,348 beta-ready timestamps.
- Artifact: `data/features/metals_dual_grid_mvp_20261010/paired_2m_beta.parquet`.
- Artifact SHA-256: `7b9746d0c11933309f227586029c26494a62bc839c9d61ec1bb11667deefb7e9`.
- Beta first became available at 2026-02-21 16:02 UTC. Each value uses only
  prior 2-minute returns from the 30-day window.
- The later part of this sample was inspected in earlier Lighter grid work.
  This is not a pristine holdout.

## Variants and execution

- A: fixed 25 bps entry spacing for both grid legs.
- B: fixed XAU spacing and XAG spacing of 25 bps times the lagged 30-day
  XAG-on-XAU return beta, clamped to [0.1, 3.0].
- Both arms use 20 levels per leg, $100 per level, separate fixed anchors,
  per-lot maker exits at entry price, and rearm at the original fill price.
- The simulation uses `ml4t.backtest.Engine`, native resting LIMIT orders,
  `NEXT_BAR` execution, 100% of reported bar volume as the participation cap,
  and no partial fills.
- Maker fees are 0 bps. Emergency market exits use 2.25 bps taker fee plus
  2.0 bps slippage. Funding is excluded because historical funding was
  unavailable for these saved Lighter OHLCV partitions.
- Historical OHLCV touch fills do not establish queue position or passive fill
  probability. The participation cap does not solve this limitation.

## Beta diagnostic

The lagged beta ranged from 1.2267 to 1.8598. Its median was 1.4911.
The five beta buckets had non-monotonic 30-minute forward residual means.
This is a descriptive stability check. It does not establish predictive alpha
or justify beta tuning.

## Full-sample A/B results

| Metric | A: fixed spacing | B: beta-adjusted XAG |
|---|---:|---:|
| Completed maker volume / max drawdown | 1,869.0041 | 1,804.8833 |
| Maker fill notional (USDC) | 381,149.2924 | 364,633.5208 |
| Completed maker volume (USDC) | 380,052.9251 | 363,537.1535 |
| Completed grid cycles | 1,908 | 1,825 |
| Net mark-to-market P&L (USDC) | -199.5002 | -195.5086 |
| Maximum drawdown (USDC) | 203.3452 | 201.4186 |
| Maximum gross plus reserved (USDC) | 4,146.5191 | 4,136.7999 |
| Emergency taker notional (USDC) | 897.2484 | 901.2417 |
| Ending unfinished inventory (USDC) | 0.0000 | 0.0000 |
| Risk stop triggered | Yes, bar 21,340 | Yes, bar 21,339 |
| Unfilled emergency orders | 0 | 0 |

Both arms stopped near the same point, about 21,340 bars after beta became
available. The $200 drawdown limit was exceeded by $3.35 for A and $1.42 for
B. The engine applies the risk check after bar processing. The observed stop is
therefore a bar-level stop, not a hard intrabar loss cap. Maximum gross exposure
stayed below the $6,000 cap.

The result artifact does not include the configured emergency-exit-cost field.
The configured rate is 4.25 bps. Applying that rate to the reported emergency
notional gives $0.3813 for A and $0.3830 for B, rounded to four decimals. The
runner subtracts emergency cost from reported net P&L. The costs above are
calculated from the recorded notional and frozen rate; they are not separate
raw engine fields.

## Research limitations and next decision

- Both arms fail the preregistered $200 drawdown condition and have negative
  net P&L. The A/B winner on turnover efficiency does not override these
  failures.
- The simulation measures completed maker turnover under a candle-touch
  proxy. It does not validate exchange maker fills, queue position, funding,
  or deployment economics.
- The historical window is previously inspected. Do not use it for another
  parameter search or call it out-of-sample evidence.
- No DSR or PBO estimate is reported. The comparison has two preregistered
  arms, but the complete related-trial history is not available here. A
  selection-aware adjustment would not be reproducible.
- Two full-sample commands with a 1,200-second timeout ended without writing
  results. Profiling found that inactive order metadata accumulated in the
  strategy risk scan; the runner now removes inactive orders. The final
  command completed in 2,221.57 seconds with a 3,600-second timeout. The
  timeout attempts produced no performance outcomes and are not extra strategy
  trials.
- The full result is in
  `run_log/research_sessions/metals_dual_grid_mvp_20261010/phase4_ab_result.json`.
  Phase 2 and Phase 3 evidence is in the same run directory.
