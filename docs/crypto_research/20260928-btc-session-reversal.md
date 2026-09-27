# Crypto Research Run — BTC 12h Same-Session Reversal

## Conclusion

**REJECT.** The source-selected BTC Reversal/Reversal rule with an 08:00 UTC daytime boundary reproduced positive net performance during 2025 (Sharpe **0.92**, +37.8%), but failed decisively in the pre-registered 2026 forward extension: base-cost net Sharpe **-1.76**, total return **-47.4%**, and maximum drawdown **-52.6%**. The 2026 gross Sharpe was already **-1.23**, so transaction costs are not the primary explanation. The 07:00 neighbor also failed, while 09:00 was roughly flat before costs and negative after costs. This is evidence against a stable, persistent same-session reversal edge under the tested specification.

## Source

Primary source:

- Zhefan Wu and Eugene Pinsky, *On the Performance of Lagged Momentum and Reversal Strategies Across Daytime and Overnight Sessions in Bitcoin and Ethereum Cryptocurrencies*, Journal of Risk and Financial Management 19(9):692, September 2026.
- DOI: 10.3390/jrfm19090692
- https://www.mdpi.com/1911-8074/19/9/692

The source tests lagged momentum/reversal rules across complementary daytime/nighttime sessions. The canonical BTC configuration tested here uses a daytime boundary of 08:00 UTC and reverses the sign of the previous realization of the same session type. The paper itself notes sensitivity to session boundaries, which motivated the pre-registered 07:00/08:00/09:00 robustness check.

Candidate screening also considered intraday time-series momentum and volume-conditioned momentum work, but the Wu-Pinsky rule was chosen because it is exact, simple, falsifiable with the available 5-minute OHLCV, and does not require order-book, funding, or cross-sectional data.

## Hypothesis

BTC exhibits negative same-session serial dependence across complementary 12-hour sessions. If a daytime session was positive, the next daytime session should be short; if negative, long. The night session is treated independently with the same lag-one reversal rule.

Possible mechanism: short-horizon overreaction plus recurring time-of-day liquidity/participant composition.

## Pre-Registered Specification

The manifest was committed **before observing market results** at commit `2c735be6d2ed8f89c62c9aa28e5dd4c89421b597`.

| Item | Fixed specification |
|---|---|
| Canonical cutoff | 08:00 UTC |
| Day session | 08:00–20:00 UTC |
| Night session | 20:00–08:00 UTC |
| Signal | `position = -sign(previous same-session return)` |
| Execution | Position fixed before the 12h session from already-observed same-session return |
| Leverage | 1.0x |
| Exploration window | 2025-01-01 through 2026-09-21 |
| 2025 role | replication/stability subperiod |
| 2026 role | forward extension; primary evaluation |
| Base friction | 3 bps per unit turnover |
| Cost stress | 1x / 2x / 3x |
| Neighboring cutoffs | 07:00 and 09:00 |
| Planned strategy variants | 3 |
| Sealed confirmation start | 2026-09-22 00:00 UTC |

Kill criteria included non-positive 2026 net Sharpe, non-positive 2026 return, or failure at 2x base friction. All three rejection conditions were triggered.

## Data

Dataset: `BTCUSD_5m_2022_2026.parquet`, 5-minute UTC OHLCV.

Data fingerprint:

`47078373d6354f5aa45c67ce9066572175162c0efc357d92d96d6ce97fb399ec`

The selected continuous window contains **181,152** rows from 2025-01-01 00:00 UTC through 2026-09-21 23:55 UTC. Validation found zero duplicate timestamps, no nulls, no OHLC consistency failures, no negative volume, and no non-5-minute gaps inside the selected window.

The source dataset contains known month-scale gaps in July and December 2024. Those periods were deliberately excluded rather than imputed. No values at or after the sealed boundary of 2026-09-22 were read.

## Methodology

Input timestamps are bar-open timestamps. Session endpoint prices use the close of the 5-minute bar ending exactly at each UTC boundary. Each session return spans exactly 12 hours.

The trading position for a session is based only on the previous realization of the **same session type**. There is no fitted threshold, scaler, model, or full-sample preprocessing.

Friction is charged on absolute position change. At base cost, a flat-to-long/short transition costs 3 bps; a direct +1 to -1 flip costs 6 bps. Funding is not modeled because the source is spot-like and the OHLCV file has no point-in-time funding history. Market impact is not modeled under a small-capacity assumption. These omissions make the test more favorable to the strategy, not less.

Daily portfolio returns compound the two 12-hour session returns. Sharpe is annualized from daily returns using a 365-day crypto calendar.

## Results

### Canonical 08:00 UTC rule

