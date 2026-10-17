# FVG Trident + EMA trend | FX MVP | 2026-10-14

**Status:** EXPLORATORY. **Authority:** user-supplied Chinese charts and translation, not an independently verified track record.

## Research question

Does an M30 bullish FVG midpoint-rejection and unusual literal next-bar confirmation, traded only at 03:00–06:30 New York time when D1 > EMA200 and the M30 EMA ribbon is rising, deliver positive cost-adjusted USD R per trade?

### Extracted source rules versus operational assumptions

| Component | Directly in source | MVP definition (if added, this is an assumption) |
|---|---|---|
| Entry clock | NY 03:00–06:30 | Fill time in [03:00,06:30), NY local DST; signal must be complete before fill |
| Higher-timeframe direction | D1 price above EMA200 | Last completed NY 17:00 daily close > D1 EMA200 |
| EMA ribbon | M30 EMA 5>9>13>21 and lines rising | All strict ordering and one-bar positive slopes at setup and confirmation |
| FVG | Three consecutive candles: high(first)<low(third) | Bullish gap [A.high,C.low], midpoint average, maximum 48 complete M30 candles (assumed) |
| Retest/Doji | Wick goes past FVG 50%; small body; price recovers above gap | low(D)<=gap midpoint, close(D)>gap top, body/range<=0.25, lower-wick/range>=0.50 (thresholds assumed) |
| Confirm | Wait exactly one more M30 close; **close below Doji high**, otherwise skip | Preserve literal inequality close(E)<high(D); no bullish-close requirement inserted |
| Entry | Enter after qualifying confirm | Earliest next 5m open; reject if session/stop constraints fail |
| Initial stop | Below low of FVG-forming candle | min(low A, low B, low C) minus 1 pip (ambiguous source choice, declared approximation) |
| Holding/exit | Hold while D1 trend persists; MAs cross/structure break as discretionary exits | Initial STOP plus first D1 close below EMA21; next 5m exit (approximation; not source-exact) |
| Potential 20R | Author describes holding for very large winners | Report MFE>5R/10R/20R; never assume a 20R take-profit or achieved outcome |

Do not silently change the counterintuitive Step-3 inequality. Note that a confirmation candle may be bearish. Source images also do not say *which* FVG-forming low defines the stop, a precise numerical Doji threshold, FVG expiry, or an unambiguous exit EMA.

## Smallest research sequence

1. **P0:** Reuse existing LSE 5m snapshots for EURUSD, GBPUSD and AUDUSD, 2010–2024. Validate OHLC, exact six-component M30 bars, UTC to NY DST, prior completed 17:00-NY daily candles, source manifest, and installed ml4t-engineer EMA semantics. Leave 2025–2026 holdout uninspected for returns.
2. **D0:** Build causal M30 and D1 features using official ML4T engineering/verified Polars patterns. Measure the funnel from all FVGs to completed entries; log each rejection. No tuning.
3. **T1:** Implement fill/risk accounting in **native ml4t.backtest Engine**, not hand-rolled trade loops. Fill on next 5m open, price stops as native STOP orders, use D1 EMA21 exit. Calculate USD-position R and independent execution-clock invariants.
4. **T2:** Frozen execution stress at 2.50 bps round-trip, no altered signal.
5. **Decision:** Require >=100 pooled completed trades, >=20 in each pair, 2/3 positive mean R, positive pooled net R with lower bound of month-clustered 95% CI >0. Otherwise REJECT or INCONCLUSIVE. A provisional pass is not a deployment approval; overnight swap remains unpriced.

## Economic hypothesis and weakest assumptions

A gap on an **OHLC FX chart** does not prove that price levels received no trades: it is a three-candle overlap pattern, not order-book evidence. The proposed mechanism is demand persisting through a transient repricing and a midpoint retrace. The experiment must falsify, not assume, this mechanism.

The 03:00–06:30 clock, EMA alignment and two-stage candle confirmation may reduce opportunities to a small sample. Source claims **6–10 opportunities per pair per year and some 20R holds** are unverified; report independent counts and achieved R. Overnight carry, actual FTMO quotes, stop-market gap slippage, NY rollover widening and product-specific leverage remain unresolved.

## Execution and provenance

- Frozen YAML: `config/research_sessions/fvg_trident_fx_mvp_20261014_v1.yaml`
- Canonical data: `data/processed/ftmo_fx_reversion_202610/`, see `manifest.json`
- Development: `2010-01-04` through `2024-12-31`; preexisting 2025+ final holdout stays unopened.
- Source: four user-provided Chinese annotated chart images plus the translated Oct 14, 2026 @OtherSideBJ thread.
- Skills: bundled `ml4t-skills` references `build-bars`, `calendar-ops`, `compute-features`, `run-backtest`, `point-in-time`, `transaction-costs`, `validate-data`, and `strategy-workflow`. Local `AGENTS.md` requires native `ml4t.engineer` and `ml4t.backtest` for actual research.
- Preserve concurrent dirty repo work and existing tmux sessions. Do not commit unrelated changes or claim a complete trial absent trace/ledger.
