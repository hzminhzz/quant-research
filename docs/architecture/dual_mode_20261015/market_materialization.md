# FX, index, and metals canonical price-vault materialization

## Scope and output (expanded to native 1m/1s on 2026-10-16)

The immutable source is the local `ml4t-data` directory:
`/home/quant/dev/quant/ml4t-data/.data/store/`.

The new trusted entry point discovers historical source directories in the
`forex_minute_*`, `index_minute_*`, `index_second_*`, `forex_daily_*`, and `index_daily_*`
namespaces. Native 1m prices are copied without downsampling; native 1s
ES/NQ are copied one day at a time. Other views stream month-sized source chunks into the exact twelve-column
canonical Parquet schema, writes source- and output-hashed receipts, and keeps
`development/` physically separate from `protected/`. The protected cutoff is
**2026-01-01 00:00:00 UTC**. The compilation horizon ends exclusively on
**2026-10-01 00:00:00 UTC**. No feature, backtest, or strategy evaluation opened
protected rows as part of this work unit.

Root:
`data/vault/market_prices_20261015/`

| Vault | Symbols | Development rows | Protected rows | Actual observed earliest | Actual observed latest | Manifest SHA-256 identity |
| --- | ---: | ---: | ---: | --- | --- | --- |
| `forex_1h` | 8 | 927,611 | 37,282 | 2003-05-04 | 2026-09-30 | `0730f0b8d87b442d60b60dc0eddf3a8a0e3e9996b794bcdf0d77e91149ce2b52` |
| `index_1h` | 6 | 392,216 | 23,118 | 2011-09-19 | 2026-09-30 | `961450699ef98c8a99c0e5a212486f8dde0e6ba39476605d896c23f49656eae2` |
| `metals_1h` | 2 | 215,095 | 5,730 | 2007-01-01 | 2026-07-01 | `ef04bc22a56df5b445b401f06b37ca0e760c8b69fdcff8a3d3fc4d7914bff8a7` |
| `forex_1d` | 13 | 48,774 | 3,042 | 2014-01-01 | 2026-09-30 | `4557455594e72bc909d14ad8db544990fbd9c85a4e94468daf6588642ba24f0b` |
| `index_1d` | 2 | 7,048 | 466 | 2014-01-01 | 2026-09-30 | `599abbf06ca1c6fa136f410883bb5ce51b34ada01fb48cd2b9db40b0d4b3fdf9` |
| `forex_1m` | 8 | 54,781,706 | 2,225,667 | 2003-05-04 | 2026-09-30 | `43e016767aa6527f9a84802c47d3b1c3c1f7dea92951a41606cc4481cce2d86e` |
| `index_1m` | 6 | 22,422,156 | 1,331,698 | 2011-09-19 | 2026-09-30 | `9fe7fd704b76607f70314a4fb0d1aaad79c1b415b4ac7c012fe8e17ce18061c0` |
| `metals_1m` | 2 | 12,371,797 | 342,962 | 2007-01-01 | 2026-07-01 | `316097158ecf40d424e92770a3985945ae9163c9b3b19b2b6656e5ba7f5e2505` |
| `index_1s` | 2 | 25,865,820 | 22,909,651 | 2025-01-01 | 2026-09-30 | `6da4df75158113f4031b1662e24896e13fff06f621a3a7b6895b5e5fd2d66f84` |

Total across nine views: **117,032,223 development rows**, **26,879,616 physically
protected rows**, 49 symbol-frequency series (including the prior 31 hourly/daily
views) and 22 distinct market identities. The four new native 1m/1s views alone
contain **115,441,479 development** and **26,809,978 protected** observations.
The `1s` source begins in 2025; earlier index minute history cannot be
reconstructed as native seconds. This count does not assert full historical coverage for
each instrument or a corporate-action-adjusted index. The observed start/end
bounds are the union of market sources and must not be interpreted as every
symbol's continuous coverage.

## Identifiers and sources

- Hourly FX: AUDUSD, CADJPY, EURUSD, GBPJPY, GBPUSD, USDCAD, USDCHF, USDJPY
- Hourly indices: DAX, ES, EUSIDXEUR, HK33, NIKKEI225, NQ
- Hourly quoted precious metals: XAGUSD, XAUUSD
- Daily FX: AUDJPY, AUDUSD, CADJPY, CHFJPY, EURGBP, EURJPY, EURUSD, GBPJPY,
  GBPUSD, NZDUSD, USDCAD, USDCHF, USDJPY
- Daily index/ETF proxies: DAX and SPY
- Native 1m FX/index/metals: the same 8 FX, 6 index, and 2 metal sources as the
  hourly views. No synthetic minute gaps or 1h resampling are used for these.
- Native 1s index prices: ES and NQ only; the store has no FX/metals 1s sources.
  These are **observed-second OHLC bars**, not a guaranteed complete 86,400-second
  day. Do not interpret absent seconds as unchanged price.

Source identity caveats:

