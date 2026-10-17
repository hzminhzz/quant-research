# Gemini Cycle 9 rolling VWAP pullback: MVP research decision

**REJECT** — BTC net PnL negative; BTC trade profit factor <1.35; BTC trade win rate <53%; BTC VWAP daily-equity Sharpe does not beat SMA; BTC VWAP trade win rate does not beat SMA; ETH replication has no net profit

## Frozen research
BTCUSDT 1h 2020–2024; ETHUSDT replication, 2025+ sealed.
24h close-volume VWAP vs SMA24; 168h ROC trend +/-2%; ATR24 stop/benchmark.
Native NEXT_BAR OPEN, one 1.0x notional position, 24 full completed-bar hold.
5bps commission +2bps slippage per side (14bps modeled round trip).
Cost stress 28bps round trip. Funding excluded and unverified.

## Trial results
| Trial | Trades | Net PnL (USDT) | Win rate | PF | Daily Sharpe | Max DD |
|---|---:|---:|---:|---:|---:|---:|
| btc_vwap_development | 1206 | -76592.24 | 0.339 | 0.921 | -0.420 | -0.843 |
| btc_sma_baseline | 1169 | -60130.12 | 0.347 | 0.953 | -0.202 | -0.859 |
| btc_vwap_double_cost | 1209 | -95823.49 | 0.327 | 0.844 | -1.163 | -0.966 |
| eth_vwap_replication | 1319 | -56966.28 | 0.357 | 0.951 | 0.019 | -0.744 |

## Independent audit
All trial fills/trades/equity are from ml4t.backtest.Engine and its native broker.
Numerical feature proof uses independent scalar VWAP and TA-Lib parity.
Every native fill clock, trade-ledger reconciliation and exposure ceiling is asserted.
Gemini's hourly close*volume VWAP is a bar approximation, not actual institutional fills.
No mark-to-market funding/fee-tier/impact calibration; this blocks live conclusions.
The acceptance gate is not a protected final-test evaluation.

## Reproduce
Run data preparation only on a new experiment ID and register a new session.
Current preregistered trial results are immutable; do not rerun and overwrite them.
Review run_log/research_sessions/crypto_rolling_vwap_pullback_v1_20261015/mvp/final_decision.json.
