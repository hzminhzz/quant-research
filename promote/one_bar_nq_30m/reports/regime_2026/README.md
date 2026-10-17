# 2026 outcome attribution for the fixed one-bar strategy

**Review type:** historical descriptive review. **Decision:** the package remains `EXPLORATORY` and `NOT_APPROVED`. No strategy rule changed. The backtest did not run again.

## Finding

The frozen 2026 ledger has 238 trades. It lost **$-14,166.96 net** with full-tick costs and **$-10,806.96 in the separate zero-cost run**. The loss is therefore present before costs. The full-tick result is $3,360.00 below the zero-cost result. The costed `gross_pnl` field is before commissions but already includes fill slippage; do not read it as zero-cost PnL.

The full-tick ledger charges $1,190.00 in commission and records $2,380.00 in slippage. Their simple sum is $3,570.00, which is $210.00 above the observed $3,360 scenario PnL gap. There are 238 matching entry-side pairs and 237 matching exit timestamps. The remaining difference is path-dependent and is not a pure slippage estimate.

The win rate was 47.5% with profit factor 0.806. Average winning trade was $522.36; average losing trade was $-585.54.

Native exit fills show 44 protective STOP exits and 194 scheduled MARKET exits. STOP exits lost $-48,058.76; MARKET exits gained $33,891.80. The market-exit trades were profitable as a group. The loss came from stop losses that outweighed those gains, plus monthly variation and modeled costs. All raw trade-ledger exit reasons say `signal`, so this split comes from native `fills.csv` order types. Source bars show 51 entry-path 1-minute OHLC touches of the nominal 50-point stop level. Intraminute order and stop gap behavior remain unresolved.

The entry-to-next-minute-open move, signed in the trade direction, had a $-0.48 mean and a 50.0% positive share. This immediate follow-through measure is descriptive only. The full-trade payoff remained negative.

## Monthly attribution

| Month | Trades | Full-tick net | Zero-cost net | STOP count / share | STOP net | MARKET net | 2018–25 same-month STOP share |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 36 | $-1,663.26 | $-1,158.26 | 7 (19.4%) | $-7,071.66 | $5,408.40 | 6/287 (2.1%) |
| 2 | 35 | $-2,359.70 | $-1,864.70 | 6 (17.1%) | $-6,060.00 | $3,700.30 | 11/266 (4.1%) |
| 3 | 38 | $-6,789.76 | $-6,269.76 | 10 (26.3%) | $-10,101.28 | $3,311.52 | 24/295 (8.1%) |
| 4 | 38 | $1,499.00 | $2,054.00 | 4 (10.5%) | $-7,313.06 | $8,812.06 | 14/282 (5.0%) |
| 5 | 42 | $4,065.84 | $4,680.84 | 3 (7.1%) | $-3,032.48 | $7,098.32 | 18/293 (6.1%) |
| 6 | 32 | $-9,195.46 | $-8,765.46 | 11 (34.4%) | $-11,450.28 | $2,254.82 | 12/282 (4.3%) |
| 7 | 17 | $276.38 | $516.38 | 3 (17.6%) | $-3,030.00 | $3,306.38 | 5/134 (3.7%) |

## Side, exits, hold time, and session

- **Side:** `long`: 137 trades, net $-2,259.70, win rate 50.4%.
- **Side:** `short`: 101 trades, net $-11,907.26, win rate 43.6%.
- **Exit:** `MARKET`: 194 trades, net $33,891.80, win rate 58.2%. The trade ledger writes `signal` for both stop and scheduled market exits. This table classifies from native fill order type.
- **Exit:** `STOP`: 44 trades, net $-48,058.76, win rate 0.0%. The trade ledger writes `signal` for both stop and scheduled market exits. This table classifies from native fill order type.
- **Session:** `RTH`: 61 trades, net $-1,762.74, win rate 44.3%.
- **Session:** `overnight`: 177 trades, net $-12,404.22, win rate 48.6%.
- Holding time: median 15 source minutes; mean 15.7 source minutes. Full distribution is grouped by `bars_held` in `metrics.json`.
- Cash-flow drawdown: {'exit_date_chicago': datetime.date(2026, 7, 6), 'pnl': -356.5400000000227, 'equity': -15013.199999999124, 'peak': 1594.780000000028, 'drawdown': -16607.979999999152}.
- Best/worst trade concentration: worst 10 sum $-13,718.76; best 10 sum $21,191.72.

