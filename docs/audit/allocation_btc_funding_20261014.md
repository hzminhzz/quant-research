# BTC funding prerequisite audit

## Decision

**BLOCKED.** The canonical funding rows cover the strategy's active period at
eight-hour intervals, but all settlement marks are null. I attempted the
official Binance endpoint. DNS resolution failed before an HTTP response, so
the exact mark join and cashflow calculation did not run. I did not use proxy
prices.

This is a prerequisite audit for a separate `EXPLORATORY` allocation study.
It does not train an allocator, score performance, or approve paper or live
trading. The development boundary is `[2019-11-09, 2025-01-01)`. The script
stops reading fills before 2025 and does not read 2025 or 2026 funding files.

## Sources

- Strategy contract: `promote/donchian_btc/strategy.yaml`. It identifies the
  Binance USDT-margined `BTCUSDT_PERP`, uses daily UTC rebalances, and lists
  funding as unverified.
- Native source ledger:
  `run_log/independent_five_full_history_20261014/donchian-btc/`. It contains
  daily signals, fills, prices, equity, and summary records. Fill timestamps
  are UTC session opens. The summary says daily bars are session labels and
  do not define a finer decision or fill clock.
- Funding source:
  `/home/quant/dev/quant/ml4t-data/.data/store/crypto_futures_funding_BTCUSDT_PERP/`
  (read only). The script reads only partition years through 2024.
- Official Binance documentation:
  [Get Funding Rate History](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History).
  It documents inclusive `startTime` and `endTime`, ascending responses, a
  maximum `limit` of 1,000, and `markPrice` as the mark tied to the funding
  fee charge.
- Installed `ml4t-backtest` version: `0.1.7`. The installed API signatures
  were inspected with `inspect.signature` for `DataFeed`, `Engine`,
  `BacktestConfig`, and `Strategy`. This audit does not need a backtest.

## Position and settlement rules

The audit signs a buy quantity positive and a sell quantity negative. At each
funding boundary, it sums only fills with timestamps strictly before the
original timezone-aware UTC funding timestamp, including its subsecond
precision. It excludes a fill at the exact event timestamp and every later
fill. The hour slot is used only to check eight-hour cadence; it is not used
for position matching. Fill times must be sorted and unique. Duplicate-time
fills fail closed because their ordering relative to a settlement is unknown.
The input also rejects sides other than `buy` and `sell`, and rejects
nonpositive or nonfinite quantities.

The cashflow sign convention is:

```text
cashflow_usdt = -signed_position_btc * funding_mark_price_usdt * funding_rate
```

A positive cashflow is a credit. Thus, a positive rate debits a long and
credits a short. A negative rate reverses those signs. Unit tests cover all
four long/short and positive/negative rate combinations.

## Evidence

The bounded canonical input has 5,819 rows from 2019-09-10 08:00 UTC through
2024-12-31 16:00 UTC. Every row identifies `BTCUSDT`. One row at the first
timestamp has null interval metadata; all other rows identify an eight-hour
interval. Timestamps are on the `00:00`, `08:00`, or `16:00` schedule and are
contiguous at eight-hour steps. The active strategy ledger starts on
2019-11-09, after funding coverage begins. There are no missing scheduled
funding events during the active period through the development end.

All 5,819 development funding rows have `mark_price = null`. The source daily
bars and funding rates therefore do not establish exact event notional.
Using a nearby candle price would be a proxy, not the Binance settlement mark.
The event ledger records positions and rates but leaves cash settlement null.

The native ledger has daily UTC fills only, with no subsecond execution clock.
The revised audit applies strict-before to the exact stored timestamps. The
funding feed can include milliseconds after the nominal hour, so exact venue
chronology at a nominal boundary still needs exchange trade or position
records to verify it.

## Binance endpoint attempt

I attempted an unauthenticated GET to the official Binance endpoint with the
required user agent. The request covered only 2019-09-01 00:00:00.000 UTC
through 2024-12-31 23:59:59.999 UTC. It set `limit=1000`. The request failed
before HTTP response with `Temporary failure in name resolution` for
`fapi.binance.com`. Pagination could not start. No 2025 or later data was
requested or inspected.

The exact URL was:

```text
https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&startTime=1567296000000&endTime=1735689599999&limit=1000
```

The attempt time was `2026-10-14T10:53:13.541665+00:00`. The empty response
body hash was
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
The exact request URL, start/response timestamps, user agent, hash, byte count,
and error are in `run_log/allocation_prerequisites_20261014/btc/binance_provenance.json`.
The raw response body is
`run_log/allocation_prerequisites_20261014/btc/binance_raw/page_0000_error.bin`
and has zero bytes.

The script fails closed on duplicate events, timestamp-set mismatches, rate
mismatches, missing marks, or nonpositive marks. It writes
`funding_events_exact.csv` and `funding_daily_equity_effect.csv` only after a
full exact join. Neither file exists because the public endpoint was
unreachable. The previous null-mark event ledger remains intact.

Machine-readable output:

- `run_log/allocation_prerequisites_20261014/btc/reconciliation.json`
- `run_log/allocation_prerequisites_20261014/btc/funding_events.csv`
- `run_log/allocation_prerequisites_20261014/btc/binance_provenance.json`
- `run_log/allocation_prerequisites_20261014/btc/binance_raw/page_0000_error.bin`

## Skill and invariant record

- `ml4t-cost-model`, local path
  `.agents/skills/ml4t-cost-model/SKILL.md`, revision pinned by
  `docs/omp.md` to ML4T skills `f0ea01919e0c517cd9b1e014724a520facd8a742`.
  Selected because signed funding is an instrument cost. Invariant:
  funding is charged on signed notional at event time. Verified with the
  accounting function and long/short sign tests.
- `ml4t-run-backtest`, local path
  `.agents/skills/ml4t-run-backtest/SKILL.md`, same pinned revision. Selected
  to check whether the native engine was required. Invariant: use installed
  `ml4t-backtest` for any simulation. No simulation was needed, and no custom
  backtest loop was written.
- `ml4t-transaction-costs`, local path
  `.agents/skills/ml4t-transaction-costs/SKILL.md`. Selected to keep the
  funding charge separate from execution costs. Invariant: funding is an
  explicit signed position cost and cannot be replaced by a generic fee.

## Commands

```bash
.venv/bin/python scripts/allocation_btc_funding_20261014.py
.venv/bin/python -m pytest -c /dev/null -q tests/test_allocation_btc_funding_20261014.py
git diff --check
```

## Next required input

Retry this bounded public endpoint retrieval from a network that can resolve
`fapi.binance.com`. Then require exact timestamp and funding-rate matches for
every local development event before using Binance `markPrice`. Confirm the
position held before each `00:00`, `08:00`, and `16:00 UTC` settlement from
venue position history or subdaily fills. Keep the 2025-2026 allocator
evaluation unopened.
