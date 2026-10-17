# Seven independent native ML4T strategies: feature and 2020-2022 evaluation

Status: **EXPLORATORY**. This project is **not related to Shannon-20**.
No optimization, no pooled portfolio, no deployment approval, and no true
independent holdout results are implied.

## Source identity

User-uploaded independent Python variants:
`pivot-breakout-btc.py`, `donchian-btc.py`,
`three-red-spy.py`, `gold-macd-hook.py`, `slope-hook.py`,
`fx-timing.py`, `rsi-30-50.py`.

New separate source code:
- `src/strategies/independent_seven_native_features.py`
- `src/strategies/independent_seven_data.py`
- `scripts/run_independent_seven_2020_2022.py`
- `scripts/audit_independent_seven_2020_2022.py`
- `tests/test_independent_seven_native_features.py`

Native dependencies: `ml4t-engineer==0.1.4`, `ml4t-backtest==0.1.7`,
`polars==1.44.2`. Each source strategy is a distinct native broker run.
All indicator calculations go through the installed engineer feature
registry. Polars composes indicators into source-specific rules; the
native `Engine` performs cash, position, order, fill and fee accounting.
No hand-written returns simulator or replacement backtest engine.

## Frozen sample and market mapping

Only local `/home/quant/dev/quant/ml4t-data/.data/store` data.
Warmup: available 2019 history (BTC futures starts September 2019).
Evaluation: Jan 1, 2020 through Dec 31, 2022. No 2023+ data used.
All minute sources are reduced to daily *completed* session bars.
The timestamp column is a **session-date label**; it is not the true
wall-clock price availability. The engine evaluates completed daily
signals and submits orders for the next daily open.

| Strategy | Local market source | Difference from uploaded source |
|---|---|---|
| Pivot Breakout BTC | Binance BTCUSDT perpetual 1m, daily UTC | Yahoo BTC-USD replaced by perpetual; funding missing; broker STOP modeled |
| Donchian BTC | Binance BTCUSDT perpetual 1m, daily UTC | Same replacement; financing/funding missing |
| Three Red SPY | Dukascopy-derived ES minute source, NY 17:00 daily | ES CFD-style price proxy is **not** SPY with dividends |
| Gold MACD Hook | XAUUSD FX minute source, NY 17:00 daily | Gold CFD/FX proxy is **not** GLD ETF |
| Slope Hook | Dukascopy-derived ES minute source, NY 17:00 daily | Index CFD proxy, not tradable S&P contract |
| FX Timing | EURUSD forex + DXY index; ES exposure vs idle cash | **Major rule-proxy change** from FXE/UUP and SPY/BIL; no BIL yield |
| RSI 30/50 | Dukascopy-derived ES minute source, NY 17:00 daily | ES CFD-style price proxy instead of SPY |

Source bar minimum: BTC 1,300 minutes/day; non-BTC 500
minutes/session; DXY uses reported daily observations. These are
exploratory coverage filters, not independently calibrated data-quality
thresholds. The daily XAUUSD, BTC perpetual, and index/FX sources are
not interchangeable with ETF adjusted close data.

## Frozen native trading assumptions

Initial account: $100,000 for **each independent strategy**, never shared.
Binary rules target 95% capital while long. Donchian permits long/short
fractional exposure up to its native 2x volatility cap; broker native
margin uses initial margin 50%.

Commissions/slippage per side:
- BTC: 5 bps + 2 bps.
- ES-index CFD proxies: 2 bps + 2 bps.
- XAUUSD: 3 bps + 2 bps.

Costs are **assumptions**, not independently measured broker fees/spreads.
No actual BTC funding, borrowing, index CFD overnight carry, ETF dividend
or idle cash yield is modeled. Engine `ExecutionMode.NEXT_BAR`; the
original source same-close backtest is not reproduced. Broker-owned
market/STOP orders. Pivot protective STOP is installed after a completed
entry becomes observable; same-entry-day protection is not certified.
Gold maximum hold is ten active bars; the source's 5% protective stop
and ATR sizing were already absent from the supplied gold variant.

Native feature families:
- Pivot: Donchian high/low (7), SMA(50), SMA(10), 3-bar delayed pivot confirmation.
- Donchian: native rolling high/low on **close**, nine windows; StdDev60
  of returns; 25% volatility target, 2x maximum, 252 convention.
- Three Red: three close-below-open bars, green-bar exit.
- Gold: native MACD(12,26), EMA9 of MACD, WMA15 then SMA7 proxy;
  green-bar exit and ten-bar time cap.
- Slope: native Typical Price, 3-bar Linear Regression Slope, SMA5.
- FX Timing: native ROC20 for currency pair and USD index; Friday rule.
- RSI30/50: native RSI5 and SMA200; threshold-based entry/exit.

Native schema rejects negative synthetic close inputs for some indicator
dependencies. Intermediate derived MACD/return series are temporarily
shifted by a positive constant before a native EMA, standard deviation,
or slope call. They are shifted back when needed. Translation invariance
is mathematically justified but numerical parity with the uploaded
pandas formulas is **not yet certified**.

## Development run (2020-2022)

| Case | Native closed trades | Net return | Sharpe | Max DD |
|---|---:|---:|---:|---:|
| pivot-breakout-btc | 17 | +196.14% | 0.90 | -57.27% |
| donchian-btc | 479 | +94.37% | 0.90 | -18.03% |
| three-red-spy | 46 | +9.90% | 0.46 | -9.46% |
| gold-macd-hook | 26 | -4.11% | -0.17 | -9.71% |
| slope-hook | 43 | +23.96% | 0.71 | -7.77% |
| fx-timing | 21 | -26.45% | -0.54 | -30.58% |
| rsi-30-50 | 18 | +21.55% | 0.91 | -7.91% |

All 7 are **EXPLORATORY**, not qualified for paper or live trade.
Daily Donchian rebalancing creates many trade records; those records
are not independent signal episodes. A trade may be open at the end,
so the `len(trades.csv)` row count need not equal the engine's number
of completed trades.

### Evidence

`run_log/independent_seven_2020_2022/`:
- `execution.log`: raw native results.
- Each case has `summary.json`, `prices.parquet`, `signals.parquet`,
  `equity.csv`, `fills.csv`, `trades.csv`, `rejected_orders.csv`.
- `manifest.json`: source counts / covered intervals.
- `independent_audit.json`: all seven passed **artifact-integrity and
  native-ledger audit only** (consistent hashes, timeline, fills,
  final equity and zero rejected orders).
- `audit.log`: full verifier output.

### What is NOT established

- Exact source parity for original Yahoo ETF and BTC price datasets.
- Exact source indicator seeds, thresholds in source-specific libraries,
  execution close assumptions, FX rotations, BTC perpetual funding.
- Broker-specific costs and available margin/cash behavior.
- True untouched holdout, complete trial ledger or survival evidence.
- That a positive 2020-2022 Sharpe predicts future returns.

## Reproduction

```sh
uv run python -m pytest -q -o addopts='' tests/test_independent_seven_native_features.py
uv run python -m scripts.run_independent_seven_2020_2022 --case all
uv run python -m scripts.audit_independent_seven_2020_2022
```

## Recommendation

Of the independent exploratory proxies, prioritize **RSI 30/50** and
**Donchian BTC** for exact-source execution/parity audits. Slope Hook
is a second-tier candidate. Pivot has an unacceptable observed 57% DD
for most conservative sizing rules; examine intrabar protective-stop
timing before any further interpretation. Gold MACD loses and FX Timing
proxy loses; do not extrapolate FX proxy rejection to the original
FXE/UUP/BIL ETF strategy. No new strategy should be promoted yet.