## Prior same-season comparison

The matched Jan 1–Jul 14 slices from 2018–2025 contain 1,839 trades and net $108,799.82. The average was $59.16 per trade. Annual summaries are in `metrics.json`. The 2026 outcome differs from the earlier same-season aggregate, but the comparison does not control for every execution or market structure change.

Matched prior seasons averaged about 230 trades per partial year. The 2026 count of 238 was similar. The main difference was realized payoff: 2026 net per trade was -$59.53 versus +$59.16 for the 2018–2025 matched sample.

## Fixed 50-point stop and pre-entry ATR

The unchanged 50-point stop represents $1,000 per illustrative contract at $20 per point. The full-year 2018 median entry price was 6,966.5; 50 points equaled 71.8 bp of price. In 2026, median entry price was 25,828.5; the same stop equaled 19.4 bp. For matched Jan–Jul 14 trades, pre-entry ATR(20) medians were 27.9 points for 2018–2025 and 66.7 for 2026.

The table below compares native STOP probability across terciles of 50 / pre-entry ATR(20), using 2018–2025 matched-season cutpoints. This is a descriptive diagnostic. It does not select or change a stop threshold. The 2026 sample has no trades in the high-ratio tercile.

| Period | 50 / ATR(20) tercile | Trades | Median ratio | STOP probability | Net PnL |
|---|---|---:|---:|---:|---:|
| reference_2018_2025 | high_50pt_atr_ratio | 613 | 3.45 | 1.0% | $18,236.90 |
| reference_2018_2025 | low_50pt_atr_ratio | 614 | 1.00 | 8.3% | $64,980.94 |
| reference_2018_2025 | mid_50pt_atr_ratio | 612 | 1.79 | 5.4% | $25,581.98 |
| 2026 | low_50pt_atr_ratio | 224 | 0.74 | 17.9% | $-16,301.02 |
| 2026 | mid_50pt_atr_ratio | 14 | 1.55 | 28.6% | $2,134.06 |

## Pre-entry regime diagnostics

Each 30-minute feature is released at the next 30-minute open. The as-of backward join only accepts `feature_available_at <= entry_time`. ATR(20) comes from `ml4t.engineer.compute_features`; the 20-bar efficiency ratio, prior range / ATR, and 50-bar channel width use sorted Polars expressions. Regime cutpoints are the 2018–2025 matched-season terciles. They describe slices. They are not proposed trading filters.

`entry_context.csv` contains `volatility_proxy`. A complete 2026 time join succeeded. The source code records that field as the channel `range_proxy`; this report does not call it realized volatility. ATR and channel width offer separate measures.

| Feature | Period | Regime | Trades | Net PnL | Win rate |
|---|---|---|---:|---:|---:|
| atr20_bps | 2026 | high | 79 | $-10,191.54 | 46.8% |
| atr20_bps | 2026 | low | 47 | $4,908.00 | 44.7% |
| atr20_bps | 2026 | mid | 112 | $-8,883.42 | 49.1% |
| atr20_bps | reference_2018_2025 | high | 613 | $38,239.08 | 51.5% |
| atr20_bps | reference_2018_2025 | low | 614 | $28,892.66 | 52.3% |
| atr20_bps | reference_2018_2025 | mid | 612 | $41,668.08 | 52.5% |
| efficiency_20 | 2026 | high | 81 | $-7,416.68 | 45.7% |
| efficiency_20 | 2026 | low | 79 | $-2,132.82 | 51.9% |
| efficiency_20 | 2026 | mid | 78 | $-4,617.46 | 44.9% |
| efficiency_20 | reference_2018_2025 | high | 613 | $33,452.96 | 52.5% |
| efficiency_20 | reference_2018_2025 | low | 614 | $43,939.48 | 52.0% |
| efficiency_20 | reference_2018_2025 | mid | 612 | $31,407.38 | 51.8% |

