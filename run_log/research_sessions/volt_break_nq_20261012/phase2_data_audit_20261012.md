# VOLT BREAK — Phase 2 data acquisition and validation (2026-10-12)

## Decision

- **PASS FOR EXPLORATORY CFD-PROXY RESEARCH** with the strict 2019–2025 qualifying-session mask below.
- **NOT VERIFIED FOR EXACT CME NQ FUTURES REPLICATION:** underlying prices are Dukascopy USATECH.IDX/USD BID CFD quotes, not dated CME futures contracts. The volume column is labeled provider 'units', not independently verified CME executed-contract volume. Therefore a CFD-volume-weighted *proxy VWAP* is permitted for research, but should not be called the actual NQ exchange VWAP.
- Phase 3/4 must not change strategy rules silently, pass missing minutes forward, or claim a live-executable NQ win rate. No trading outcome, protected September–October 2026 holdout, or strategy parameter was examined in this audit.

## Provenance and source identity

- Canonical raw-equivalent store: `/home/quant/dev/quant/ml4t-data/.data/store/index_minute_NQ/`
- Provider: Dukascopy `usatechidxusd` / `USATECH.IDX/USD`, one-minute **BID** OHLCV proxy.
- Source timestamps are naive UTC, not America/Chicago. Apply `replace_time_zone("UTC")`, then `convert_time_zone("America/Chicago")`; never interpret as naive CT or a fixed GMT offset.
- Provider contract reports `volume_units: units`, not verifiable CME trade volume. Earlier 2013 candle volume scale differs strongly from 2019–2025; do not use raw volume totals to compare liquidity across eras.
- Existing per-file SHA256 manifest: `run_log/one_bar_dukascopy_2013_2026_20261011/source_manifest.json`
- Existing source/calendar qualification: `run_log/one_bar_dukascopy_2013_2026_20261011/calendar_qualification.json`; provider qualification identity `f27123afdeeaf13b65fd1215b7fdc4c751f870a370cb0d3c91477328d08f0e95`. Calendar qualification starting 2011 does **not** indicate this price store starts in 2011.
- Earlier independent investigation: `docs/audit/one_bar_dukascopy_2013_2026_20261011.md`; its source-quality report records long historical gaps, including the 2017 gap.
- Separate candidate `index_minute_NAS100` has 2011-origin history but provider is London Strategic Edge (LSE), mostly RTH only. Metadata: `/home/quant/dev/quant/ml4t-data/.data/store/.metadata/index_minute_NAS100.json`. It is not a substitute for a 00:00 CT anchor.
- Frozen Phase 1 session currently binds a **2024–2025** snapshot at `data/processed/nq_1m.parquet` (648,592 rows, 2024-01-01 23:00 UTC through 2025-12-31 21:13 UTC). Preserve this frozen identity. Register a new versioned session/source scope before using full 2019–2025 partitions as Phase 3 development data.

## Read-only quality results

Scope: 2013–2025 Dukascopy source partitions, no 2026 market outcomes read:

| Check | Dukascopy NQ | LSE NAS100, 2011–2025 |
| --- | ---: | ---: |
| Partitions scanned | 156 | 180 |
| Price rows | 3,711,128 | 1,502,463 |
| Null in timestamp/OHLCV | 0 | 0 |
| Duplicate timestamps | 0 | 0 |
| Nonfinite OHLC rows | 0 | 0 |
| Invalid OHLC geometry | 0 | 0 |
| Dates with 00:00 CT bar | 2,274 | 22 |

Dukascopy NQ has **zero** midnight CT bars in both 2016 and 2017. 2018 has partial coverage. LSE cash-session candles have zero midnight bars for each year 2011–2024. Earlier data therefore cannot be treated as equivalent 00:00-anchored sessions.

## Strict 2019–2025 candidate session mask

A candidate day passes a preliminary data-availability gate if:
1. Local CT date is valid (DST-aware IANA timezone, using source UTC minute timestamps).
2. 00:00 and 10:00 CT bars exist.
3. At least **861 of the 870 distinct minutes** from 00:00 to 14:29 CT exist (99% rounding).
4. A 14:30 CT open timestamp exists for the hard exit.
5. Volume is finite and positive for actual recorded NQ minutes; no fabricated zeros/fills.

| Year | Observed days | At least 99% complete and boundary-ready | Fully complete (870/870 + exit) |
| --- | ---: | ---: | ---: |
| 2019 | 237 | 227 | 211 |
| 2020 | 244 | 230 | 221 |
| 2021 | 247 | 239 | 234 |
| 2022 | 247 | 239 | 231 |
| 2023 | 247 | 237 | 231 |
| 2024 | 247 | 236 | 227 |
| 2025 | 244 | 233 | 221 |
| **Total** | **1,713** | **1,641** | **1,576** |

Every observed 2019–2025 minute in the relevant 00:00–14:29 interval had positive reported source volume; this does not make it exchange trade volume. Holiday half-sessions and interrupted days lacking 14:30 exits are explicitly disqualified.

**Caution:** The 99% mask only qualifies day-level availability. Feature computations and order simulation must additionally require every minute contributing to each 30-minute signal bar or exit interval; skip missing-minute events and ambiguous same-minute TP/SL ordering or stress their adverse outcomes. For a completely missing 1-minute VWAP observation, do not impute trade volume or price. A full 870/870 mask is the cleanest primary robustness/control cohort.

The stricter audit's first attempt was invalid because 8-bit time components overflowed during `hour * 60`; it was corrected to 32-bit minute-index arithmetic before using the results above. The invalid preliminary counts are excluded from the decision.

## Pending Phase 3 contract choices

1. Prefer the **2019–2025 complete-minute primary cohort** (1,576 source days); separately show broader 99% availability cohort if reconstruction tolerates isolated gaps without imputation.
2. The source's BID prices and provider-volume-weighted approximate VWAP are research proxies. Do not label this a replication of genuine exchange-traded NQ VWAP.
3. Preserve 00:00 CT clock, 30-minute bars, 10:00–14:30 CT signal/fill limits, fixed +40/-75 point NQ-equivalent TP/SL, and three-entry cap without optimization.
4. Freeze exact session daily ATR definition from *completed* sessions before generating signals. Do not conflate 15 completed daily true ranges with the mean of a separately smoothed daily ATR.
5. Use a 1m quote-bar fill model with conservative stop/limit ordering, CFD-vs-CME basis caveat, and explicit per-contract NQ commission/slippage as assumptions.
6. Keep already-observed 2026 periods separate from sealed future evaluation. No results from Sep–Oct 2026 may drive selection.

## Reproduction

Run from `/home/quant/dev/quant/quant-research`:
- `.venv/bin/python scripts/audit_volt_break_data_probe_20261012.py`
- `.venv/bin/python scripts/audit_volt_break_quality_20261012.py`
- `.venv/bin/python scripts/audit_volt_break_intraday_grid_20261012.py`

These three read-only scripts inspect canonical files and print data diagnostics. No market-data download, canonical-store mutation, backtest, or Git commit was performed.
