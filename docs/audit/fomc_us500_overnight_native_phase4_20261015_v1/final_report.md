# FOMC overnight: native ML4T Phase 4 exploratory result

**Research decision: REJECT.**

**This trial is post-Phase-3 exploratory**, not unseen OOS or historical Hyperliquid performance.
Frozen 53 paired schedules (2018–2024), 16:05 decision/16:06 next-open entry, 09:35 decision/09:36 next-open exit. No stops or signal optimization.
Fractional linear synthetic index units; 3x equity primary, 10bps hypothetical roundtrip friction, 20bps stress, leverage 1x/5x and zero-cost attribution.
**No real funding, quotes, dividends, liquidation or venue impact are modeled.**
## Trial metrics

| Native trial | Closed | Net PnL | PF | Win | Daily Sharpe | MaxDD | Annualized return |
|---|---:|---:|---:|---:|---:|---:|---:|
| fomc_primary_3x_10bps | 53 | 12191.02 | 1.469 | 0.396 | 0.393 | -0.086 | 0.017 |
| ordinary_baseline_3x_10bps | 53 | 6287.88 | 1.172 | 0.509 | 0.204 | -0.186 | 0.009 |
| fomc_3x_20bps_cost_stress | 53 | -4306.53 | 0.872 | 0.358 | -0.119 | -0.105 | -0.007 |
| fomc_1x_10bps | 53 | 4097.30 | 1.488 | 0.396 | 0.395 | -0.029 | 0.006 |
| fomc_5x_10bps | 53 | 20051.66 | 1.451 | 0.396 | 0.391 | -0.142 | 0.028 |
| fomc_3x_zero_cost_diagnostic | 53 | 31470.16 | 2.654 | 0.585 | 0.888 | -0.069 | 0.042 |

## Frozen acceptance evaluation

- Primary daily-equity Sharpe <0.50
- Double friction 20bps net PnL <=0

## Verification
- All PnL, trades, fills, prices, equity and cash originate in native ml4t-backtest.Engine/broker.
- Fills match the exact next-minute timestamp and native source bar OPEN.
- Closed trade net sum and native equity are independently reconciled on all trials.
- Equity risk metrics use calendar daily curve incl. flat days and ml4t.diagnostic PortfolioAnalysis.
- Original Phase3 53-event gross proxy results remain untouched; 2025+ protected holdout unread.
- Conditional trial success cannot establish historical Hyperliquid execution or positive net funding-adjusted alpha.