| Period | Gross Sharpe | Net Sharpe | Net return | Max DD | Sortino | Profit factor | Win rate |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2025 | 1.41 | **0.92** | +37.8% | -30.2% | 1.49 | 1.14 | 49.9% |
| 2026 forward extension | **-1.23** | **-1.76** | **-47.4%** | **-52.6%** | -2.59 | 0.78 | 45.5% |

The full 2025–2026 canonical run generated 669 position-change events and 1,337 units of turnover.

### Cost sensitivity — 2026 canonical rule

| Cost scenario | Net Sharpe | Net return | Max DD |
|---|---:|---:|---:|
| 1x base | **-1.76** | -47.4% | -52.6% |
| 2x base | **-2.29** | -55.8% | -59.3% |
| 3x base | **-2.82** | -62.9% | -65.1% |

### Benchmark

BTC buy-and-hold over the same 2026 window returned approximately **-2.5%**, with Sharpe **0.16** and max drawdown **-39.5%**. The tested reversal rule therefore materially underperformed passive BTC during the forward extension.

## Robustness

### Boundary sensitivity

| Day start | 2026 gross Sharpe | 2026 net Sharpe | 2026 net return |
|---|---:|---:|---:|
| 07:00 UTC | -0.42 | **-0.92** | -31.2% |
| 08:00 UTC | -1.23 | **-1.76** | -47.4% |
| 09:00 UTC | +0.59 | **+0.05** | -4.6% |

There is no stable positive plateau. The neighboring 09:00 cutoff is economically flat after base friction and becomes negative as costs rise.

Removing the strongest 2026 month (April) makes the canonical result worse: Sharpe **-2.40**, return **-53.4%**, max drawdown **-57.9%**. The rejection is therefore not caused by one isolated bad month offsetting an otherwise strong year.

## Failure Analysis

The strongest evidence is temporal instability. The exact 08:00 rule is profitable during 2025 but reverses sign in 2026, including **before costs**. This is consistent with a regime-dependent or sample-specific session effect rather than a durable behavioral premium.

Transaction costs amplify the loss but do not create it. Boundary sensitivity is also substantial: shifting the split by one hour changes the 2026 gross result materially, yet none of the pre-registered neighbors produces a convincing net edge.

Because the test is already decisively negative, adding funding, spread variation, or impact would not rescue the hypothesis and was not used to search for a better-looking variant.

## Multiple-Testing Audit

- Previous crypto-registry strategy trials: **0**
- New pre-registered strategy-parameter trials: **3** (07:00, 08:00, 09:00)
- Cost scenarios evaluated per trial: **3**
- Total strategy-cost evaluations retained: **9**
- DSR probability for the canonical 2026 Sharpe against the three base-cost cutoff trials: **0.0075**
- Haircut Sharpe: **-2.39**
- PBO: **N/A** — three fixed neighboring variants are insufficient for a meaningful CPCV winner-selection PBO analysis, and no variant winner is being promoted.

The result is a rejection, so the distinction between three strategy trials and nine cost-scenario evaluations does not create a favorable-selection claim.

## Decision

**REJECT**

The 08:00 UTC same-session reversal hypothesis does not survive the 2026 forward extension, realistic friction, neighboring cutoff checks, or strongest-month removal.

## Reproduction

Pre-registration:

`run_log/crypto_research/runs/20260928-btc-session-reversal-manifest.json`

Runner:

`scripts/run_crypto_session_reversal.py`

Command:

`PYTHONPATH=. uv run --with polars --with numpy --with scipy python scripts/run_crypto_session_reversal.py --data /home/quant/dev/quant/quant-research/data/processed/BTCUSD_5m_2022_2026.parquet`

Focused test:

`uv run --with polars --with numpy --with scipy --with pytest --with pyyaml pytest -q tests/test_crypto_session_reversal.py`

## Provenance

- Repository starting branch SHA: `769c8c993a21bc1f1d9a7abfc73b1b32aea7c86f`
- Pre-registration commit: `2c735be6d2ed8f89c62c9aa28e5dd4c89421b597`
- Data SHA256: `47078373d6354f5aa45c67ce9066572175162c0efc357d92d96d6ce97fb399ec`
- Manifest SHA256: `2afa928606f26c31399f6d7605eb26398e3947906a8ff847cb8e07a67b2d8340`
- Runner SHA256: `b0d6bac8887a61b04307045feb3db7f6ea091067d0060deb95a1e0fb48dbe656`
- Strategy fingerprint: `5c0fe081b71322c375bd14d615efea849ebf6386d30afccddb7db696a53cb08f`

The final evidence commit SHA is recorded in the registry after results are committed.