1. `index_minute_HSI` is **not an additional HSI instrument**. The Parquet
   source labels itself `HK33`; the file-tree alias was excluded to avoid
   double counting `index_minute_HK33`.
2. The `forex_daily_USDJPY` Parquet files internally use the label `JPY`.
   This single explicit source alias is mapped to USDJPY after comparing
   Dec 1, 2025 provider daily open/close (155.907, 155.561) to the independent
   USDJPY minute source (155.900, 155.556). The original symbol is retained
   in the partition provenance. This is a source-label reconciliation, **not**
   exchange certification of a forex dealing contract.
3. SPY is a stock-market-tracking ETF source, **not** a directly tradable cash
   S&P 500 index nor an ES CFD. NQ/ES names from an `index_minute` directory
   are not CME futures contract/volume proof.
4. 2026 gold/silver observed data end earlier than most FX/index sources;
   no later bars were generated.
5. The original `forex_minute_CADJPY` **February 2008** month is rejected by
   `validate_panel` because source OHLC values violate price invariants. It was
   not silently repaired or imputed; the `forex_1m` manifest records `BLOCKED_DATA`.
6. The `index_second_ES` / `index_second_NQ` files are source-vendor index
   quote proxies. They are not evidence of CME exchange-traded volume or HFT
   executable bid/ask spreads.

## Coverage, costs, and safe use

The 1-second and 1-minute views preserve every valid observed input OHLC row,
including exact UTC timestamps. Each native 1s/1m record has an observed-bar
`is_tradable` flag based on clock alignment, **not** proof that surrounding seconds,
minute bars or broker dealing hours are complete. The final manifests separately
count observed inter-row gaps greater than the cadence: FX 1m **201,025**,
indices 1m **227,623**, metals 1m **229,574**, indices 1s **7,686,427**.
These counts measure discontinuous transitions, **not the number of absent
seconds/minutes**. The 1-second feed is sparse and not forward filled. Native
1s files are grouped into bounded, immutable daily partitions; 1m files into
monthly partitions. Inspect a short date window with `DataVault.load()` rather
than loading all second-level data into notebook memory.

The 1-hour compiler aggregates observed 1-minute bars using first open,
maximum high, minimum low, last close and source-reported volume sum. A bar is
marked `is_tradable` **only when all 60 distinct minutes of its hour are
present**, with the first and final minute at the expected boundaries. A
partial hour is retained for transparency but `is_tradable=false`. This is a
source-continuity flag, **not a verified broker dealing calendar**. The daily
source uses native daily bars and a UTC day identifier, not intraday-derived
daily bars. The canonical volume remains an unverified vendor quote/tick proxy,
not exchange turnover. DST and broker daily swap rollover conventions are not
inferred from these files.

The canonical columns `carry_rate` and `spread_bps` are **zero-shaped
placeholders** solely because this price-only source has no verified directional
CFD overnight swaps or actual quoted bid/ask spread history. These zeros
**DO NOT MEAN zero financing or a zero market spread**. The explicit manifest
flags `execution_qualified=false` and `carry_status` /
`spread_status=UNKNOWN_NOT_EXECUTION_QUALIFIED` prevent the new factory's
Stage 3 and Workbench's native backtest from silently simulating free
execution. Workbench `load()`, feature construction and IC are available on
development data; a real PnL test requires a separate reviewed broker
cost/carry adapter.

Protected data were materialized only through the trusted ingestion command;
untrusted feature workers and `DataVault.load()` see development partitions
only. Previously exposed 2026 historical research is still previously exposed.

## Usage

From the isolated quant-research worktree:

```bash
# Discover and materialize all available groups with physical protection.
python scripts/quant.py materialize-markets \
  --output-root data/vault/market_prices_20261015 \
  --groups forex index metals --frequencies 1h 1d \
  --start 2000-01-01 --end 2026-10-01 --include-protected
```

The new native resolutions are built with explicit invocations:

```bash
python scripts/quant.py materialize-markets \
  --output-root data/vault/market_prices_20261015 \
  --groups forex index metals --frequencies 1m \
  --start 2000-01-01 --end 2026-10-01 --include-protected

python scripts/quant.py materialize-markets \
  --output-root data/vault/market_prices_20261015 \
  --groups index --frequencies 1s \
  --start 2000-01-01 --end 2026-10-01 --include-protected
```

The command is **resumable** with immutable per-month (or daily for 1s) source hashes and
receipts. An orphaned output created by a crash before receipt publication is
rejected pending explicit reconciliation, not automatically trusted. The
builder never alters original `ml4t-data` stores.

A safe interactive read:

```python
from src.data_vault import DataVault

vault = DataVault("data/vault/market_prices_20261015/forex_1h")
eurusd = vault.load(start="2024-01-01", end="2026-10-01",
                    symbols=["EURUSD"])
assert eurusd["timestamp"].max().year <= 2025
assert not any("/protected/" in path for path in vault.opened_files)
```

A client wishing to use index + FX jointly must construct an explicit
multi-source specification (including different quote, session and cost
semantics) rather than assuming the instruments are interchangeable.
