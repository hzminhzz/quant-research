# Gold / FX trend diversification — development-only intake

Date: 2026-10-15 (Asia/Bangkok). Status: **EXPLORATORY / NOT_APPROVED**.
Registered session: `gold_fx_trend_diversification_mvp_20261015`.

## Purpose

Study whether Gold and major FX price trends can add returns that differ from
the existing NQ/ES/BTC-dominated portfolio. This is one frozen 60-session
trend-sign family on three instruments, not an optimizer and not a claim that
three markets supply independent economic mechanisms.

**Economic hypothesis:** slow macro repricing and positioning can persist
over months. The null comparator is no-trade cash. Both Gold and currency
trends may be whipsawed during policy reversals or sideways conditions.

## Current data gate

Canonical read-only source: `/home/quant/dev/quant/ml4t-data/.data/store/`.
No files with raw timestamps on or after 2025-01-01 UTC were queried.
The canonical data repository was not modified.

Data snapshots: `data/processed/gold_fx_trend_diversification_20261015/`.
Each daily candle is labeled by the last available minute's close at
approximately **17:00 America/New_York**. Eligibility requires at least
600 observed quote minutes and no gap above 90 minutes inside that session.
Partial/unavailable days are **dropped, not filled**. These are
Dukascopy forex/Gold historical quote prices, not broker-executable
bid/ask spread or swap data.

| Source | Raw quote minutes (2013–2024) | Qualified daily bars | 2015–2021 | 2022 | 2023 | 2024 |
| --- | ---: | ---: | --- | ---: | ---: | ---: |
| XAUUSD | 3,890,218 | 2,721 | 241–244 per year | 224 | 185 | 155 |
| EURUSD | 4,481,187 | 3,106 | 257–260 per year | 260 | 259 | 260 |
| AUDUSD | 4,478,843 | 3,107 | 257–260 per year | 260 | 260 | 260 |

**Gold gap:** XAUUSD becomes materially incomplete from 2022 onward.
Do not imply that a backtest through 2024 has uninterrupted Gold daily prices.
The primary comparable study covers **2015–2021 only**. Price data from
2013–2014 supplies causal indicator warmup. The observed 2022–2024 history
is not an unseen holdout; it is excluded from the primary three-market
comparison due to Gold coverage. The separate **2025–2026 allocation
evaluation is locked**.

## Frozen research rule (no optimizer)

- One **native `ml4t.engineer` ROC60** per market on completed local daily
  closing quotes. No indicator is computed using future bars.
- At the completed close of the first eligible trading session each new
  calendar month, form the sign of the 60-session rate of change.
- Native `ml4t-backtest.Engine` NEXT_BAR order, filling at the *next*
  observed tradable bar open. No same-bar execution.
- Each instrument is tested in a standalone $100,000 book at 10% gross
  notional risk exposure; take the long or short sign. No leverage optimization.
- Development: 2015-01-01 through 2021-12-31. Ignore overlapping
  historical strategy claims as unseen validation.
- Explicit placeholder costs: 2 bps commission + 3 bps slippage **per side**.
  Exact broker spread, financing, overnight swap, instrument multiplier
  and margin requirements remain unverified and prevent any trading approval.
- Three baseline trials are preregistered and **not executed** at intake:
  `xau_tsmom_60_mvp`, `eur_tsmom_60_mvp`, `aud_tsmom_60_mvp`.
- Before any portfolio return comparison, audit each native fill, equity
  series, daily valuation clock, trade costs and holdout boundary. Compare
  synchronized daily returns at matched volatility to the unchanged
  incumbent portfolio only if individual evidence passes.

## Registration and verification

- Frozen YAML: `config/research_sessions/gold_fx_trend_diversification_mvp_20261015.yaml`.
- Frozen identity: `run_log/research_sessions/gold_fx_trend_diversification_mvp_20261015/frozen_spec.json`.
- Data source qualification: `scripts/qualify_gold_fx_daily_20261015.py`.
- Data report, yearly missing sessions, and snapshot SHA256:
  `data/processed/gold_fx_trend_diversification_20261015/data_qualification.json`.
- Native session CLI input audit returned **PASS** for all three
  qualified snapshot identities. `PASS` is a file-integrity result,
  **not a strategy result**. No PnL, Sharpe, or diversification evidence
  exists yet for this session.
- Existing unrelated dirty and staged work was preserved.
- The earlier Milkman archive was committed independently at
  `29efb1321dacff4c9486ea12cd240fa97553e66c`.

## Next bounded action

Run three fixed native ROC60 monthly strategy MVPs through the registered
research permit/attempt workflow, with close-to-next-open causal order tests
and separate terminal reports. If all fail the declared economic
falsifier, end research. Do not search parameters, open protected
evaluation data, train a new allocator or deploy.
