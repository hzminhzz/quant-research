# Lighter SPY/QQQ grid comparison — 2026-10-09

Status: **EXPLORATORY — NOT APPROVED FOR LIVE DEPLOYMENT**.

## Decision

The hypothesis that two independent opposing DCA grids hedge a persistent market
trend is **not supported** by this particular historical test. A coordinated
SPY–QQQ spread grid lowered historical maximum drawdown but failed to retain a
positive return after placeholder execution costs.

This is a *price-path risk experiment*, not a verified Arcus maker or Lighter
order-book backtest. Do not infer maker fills or a profitable live strategy.

## Data provenance and validation

- Provider: Lighter public candles via installed CCXT 4.5.85.
- Instruments: `SPY/USDC:USDC` (market 128) and `QQQ/USDC:USDC` (market 129).
- Requested: one year back from 2026-10-09. Actual endpoint history starts
  2026-01-22 16:00 UTC for both instruments, and ends 2026-10-09 07:38 UTC.
  Older sampled requests returned no candles. Do not claim 365 days.
- Both: 373,899 one-minute bars, contiguous UTC opens, zero missing minutes after
  the first observed bar; 747,798 combined rows.
- Twenty monthly zstd Parquet partitions; sidecar SHA-256 hashes all verified.
- Zero reported volume: SPY 31.01%, QQQ 43.80% of minutes. Those candles do not
  change close relative to the previous minute.
- Canonical path: `/home/quant/dev/quant/ml4t-data/.data/store/crypto_futures_ohlcv_1m_LIGHTER_USDC_PERP/`.
- Acquisition script: `ml4t-data/scripts/fetch_lighter_rwa_1m.py`.
- Source windows are paginated in **<=500 bars**: Lighter silently returns the
  *last* 500 of an oversized CCXT-requested interval.

## Frozen comparison design

Session config: `config/research_sessions/lighter_spy_qqq_pair_grid_20261009.yaml`.

- Calibration: observed history through 2026-02-21; frozen OLS hourly-return
  SPY-on-QQQ beta **0.2976247240**; calibration correlation **0.5462**.
- Development: 2026-02-22 through 2026-07-31 inclusive.
- Chronological OOS: 2026-08-01 through 2026-10-09 07:38 UTC.
- All use `ml4t.backtest.Engine` and one-minute bars.
- Long-only SPY grid: three $200 entry levels.
- Independent SPY-long / QQQ-short grids: three $100 entry levels **per leg**.
- Coordinated pair grid: three $200 gross levels allocated using the frozen beta,
  entering on 7-day rolling spread z-scores at 1.5, 2.0, and 2.5; exit near
  the mean, at a 3.5 z-score stop, or after 7 days.
- Individual grid TP 0.2%; add spacing 0.5%; minimum 10-minute add interval.
- Nominal starting inventory budget $600; $1,000 initial account cash; $50
  peak-to-trough strategy drawdown halt. Marked gross exposure can **exceed**
  $600 as prices move (observed up to $669), so $600 is **not a continuously
  enforced hard risk cap**. Explicit enforcement is required before any deployment.
- Uses prior-minute signals, subsequent-minute market fills, and positive-volume
  *signal* candles. Real exchange volume or quote availability at the *fill*
  instant is not proven. The simulation is **not** a passive-grid fill model.
- Base costs: 2 bps commission + 2 bps slippage per fill, **assumptions**, not
  validated Lighter/Arcus fees or execution spreads.
- Funding, spread/impact beyond configured assumptions, liquidation rules,
  off-hours Arcus–Lighter basis, mark/reference changes, and reward points are
  not modeled. Remaining end-of-window positions are marked to market, not
  liquidated.

## Base (4 bps per fill) results

| Phase | Variant | Net USD | Fills | Max drawdown | Strategy halted |
|---|---|---:|---:|---:|---|
| Development | SPY solo | -45.38 | 26 | 5.03% | Yes |
| Development | Independent dual grids | -44.86 | 428 | 4.99% | Yes |
| Development | Coordinated pair grid | -20.87 | 790 | 3.37% | No |
| OOS | SPY solo | +12.63 | 92 | 1.76% | No |
| OOS | Independent dual grids | -22.34 | 103 | 2.70% | No |
| OOS | Coordinated pair grid | -10.17 | 206 | 1.35% | No |

At OOS end: solo holds ~0.513 SPY long; independent holds ~0.257 SPY
long **and** ~0.437 QQQ short; the coordinated pair is flat. Do not
interpret closed-trade win rate as total performance while inventory remains.

## Post-hoc cost sensitivity (nonconfirmatory)

Same trading rules, actual engine re-runs; cost scenarios were introduced
*after* the base OOS result was observed. They are for risk diagnosis and
cannot support model selection or independent OOS claims.

| Phase | Cost per fill | SPY solo net | Independent net | Pair net |
|---|---:|---:|---:|---:|
| Development | 0 bps | -44.10 | -39.60 | +20.51 |
| Development | 4 bps | -45.38 | -44.86 | -20.87 |
| Development | 8 bps | -46.26 | -46.14 | -49.04 |
| OOS | 0 bps | +18.33 | -18.99 | +1.20 |
| OOS | 4 bps | +12.63 | -22.34 | -10.17 |
| OOS | 8 bps | +4.26 | -26.76 | -21.55 |

The paired grid's OOS turnover was about $28,442 at 4 bps/fill. Its
negative $10.17 net return implies a *purely arithmetic* required additional
reward above ~3.58 bps of traded notional to break even, before omitted funding,
spread and real fill costs. This is **not** an Arcus points valuation.

## Artifacts and reproduction

```bash
# In /home/quant/dev/quant/ml4t-data:
.venv/bin/python scripts/fetch_lighter_rwa_1m.py --start 2026-01-22T00:00:00Z

# In /home/quant/dev/quant/quant-research:
.venv/bin/python scripts/run_lighter_spy_qqq_grid_comparison.py --phase development
.venv/bin/python scripts/run_lighter_spy_qqq_grid_comparison.py --phase test
.venv/bin/python scripts/run_lighter_spy_qqq_grid_comparison.py --phase test --cost-bps 0
.venv/bin/python scripts/run_lighter_spy_qqq_grid_comparison.py --phase test --cost-bps 8
```

Metrics and full configuration are under
`run_log/lighter_spy_qqq_pair_grid_20261009/` as JSON files.
The script records post-hoc runs separately and does not submit live orders.

## Next falsifier / missing evidence

1. Audit Lighter and Arcus SPY/QQQ historical bid-ask spreads, trade depth,
   funding and the difference between their off-hours reference prices.
2. Replace synthetic market fills with genuine limit-order / queue-aware fills.
3. Enforce absolute marked gross/leg inventory caps and orphan-leg unwind.
4. Test a time-segmented follow-on sample with independent verification and
   only then evaluate whether Arcus incentives offset real costs.
5. Do not select one of these three variants for production from this sample.
