# Crypto Research Run — Liquidity-conditioned daily sign flip

## Conclusion

**REJECT.** The source-inspired hypothesis that the most-liquid contracts should exhibit one-day momentum while the less-liquid contracts exhibit reversal failed its preregistered development gate. The canonical 25% liquid split produced net development Sharpe **-0.622** and total return **-40.0%**. Both neighboring liquidity splits were also negative. The 2024-2025 OOS sample was therefore not consumed.

## Source

Zaremba et al., *Up or down? Short-term reversal, momentum, and liquidity effects in cryptocurrency markets*, International Review of Financial Analysis (2021), DOI 10.1016/j.irfa.2021.101908.

## Hypothesis / Mechanism

Use prior completed UTC-day return. In the most-liquid bucket, rank in the momentum direction; in the remaining bucket, rank in the reversal direction. The mechanism is the paper's liquidity-conditioned sign flip in short-horizon return continuation.

## Pre-Registered Specification

- Data: Binance 1h USDT perpetual panel.
- Universe: point-in-time assets with at least 30 days exact hourly history and valid lagged trailing 30-day dollar volume; minimum 8 assets.
- Liquidity splits: 20%, **25% canonical**, 33%.
- Rebalance: daily 00:00 UTC at current open, using only completed prior data.
- Construction: 0.5 gross liquid-momentum sleeve and 0.5 gross less-liquid reversal sleeve; each sleeve dollar neutral.
- Base cost: 3 bps one way.
- Development: 2021-2023.
- OOS: 2024-2025, consumed only if development gate passed.

## Data

866,868 rows, 19 symbols, 2020-01-01 through 2025-12-31. No duplicate symbol/timestamp pairs or OHLC integrity failures. Two non-hourly symbol gaps were detected and eligibility required exact trailing history.

## Results

| Liquid fraction | Net Sharpe | Total return | Max DD |
|---:|---:|---:|---:|
| 20% | -0.890 | -48.6% | -57.9% |
| **25%** | **-0.622** | **-40.0%** | **-51.6%** |
| 33% | -0.451 | -32.3% | -46.0% |

The fixed development requirement was canonical Sharpe > 0.70, positive canonical return, and at least two of three liquidity splits positive. It failed decisively.

## Leakage / Execution Audit

The one-day signal uses close[t-1]/close[t-25]-1 at the 00:00 UTC decision timestamp, trailing liquidity is shifted one hour, and execution occurs at the current 00:00 open. OOS was not accessed after the development failure.

## Multiple-Testing Audit

Three preregistered liquidity splits were counted as trials, moving the cumulative crypto parameter-trial count from 42 to **45**. DSR/PBO are not applicable because the development gate failed before OOS portfolio evaluation.

## Decision

**REJECT**

## Reproduction

`uv run python -m scripts.run_crypto_liquidity_signflip --data /home/quant/dev/quant/ml4t-data/data/crypto/market/perps_1h.parquet`
