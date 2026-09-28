# Crypto Research Run — Large-to-Small Seesaw Lead-Lag

## Conclusion
**REJECT.** The pre-registered large-to-small negative lead-lag was statistically visible in development, but the canonical 4h tradable follower-basket rule failed OOS with net Sharpe **-0.41**, total return **-69.4%**, and max drawdown **-88.1%**. Performance was sharply unstable: 2024 Sharpe **+1.21** versus 2025 Sharpe **-2.01**. The 8h neighbor was positive overall at Sharpe **0.53**, but it was not the canonical hypothesis and remains well below the success gate.

## Source
Jia, Wu, Yan & Liu (2023), *A seesaw effect in the cryptocurrency market: Understanding the return cross predictability of cryptocurrencies*, Journal of Empirical Finance.

Source: https://ideas.repec.org/a/eee/empfin/v74y2023ics0927539823000956.html

## Hypothesis
Recent returns of the point-in-time top-five most-liquid crypto basket negatively predict the next-block return of smaller eligible Binance perpetuals.

## Pre-Registered Specification
Manifest: `run_log/crypto_research/runs/20260928-seesaw-large-to-small-leadlag-manifest.json`

Canonical horizon 4h; neighbors 2h and 8h; top five leaders selected causally by lagged 30-day dollar volume; remaining eligible assets are followers; signal is the negative prior-block equal-weight leader return; trade an equal-weight directional follower basket at the current block open; base cost 3 bps one-way.

## Development Diagnostics
| Horizon | Blocks | Spearman | HAC p | Mean signed follower return |
|---|---:|---:|---:|---:|
| 2h | 13,140 | 0.0592 | 0.0021 | +0.0385% |
| 4h | 6,570 | 0.0636 | 0.0030 | +0.0732% |
| 8h | 3,285 | 0.0429 | 0.4078 | +0.0391% |

The canonical 4h development gate passed.

## OOS Results
| Horizon | Net Sharpe | Total return |
|---|---:|---:|
| 2h | 0.02 | -40.6% |
| 4h | **-0.41** | **-69.4%** |
| 8h | 0.53 | +25.8% |

Canonical 4h by year: 2024 Sharpe **+1.21**, return **+88.2%**; 2025 Sharpe **-2.01**, return **-83.3%**.

## Cost Sensitivity
Canonical 4h at 2x cost: Sharpe **-1.34**. At 3x: **-2.28**.

## Robustness
Removing BTC from the universe remained negative (Sharpe **-0.37**). Delaying execution one hour remained negative (**-0.17**). Removing strongest follower contributor COMPUSDT remained negative (**-0.45**).

## Failure Analysis
The development relation does not translate into a stable recent trading rule. The 2024/2025 sign break dominates the result. The positive 8h neighbor is retained as a trial but cannot be selected post hoc.

## Multiple-Testing Audit
Previous parameter trials: **15**. New trials: **3**. Cumulative: **18**. DSR probability **0.104**; haircut Sharpe **-0.740**; PBO N/A for three pre-registered horizons.

## Decision
**REJECT**

## Reproduction
`uv run --with scipy python3 -m scripts.run_crypto_seesaw_leadlag --data /home/quant/dev/quant/ml4t-data/data/crypto/market/perps_1h.parquet`
