# Five independent strategies: full available local-history evaluation

**Date:** 2026-10-14. **Status:** EXPLORATORY, **NOT APPROVED**.
**Scope:** only the five independent strategies selected because 2020–2022
Sharpe was positive. These strategies are NOT Shannon components.
Frozen experiment and incremental post-baseline cost-stress plan:
`docs/plans/independent_five_full_history_20261014.md`.

## Source and execution

- BTC: `ml4t-data/.data/store/crypto_futures_minute_BTCUSDT_PERP`.
  Daily UTC completed bars. 2019-09-09 to 2026-10-11, 2,590 sessions.
- S&P proxy: `ml4t-data/.data/store/index_minute_ES`.
  Daily New York 17:00 session-ending CFD/index price proxy.
  2011-09-19 to 2026-10-09, 3,899 sessions.
- All raw timestamps on or after **2026-10-12 00:00 UTC** are excluded
  BEFORE data aggregation. This preserves the protected 2026-10-12+
  repository holdout boundary. Only completed eligible sessions are scored.
- Native `ml4t.engineer.compute_features` indicators and native
  `ml4t.backtest.Engine` for each of five strategies independently.
  No hand-rolled PnL engine, no model optimization, and no new instrument
  discovery after observing returns.
- $100,000 capital **per independent strategy**, not pooled.
  Native `ExecutionMode.NEXT_BAR`; broker commissions + slippage
  baseline: BTC 5+2 bps/side; ES proxy 2+2 bps/side.
  Two and three times BOTH components tested afterwards.
- BTC funding, leverage financing and broker liquidation mechanics
  not independently calibrated. ES proxy is NOT SPY ETF, and lacks
  SPY distributions/borrow/funding equivalence. Generic fees are research
  costs, not verified trade execution.
- Full-history Sharpe is reported as emitted by installed native
  `ml4t-backtest==0.1.7`; period Sharpe computed from native equity
  returns with ML4T analytics `sharpe_ratio` (252 convention).
  Treat BTC calendar annualization as not qualified.

## Full-history native backtest

| Strategy | Period | Native closed trades | Net cumulative return | Sharpe | Maximum equity DD |
|---|---|---:|---:|---:|---:|
| Pivot Breakout BTC | 2019-09 to 2026-10 | 48 | +306.41% | 0.62 | -59.63% |
| Donchian BTC | 2019-09 to 2026-10 | 1,102 | +208.18% | 0.68 | -25.07% |
| Three Red Days (ES proxy) | 2011-09 to 2026-10 | 187 | +6.05% | 0.09 | -30.45% |
| Slope Hook (ES proxy) | 2011-09 to 2026-10 | 187 | +17.66% | 0.18 | -26.37% |
| RSI 30/50 (ES proxy) | 2011-09 to 2026-10 | 101 | +101.55% | 0.78 | -10.48% |

For Donchian, native position rebalancing produces many trade records,
not 1,102 statistically independent full strategy episodes.

## Chronological behavior

| Strategy | Pre-2020 return | 2020–2022 return | 2023–2025 return | 2023–2025 Sharpe | 2026 YTD return |
|---|---:|---:|---:|---:|---:|
| Pivot Breakout BTC | 0.00% (early warmup) | +196.14% | +37.86% | 0.42 | -0.45% |
| Donchian BTC | +1.58% (short 2019 history) | +94.41% | +40.73% | 0.51 | +12.25% |
| Three Red Days | -16.19% | +9.90% | +6.61% | 0.62 | +7.85% |
| Slope Hook | -15.75% | +23.96% | +6.38% | 0.42 | +5.90% |
| RSI 30/50 | +40.20% | +21.55% | +13.76% | 0.78 | +3.97% |

Period return is measured using the FIRST equity mark inside that
segment and the LAST equity mark inside that segment, so it may differ
slightly from a calendar-year close-to-previous-year-close calculation.
Segment metrics do not restart broker capital or reoptimize weights.

Annual net equity returns are also retained in each case's
`summary.json` under `segments`; 2026 is partial to Oct 9/11.

### Post-baseline 2x/3x execution cost stress

| Strategy | Base return | 2x costs | 3x costs | 3x Sharpe | 3x Max DD |
|---|---:|---:|---:|---:|---:|
| Pivot Breakout BTC | +306.41% | +281.43% | +257.95% | 0.57 | -61.26% |
| Donchian BTC | +208.18% | +190.94% | +174.66% | 0.62 | -26.71% |
| Three Red Days | +6.05% | -8.00% | -20.20% | -0.22 | -35.91% |
| Slope Hook | +17.66% | +2.06% | -11.47% | -0.07 | -35.01% |
| RSI 30/50 | +101.55% | +86.69% | +72.92% | 0.62 | -12.24% |

This cost stress was preregistered AFTER observing full-history
baseline returns; it is a separate exploratory robustness check,
not confirmation on an untouched dataset.

## Verification and source artifacts

Root: `run_log/independent_five_full_history_20261014/`.

- `execution.log`, `exit_code.txt` (0), `manifest.json`,
  `data_manifest.json`.
- One folder per strategy contains `summary.json`,
  `prices.parquet`, `signals.parquet`, `equity.csv`, `trades.csv`,
  `fills.csv`, `rejected_orders.csv`, artifact hashes.
- `audit.json`, `audit.log`: **PASS for all 5**. Verified price and
  signal hashes, no protected timestamps, session counts, native
  fills, trade records, no rejected orders, and native final equity.
- `cost_stress_2x_3x.json`, `stress.log`: 10 native stress trials
  at frozen 2x/3x fees. No missing or discarded trial.

Source:
`scripts/run_independent_five_full_history_20261014.py`,
`scripts/audit_independent_five_full_history_20261014.py`,
`scripts/stress_independent_five_full_history_20261014.py`.
Earlier rule and data code remains separate:
`src/strategies/independent_seven_native_features.py`,
`src/strategies/independent_seven_data.py`.

```sh
uv run python -m scripts.run_independent_five_full_history_20261014
uv run python -m scripts.audit_independent_five_full_history_20261014
uv run python -m scripts.stress_independent_five_full_history_20261014
```

Focused native-feature tests were already passing before this
extension (8 passed, 3 dependency warnings). Historical global
repository suite had 13 unrelated failures due to missing old
research partitions/artifacts; do not misreport as fully green.

## Decision

**Advance to next provenance/execution audit, not production**:
- **Priority 1: RSI 30/50.** Full history positive, +40.20% pre-2020,
  +13.76% 2023–2025, +72.92% net with 3x assumed friction, max DD
  around 10–12%. Needs actual ETF SPY/adjustment and dividends
  for rule/source parity, and unbiased execution costs.
- **Priority 2: Donchian BTC.** Positive across the main eras, still
  +174.66% at 3x assumed friction, but short/long derivatives economics
  missing funding/financing; 1,102 trade records include resizing.
- **Watch only: Pivot BTC.** Large profits depend on a 59–61% DD,
  and intrabar protective stop activation is not certified.
- **Do not advance: Three Red and Slope Hook.** Pre-2020 negative
  and 3x-cost results negative, with low whole-period Sharpe.

This is **NOT** a fresh OOS promotion. The five were selected because
the 2020–2022 development sample was positive. Related research has
already exposed subsequent periods. The multiple-testing record of
source-author iterations is unknown. Independent confirmation still
requires genuinely new future data and exact instrument parity.
