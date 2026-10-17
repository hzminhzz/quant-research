# VWAP pullback + ADX: local data discovery (2026-10-12)

Status: READ-ONLY PRELIMINARY DATA CHECK. No strategy trial, PnL, signal selection, or holdout evaluation occurred.

Session: `vwap_pullback_adx_nq_20261012`.
Repository state inspected: main at c095faa, with pre-existing unrelated dirty work. The frozen Phase 1 YAML and frozen_spec.json have not been changed by this check.

## Discovered sources

1. Dukascopy USATECH.IDX/USD (NQ-alias) staged rebuild:
   `/home/quant/dev/quant/ml4t-data/.data/rebuild/duk21_usatechidxusd/index_minute_NQ/`
   Source report: `/home/quant/dev/quant/ml4t-data/.data/rebuild/duk21_usatechidxusd_pass.json`.
   Source report states 2011-09-19 through 2026-08-17, 4,839,248 rows, 4,493 COMPLETE days, 954 EXPECTED_CLOSED days, status PASS. This is a *staged rebuilt CFD dataset*, not the unchanged legacy live store.
2. Legacy `/home/quant/dev/quant/ml4t-data/.data/store/index_minute_NQ/`: year folders 2013-2026, latest sample 2026-07-14, older naive timestamp schema. Do not substitute it for the staged rebuilt history silently.
3. LSE NAS100/USD `/home/quant/dev/quant/ml4t-data/.data/store/index_minute_NAS100/`: metadata states LSE, not Dukascopy, 2011-01-03 to 2026-10-02, 1,770,875 rows, 190 monthly partitions.
4. LSE futures-labeled NQ.F one-minute candidate:
   `/home/quant/dev/quant/ml4t-data/.artifacts/lse-orb/raw-nq/futures_NQ.F_1m.parquet`
   Observed file covers 2025-09-19 through 2026-10-02, with 366,913 bars. Its `ts` field must be mapped to `timestamp`. The LSE `NQ.F` product is **not yet verified** as a specific dated CME contract with true exchange trade volume and roll accounting.
5. Repo `data/processed/nq_1m.parquet` is only a limited 2024-2025 materialization; it is not the full history.

## Observed 2026 mechanical checks (UTC timestamps converted to America/Chicago)

| Source | Bars in observed 2026 file range | 08:30-08:59 CT bars | 15:55 CT bars | Zero-volume OR bars | Duplicate timestamps | Invalid OHLC high/low |
|---|---:|---:|---:|---:|---:|---:|
| Dukascopy staged NQ | 214,195 | 4,830 | **0** | 4 | 0 | 0 |
| LSE NAS100 | 268,412 | 5,850 | 188 | 2,340 | 0 | 0 |
| LSE NQ.F | 267,734 | 5,602 | 189 | 0 | 0 | 0 |

Dukascopy 2026 observed end: 2026-08-17. LSE 2026 observed end: 2026-10-02.

Dukascopy sampled complete regular days 2026-01-07, 2026-03-11, 2026-07-07, and 2026-08-07 each had all 30 opening-range bars but *no* 15:55 CT bar. The full scanned Dukascopy 2026 files also contained zero 15:55 CT bars. This is a source trading-hours mismatch to the specified strategy, not a random missing-bar finding. Do not use synthetic fills at 15:55 CT.

LSE NAS100 had 2,340 zero-volume opening-range bars, exactly 78 complete 30-minute opening ranges with zero recorded volume (first 2026-01-02, last 2026-04-24). Do not calculate VWAP using these volume-zero ranges. The provider-reported volume of either CFD/index feed is not proof of CME futures traded-contract volume. Dukascopy volumes vary in scale between the rebuilt and legacy stores; do not combine without source normalization and a documented proxy definition.

LSE NQ.F has the 15:55 CT window on most observed 2026 sessions and no zero-volume opening-range bars in the 2026 scan. It is preferable for a **candidate faithful 2026 timing/VWAP backtest** after verifying product mapping, traded volume provenance, active futures contract, rolls, fee model and partial OR bar sessions. A label containing `NQ.F` alone does not establish actual CME execution fidelity.

## Decision / next gate

- AVAILABLE for Phase 2: Historical Dukascopy price-pattern research back to 2011 (Opening Range, ADX, directional/reclaim diagnostics), as CFD proxy.
- NOT equivalent to exact original strategy: Dukascopy lacks the 15:55 CT bar and does not establish true CME traded-volume VWAP. Any earlier exit or broker-volume-weighted proxy must be separately labeled as a changed strategy.
- BEST 2026 candidate: LSE NQ.F for primary Phase 2 inspection, pending contract/volume identity and missing-minute checks; preserve Dukascopy for long-history robustness.
- Do not splice Dukascopy entries to LSE exits. Do not silently modify the create-once `run_log/research_sessions/vwap_pullback_adx_nq_20261012/frozen_spec.json`. A revised input specification needs a separately versioned research session and trial ledger before Phase 3/4.
- No backtests or holdout scores were run.