The KS and PSI results in `metrics.json` compare feature distributions. They are drift diagnostics, not tests that the features caused the PnL change. Daily proxy trend and realized volatility are shown in the chart.

## Source and macro context

The source is Dukascopy USATECH.IDX/USD BID one-minute data, an index/CFD proxy. It is not a dated CME NQ contract. The source manifest ends on 2026-07-14. The source-feature calculation excludes later observations.

The chart reports daily trend and realized volatility for the same local index proxy. These features do not represent a separate official Nasdaq index or a causal macro variable. Monthly values are in `metrics.json`.

For context only, March coincided with geopolitical shocks, April and May with a broad market rebound, and June with technology leadership rotation. These are hypotheses about the surrounding period, not identified causes of trade PnL. The market-proxy monthly returns and trade PnL do not establish a causal link.

Cboe described January 2026 as broadening beyond mega-cap technology, with Russell 2000 up 5.31% and MGTN down 0.8% ([Cboe](https://www.cboe.com/insights/posts/index-insights-january-2026/)). Cboe described June leadership rotation, with Russell 2000 up 3.6%, MGTN down 9.2%, and VIX rising from 15.3 to 16.5 ([Cboe](https://www.cboe.com/insights/posts/index-insights-june-2026/)). Nasdaq's official scorecard search results report NDX down 2.3% in February, up 15.6% in April, and up 10.5% in May ([February](https://www.nasdaq.com/articles/global-indexes/index-monthly-scorecard-february-2026), [April](https://www.nasdaq.com/articles/global-indexes/monthly-scorecard-april-2026), [May](https://www.nasdaq.com/articles/global-indexes/monthly-scorecard-may-2026)). Nasdaq page retrieval was blocked, so this report uses only those monthly return values and does not repeat driver claims from the pages. Strategy PnL was positive in April and May and negative in March and June. These public summaries do not match individual trade entry times. Any event/month link to PnL is a hypothesis only.

## Confidence and limits

- **Verified:** ledger identities, counts, PnL, modeled costs, monthly and conditional sums, entry-side/exit categories, entry timestamps, source cutoff, and matched same-season sample.
- **Inference:** the fixed 50-point stop was smaller relative to 2026 ATR(20) and price than in earlier observations. Higher stop incidence is consistent with that change. This does not establish causality.
- **Hypothesis:** monthly macro narratives may coincide with trade outcomes. Broad index returns do not explain intraday proxy PnL without event-time matching.
- One-minute OHLC touches include the entry and exit minute. The data cannot determine event order inside those minutes. There were 51 nominal 50-point touches and 44 native STOP exits. Stop gaps can exceed nominal risk. The engine's OCO is non-atomic. Annual runs reset account state. The run does not verify CME contract mapping, bid/ask execution, or certified costs.
- No day-cluster confidence intervals were computed. The historical trial ledger is incomplete for Deflated Sharpe Ratio. The report does not use MFE or MAE as pre-entry features.

## Reproduction

```bash
UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp/mplconfig XDG_CACHE_HOME=/tmp/cache uv run python promote/one_bar_nq_30m/scripts/analyze_regime_2026.py
UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp/mplconfig XDG_CACHE_HOME=/tmp/cache uv run python -m pytest promote/one_bar_nq_30m/tests/test_regime_2026.py
```

See `analysis_manifest.json` for frozen groups and feature definitions. The frozen reports, original run folders, and the post-2026-07-14 holdout were not changed or read.
