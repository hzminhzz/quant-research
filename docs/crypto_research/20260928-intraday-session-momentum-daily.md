# Crypto Research Run — Intraday Session Momentum

## Conclusion
**REJECT.** The preregistered daily session-continuation rule failed across all 4/8/12-hour block lengths after realistic entry and exit costs. Canonical 8h development Sharpe was **-4.279** with **-94.7%** return. OOS was not consumed.

## Sources
- Wen, Bouri, Xu & Zhao (2022), *Intraday return predictability in the cryptocurrency markets: Momentum, reversal, or both*, DOI 10.1016/j.najef.2022.101733.
- Shen, Urquhart & Wang (2022), *Bitcoin intraday time series momentum*, DOI 10.1111/fire.12290.

## Specification
- Binance USD-M USDT perpetuals listed by 2021-12-31.
- Daily top 30 by lagged 30-day quote volume.
- Early UTC signal blocks: 4/8/12h; canonical 8h.
- Signal direction = sign of early-block return.
- Execute one hour after signal completion; hold for equal block length.
- Flat outside holding block.
- 10 bps one-way; charge both entry and exit.
- Development 2022–2023; OOS 2024–2025.

## Development
| Block | Net Sharpe | Return | Max DD |
|---|---:|---:|---:|
| 4h | -3.954 | -82.28% | -82.53% |
| **8h** | **-4.279** | **-94.74%** | **-94.85%** |
| 12h | -1.935 | -85.27% | -86.30% |

## Failure Analysis
The source documents specific intraday predictor pairs, not a universal equal-block continuation rule. This broad adaptation does not survive costs and is rejected without flipping the signal direction after seeing results.

## Multiple-Testing Audit
Three preregistered block lengths; cumulative trial count **157**.

## Decision
**REJECT**

## Reproduction
`uv run python scripts/run_crypto_intraday_session_momentum.py --root /home/quant/dev/quant/ml4t-data/.data/store/crypto_futures_ohlcv_1h_BINANCE_UM_PERP`
