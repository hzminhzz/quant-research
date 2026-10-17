# Plain cross-sectional Binance funding factor MVP — terminal audit

**Session:** `crypto_xs_plain_funding_mvp_20261015_v1`  
**Mode:** MVP Research  
**Classification:** EXPLORATORY / NOT APPROVED  
**Terminal decision:** **INCONCLUSIVE**  
**Terminal stage:** `EXECUTION_DATA_GATE`

## Outcome

The plain funding factor passed the frozen Stage-1 signal gate on 2020-06-01 through 2023-12-31 development data. The mission did not reach the native portfolio backtest because the frozen requirement for exact historical funding cashflows could not be satisfied.

This is not an economic rejection of the factor. It is a data/execution-accounting blocker.

## Frozen research contract

The signal is only trailing-24h realized Binance USD-M funding:

`prediction = -cum_funding_24h`

No momentum, exhaustion filter, ML model, price filter, stop, or parameter search is used.

At each 48h decision:
- require 720 contiguous completed hourly bars;
- require at least one actual funding event in the trailing 24h;
- rank by trailing-720h `close*base_volume`;
- target top 40;
- use all eligible contracts when breadth is 20-39;
- stay flat below 20;
- diagnostic label is 48h next-open return.

The prospective portfolio rule is five lowest-funding contracts long at +10% each and five highest-funding contracts short at -10% each. Base execution friction is 5 bps commission + 4 bps slippage per side. The stress arm doubles both.

All 2024+ observations remain sealed.

## Verified Stage-1 factor evidence

| Metric | Result | Frozen gate |
|---|---:|---:|
| Mean 48h Spearman IC | **0.038819** | >= 0.020 |
| HAC t-stat, lag 1 | **5.0362** | >= 2.0 |
| HAC p-value | **6.15e-07** | diagnostic |
| IC IR | **0.1984** | diagnostic |
| First chronological half mean IC | **0.061160** | > 0 |
| Second chronological half mean IC | **0.016478** | > 0 |
| Eligible 48h cycles | **654** | >= 150 |
| Minimum universe breadth | **23** | >= 20 |
| Median universe breadth | **40** | diagnostic |
| Maximum universe breadth | **40** | diagnostic |

An independent SciPy/statsmodels recalculation reproduced:
- mean IC: `0.038819223701307505`;
- HAC SE: `0.0077080309284728536`;
- HAC t-stat: `5.036204973946379`;
- first-half mean IC: `0.06116026309940029`;
- second-half mean IC: `0.016478184303214703`.

The latest diagnostic decision is 2023-12-29 00:00 UTC. The latest label exit is 2023-12-31 01:00 UTC. No 2024 observation is needed.

## Data-contract repair

The generic research-session auditor previously treated valid cross-sectional panel timestamps as duplicates and rejected panels above one million rows.

This mission added explicit `panel: true` dataset semantics:
- required `symbol` entity column;
- per-symbol timestamp ordering;
- per-symbol timestamp uniqueness;
- lazy panel validation above the single-series one-million-row cap;
- the existing 100 MB file bound remains enforced.

Regression verification:
- full `tests/test_research_session.py` + CLI: **68 passed**;
- focused plain-funding and panel tests: **6 passed**.

The frozen session audit is now **PASS** for all eight bounded price/funding panel files, including the 1,276,518-row 2023 price panel.

## Exact funding-cashflow gate

The portfolio trial required actual Binance funding cashflows:

`cashflow = -quantity * settlement_mark_price * funding_rate`

The native ML4T broker cash ledger can represent this cashflow directly. A synthetic native-engine test verified the broker cash mutation, next-bar fills, flattening, and final equity reconciliation.

However, historical Binance archive funding rows have nullable `mark_price`. The existing `ml4t-data` official Binance REST provider was therefore used for the frozen execution-data qualification.

The first funding event that would affect a selected position was:

- symbol: **DASHUSDT**
- event: **2020-06-01 08:00:00.001 UTC**
- canonical funding rate: **0.0001**
- official Binance funding rate: matched
- official Binance `markPrice`: **null**

Provider:
- `/home/quant/dev/quant/ml4t-data/scripts/fetch_binance_perp_funding.py`
- SHA256: `28be6214f3c5a5a7acc5a7f0d3f6ce16aaf7d32a2740e2fcd6364900258af42d`
- endpoint: `https://fapi.binance.com/fapi/v1/fundingRate`

The full prospective basket would require **39,971** held-position funding events. Because even one required event lacks exact settlement mark price, the exact historical cashflow contract fails.

The frozen specification explicitly prohibited replacing a missing exact mark with OHLCV or a mark-kline proxy. Therefore the native portfolio trial was not executed.

## Interpretation

**Verified:** The simple funding rank contains strong development-sample cross-sectional price information under the frozen causal panel construction.

**Verified:** The earlier momentum/exhaustion overlay was unnecessary for signal strength; this plain funding factor is materially stronger in the same broad research domain.

**Unknown:** Whether a 5-long/5-short portfolio is profitable after actual funding cashflows and 18/36 bps execution friction, because exact historical settlement marks are unavailable for part of the development period.

**Research-control note:** The funding-only relationship was already observed indirectly in the prior exhaustion study. This MVP is development evidence, not independent validation.

## Decision

**INCONCLUSIVE.**

Do not reject the funding factor. Do not call it validated. Do not run a proxy-funded backtest under this frozen session.

The scientifically clean next step is a separate Validation-era experiment on a period where Binance exposes exact `markPrice` for all required funding events, while preserving 2026 as the protected final test.
