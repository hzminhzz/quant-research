# Workstation Data Catalog & Environment Manifest

This manifest documents the exact datasets, date ranges, storage formats, and libraries installed on the execution workstation (`/home/quant/`). Web coding agents without direct SSH access should consult this document to ground research scripts, backtests, and feature engineering.

---

## 1. Storage Location & Loading Convention

All historical data lives centrally in **`ml4t-data`**, stored as Hive-partitioned Parquet with zstd compression:
- **Base directory:** `/home/quant/dev/quant/ml4t-data/.data/store/`
- **Partitioning format:** `<dataset_name>/year=YYYY/month=MM/[day=DD/]data.parquet`

### Canonical Polars Loading Pattern
```python
from pathlib import Path
import polars as pl

def load_store(dataset_name: str, start_date: str | None = None, end_date: str | None = None) -> pl.DataFrame:
    """Discovers and concatenates partitioned Parquet files for a given dataset."""
    store_dir = Path("/home/quant/dev/quant/ml4t-data/.data/store") / dataset_name
    files = sorted(store_dir.rglob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"Store {dataset_name} not found or empty at {store_dir}")
    
    # Lazy scan across all partitions
    lf = pl.scan_parquet(files)
    if start_date:
        lf = lf.filter(pl.col("timestamp") >= pl.lit(start_date).str.to_datetime())
    if end_date:
        lf = lf.filter(pl.col("timestamp") <= pl.lit(end_date).str.to_datetime())
    return lf.collect()
```

---

## 2. Available Datasets & Provenance

### A. Cash Indices & Index Proxies (CFD / Spot Quotes, NOT Exchange Futures)
**Provenance & Tradability:** `index_*` series are cash index / CFD proxy quotes supplied via Dukascopy and London Strategic Edge (LSE). For example, `HK33` is LSE's `HK33/HKD` cash index series, not an HKEX futures contract. Similarly, `index_minute_ES` and `index_minute_NQ` represent broker-quoted index CFDs, not CME exchange futures order books. Vendor session semantics, overnight financing, and execution slippage require separate qualification.

Schema: `timestamp` (UTC datetime), `symbol` (str), `open`, `high`, `low`, `close`, `volume` (float64)

| Dataset Name | Instrument / Underlying | Provider / Source | Resolution | Date Range | Size / Files |
|---|---|---|---|---|---|
| `index_second_ES` | S&P 500 Index Proxy | Dukascopy CFD | **1-second** | 2023 – 2026 | Sub-minute seconds |
| `index_second_NQ` | Nasdaq 100 Index Proxy | Dukascopy CFD | **1-second** | 2023 – 2026 | Sub-minute seconds |
| `index_minute_ES` | S&P 500 Index Proxy | Dukascopy CFD | **1-minute** | **2011-10 to 2026-09** | 4,542 files |
| `index_minute_NQ` | Nasdaq 100 Index Proxy | Dukascopy CFD | **1-minute** | **2011-10 to 2026-09** | 4,542 files |
| `index_minute_DAX` | DAX 40 Index Proxy | Dukascopy CFD | **1-minute** | 2018 – 2026 | Comprehensive |
| `index_minute_NIKKEI225` | Nikkei 225 Index Proxy | Dukascopy CFD | **1-minute** | 2018 – 2026 | Comprehensive |
| `index_minute_HSI` | Hang Seng Index | Dukascopy / LSE | **1-minute** | 2019 – 2026 | Comprehensive |
| `index_minute_HK33` | Hong Kong 33 Series | LSE (`HK33/HKD`) | **1-minute** | 2019 – 2026 | Unqualified tradability |
| `index_minute_EUSIDXEUR` | Euro Stoxx 50 Proxy | Dukascopy CFD | **1-minute** | 2018 – 2026 | Comprehensive |
### B. Foreign Exchange (Wave-1 LSE & Dukascopy FX)
Schema: `timestamp` (UTC datetime), `symbol` (str), `open`, `high`, `low`, `close`, `volume` (float64)

