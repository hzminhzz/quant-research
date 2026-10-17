# Independent review — Dukascopy NQ 2013–2026 one-bar replication (2026-10-11)

Status: VERIFIED exploratory backtest artifacts with significant qualification. **NOT APPROVED for CME futures deployment.** The principal Codex run may still be completing its final report.

## Verified directly from saved ML4T Engine artifacts

Study source: Dukascopy usatechidxusd / USATECH.IDX-USD BID index CFD price proxy, *not* CME E-mini NQ. Its legacy store index_minute_NQ is unqualified/noncanonical for institutional futures research. Parsed data consists of 3,883,929 1m rows, January 2013–2026-07-14; no nulls, duplicate timestamps or invalid OHLC in the historical store, but 11,744 incomplete 30-minute bars. Source timestamps are naive UTC according to original Dukascopy UTC epoch decoder. Source future-feed completeness is not point-in-time knowable.

One simulated NQ-equivalent $20/point contract, stop $1,000 = 50 index points, original 50 completed 30m-bar extreme breakouts, next 30m opening print exit, maximum 2 entries per Chicago session day. These proxy dollar values do not prove actual CFD contract economics.

| Run | Closed trades | Total PnL | Average PnL/trade | Net PF | Daily-equity Sharpe |
| --- | ---: | ---: | ---: | ---: | ---: |
| No friction | 5150 | +$246,425.90 | +$47.8497 | 1.4618 | 2.0657 |
| Quarter-tick friction | 5150 | +$207,805.90 | +$40.3507 | 1.3765 | 1.7296 |

**Independent arithmetic check**: All 5,150 trades in each saved trades.csv have status=closed, and sum(pnl) equals (final_value-initial_cash) to cents. No max holding duration exceeds 30 minutes in saved metrics, and saved max entries/session day=2. Test invocation with uv run --no-sync python -m pytest -q tests/test_one_bar_dukascopy_2013_2026_20261011.py passed 3 focused tests.

### Relative to screenshot

Screenshot visually implies approximately $200,000 after ~4,800 trades, average $41.67. The quarter-tick proxy output has +$207,806 after 5,150 trades, average $40.35. Similar order of magnitude and late-history acceleration; not exact evidence of same historical series, date range, stop convention or brokerage cost. Unlike 2026-only LSE proxy (negative 2026), this long-term Dukascopy proxy is strongly positive.

### Important unresolved issues

1. **Cost discrepancy**: The planned cross-run cost model was $2.50 commission PER SIDE plus one NQ tick 0.25 index point adverse slippage PER SIDE. The actual proxy cost-aware run instead uses NQ_TICK/4 = 0.0625 index point PER SIDE, one-quarter of one futures tick. Its total costs $38,625 and net +$207,805.90 are correct for its **actual** low-friction assumptions, but they are NOT a verified full-one-tick cost test. Run a separate versioned full-one-tick Native Engine sensitivity before asserting all originally specified costs have been tested. Preserve the completed trial ledgers; do not overwrite/relabel historical cost result.
2. **Retrospective future data availability gate**: Runner entry_valid checks that subsequent 30m candidate and following 30m bar exist and are complete. This uses future price-feed availability as a retrospective sample-quality exclusion. It is not a live-causal decision gate; missing-bar exclusions must be counted separately and future-known availability must not be misrepresented as a tradeable live signal. Re-run sensitivity if material.
3. **Intrabar ambiguity**: 42 cases where 1m OHLC intersects entry and protective stop, sequence unknown. Count is recorded and main run keeps as-modeled fills, not tick-level truth.
4. **Proxy identity**: Bid-only Dukascopy index CFD prices, not dated CME futures; no verified CME tick, 24-hour availability, roll treatment, spread, queue execution, or margin. Price was mapped counterfactually to NQ $20/point, $0.25 tick and $1,000 adverse stop.
5. **Research status**: Strong retrospective performance may be driven by recent higher nominal Nasdaq index points or volatility, and does not prove a stable economic causal mechanism or OOS robustness. Prior 2026-only loss and strong 2018–2025 proxy data can coexist.
6. **Research workflow**: The runner uses a precomputed next-bar availability flag in signals; review whether this compromises point-in-time execution under missing data. The reported positive PnL is exploratory until a corrected causal, data-quality aware execution replication.

Outcome: exploratory evidence materially supports investigating the manager's historical curve rather than dismissing it on seven months of LSE proxy data. Do not approve live trading, classify as retrospection only, and run full-tick cost/availability stress next.