| Dataset Name | Pair | Resolution | Date Range | History |
|---|---|---|---|---|
| `forex_minute_EURUSD` | EUR/USD | **1-minute** | **2009-10 to 2026-09** | 17 Years |
| `forex_minute_USDJPY` | USD/JPY | **1-minute** | **2009-10 to 2026-09** | 17 Years |
| `forex_minute_GBPUSD` | GBP/USD | **1-minute** | 2009-10 to 2026-09 | 17 Years |
| `forex_minute_GBPJPY` | GBP/JPY | **1-minute** | **2003-10 to 2026-09** | **23 Years** |
| `forex_minute_USDCHF` | USD/CHF | **1-minute** | **2003-10 to 2026-09** | **23 Years** |
| `forex_minute_AUDUSD` | AUD/USD | **1-minute** | 2009-10 to 2026-09 | 17 Years |
| `forex_minute_USDCAD` | USD/CAD | **1-minute** | 2009-10 to 2026-09 | 17 Years |
| `forex_minute_NZDUSD` | NZD/USD | **1-minute** | 2009-10 to 2026-09 | 17 Years |
| `forex_minute_CADJPY` | CAD/JPY | **1-minute** | 2009-10 to 2026-09 | 17 Years |
| `forex_minute_EURGBP` | EUR/GBP | **1-minute** | 2009-10 to 2026-09 | 17 Years |

### C. Commodities & Precious Metals
| Dataset Name | Asset | Resolution | Description |
|---|---|---|---|
| `xauusd_1m_ohlcv` | Gold (XAU/USD) | **1-minute** | Spot Gold 1m OHLCV |
| `xagusd_1m_ohlcv` | Silver (XAG/USD) | **1-minute** | Spot Silver 1m OHLCV |
| `forex_tick_XAUUSD` | Gold (XAU/USD) | **Tick-level** | Raw Dukascopy tick stream |
| `commodity_minute_CL` | WTI Crude Oil | **1-minute** | NYMEX Crude Oil futures 1m |

### D. Crypto Perpetuals Funding Rates (660+ Pairs)
Schema: `timestamp` (UTC datetime), `symbol` (str), `funding_rate` (float64)
- **Coverage:** 200+ symbols (e.g. `crypto_futures_funding_BTCUSDT_PERP`, `ETHUSDT_PERP`, `SOLUSDT_PERP`, `DOGEUSDT_PERP`)
- **Span:** **2019-10 to 2026-10** (8-hour funding settlements).

### E. Real-World Asset (RWA) & DEX Perpetuals
- `crypto_futures_ohlcv_1m_HYPERLIQUID_XYZ_PERP`: Hyperliquid 1m perps (2026).
- `crypto_futures_ohlcv_1m_LIGHTER_USDC_PERP`: Lighter DEX 1m perps (2026).

### F. High-Frequency Market Making Depth (`.npz`)
- Location: `/home/quant/dev/quant/quant-research/data/hftbacktest/`
- Tickers: `btcusdt_*.npz`, `ethusdt_*.npz` (L2 order book tick events for HFT simulation).

### G. Macro & Fundamental Data
- FRED Macro: `fred_daily_DGS10` (10Y yield), `fred_daily_VIXCLS` (VIX), `fred_daily_CPIAUCSL` (CPI), `fred_daily_UNRATE`.
- CFTC COT: `cot_weekly` (Commitments of Traders institutional positioning).
- Token Unlocks: `alternative_token_unlocks_PATTERNPLUS` (Point-in-time token emission unlocks).

---

## 3. Installed Execution & Analytics Ecosystem

When writing code for this environment, target the installed Python 3.14 virtual environment (`/home/quant/dev/quant/quant-research/.venv/`):

1. **`ml4t.engineer`:** 120 Polars/Numba technical & microstructure indicators (`compute_features`), fractional differencing (`ffdiff`), and leakage-safe `create_dataset_builder`.
2. **`ml4t.diagnostic`:** Statistical validation (`deflated_sharpe_ratio`, `compute_pbo`, `benjamini_hochberg_fdr`, `generate_backtest_tearsheet`).
3. **`ml4t.backtest`:** Parity-audited event-driven engine (`Engine`, `Strategy`, `DataFeed`, bracket orders, position rules).
4. **`ml4t.live`:** `LiveEngine`, `SafeBroker` (kill switches, pre-trade drawdown limits).
5. **Connectors:**
   - `connectors/propr/`: Propr challenge accounts (`ProprLiveBroker`, `IntentJournal`).
   - `connectors/bybit/`: Bybit V5 Unified Trading Account via CCXT (`BybitLiveBroker`, `BybitKlineFeed`).
   - `connectors/hyperliquid/`: Hyperliquid DEX via CCXT (`HyperliquidLiveBroker`, `HyperliquidKlineFeed`).
