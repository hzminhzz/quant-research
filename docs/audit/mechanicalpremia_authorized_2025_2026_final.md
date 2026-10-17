# Mechanical Premia — user-authorized 2025 full and 2026 YTD results

**Research session:** `mechanicalpremia-authorized-2025-2026-ytd-v1` (frozen before executing 2025+ results).
**Source:** https://mechanicalpremia.substack.com/p/building-a-multi-strategy-portfolio
**Explicit authorization:** User explicitly authorized consuming prior protected 2025+ final-test data.
**Outcome:** 12/12 native `ml4t.backtest.Engine` runs completed (four 1x portfolios + two preset additional cost stresses in EACH calendar period), no runtime failures.
**Dates:** 2025 UTC [2025-01-01, 2026-01-01); 2026 YTD UTC [2026-01-01, 2026-10-12). Latest common included Dukascopy file 2026-10-11. The 2026 results are NOT full-year.
**Permanently observed:** The evaluated 2025–2026 window is no longer a pristine holdout for any future strategy revision. A rule not using ML can still be overfit by repeated adjustment after these observations.
**Earlier 2013–2024 research remains frozen and unmodified.**

## Native marked-equity results at 1x assumed costs

Synthetic $100,000 *price-unit* account reset independently January 1 each period; source broker USD/EUR conversion absent. Performance is from native engine marked equity, not summation of closed trades.

| Strategy | 2025 net return | 2025 daily Sharpe | 2025 Calmar | 2025 max DD | 2025 closed / open | 2026 YTD net return | 2026 daily Sharpe | 2026 Calmar | 2026 max DD | 2026 closed / open |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| H1 breakout (US500, US100, DE30) | -2.27% | -0.48 | -0.30 | -6.04% | 167 / 0 | +2.99% | +0.62 | 1.01 | -3.08% | 105 / 0 |
| D1 mean reversion (four indices) | +6.79% | +2.14 | 3.52 | -1.55% | 11 / 0 | +3.29% | +0.76 | 1.09 | -3.13% | 12 / 2 |
| Equal-risk portfolio (50/50 D1/H1) | +2.33% | +0.89 | 1.02 | -1.83% | 178 / 0 | +2.98% | +0.91 | 1.38 | -2.26% | 117 / 2 |
| Source-weighted portfolio (76.64% D1) | +4.43% | +1.58 | 2.60 | -1.37% | 178 / 0 | +3.20% | +0.86 | 1.23 | -2.71% | 117 / 2 |

**Closed win rates:** 2025 H1 38.92%, D1 100% (11 wins), equal/source 42.70%. 2026 H1 36.19%, D1 91.67% (11 wins out of 12), equal/source 41.88%. Win rate excludes 2026 open D1 trades. High D1 win rates on very few trades are NOT dependable evidence of 90%+ expected live wins.

**2026 open positions:** D1-only and both portfolio choices (and cost-stress) have two open positions at cutoff; native return includes marked open exposure and excludes subsequent realized exit cost and overnight financing.

## Cost stress on source-weighted portfolio

The 1.0x model charges **1 bp commission + 2 bps slippage PER SIDE**. The stated 1.5x and 2x multiply both. Broker bid/ask spread, overnight financing and EURUSD FX conversion remain missing.

| Source-weighted cost | 2025 native equity return | 2025 daily Sharpe | 2026 YTD native equity return | 2026 daily Sharpe |
|---|---:|---:|---:|---:|
| 1.0x | +4.43% | 1.58 | +3.20% | 0.86 |
| 1.5x | +3.43% | 1.23 | +2.60% | 0.70 |
| 2.0x | +2.44% | 0.88 | +2.01% | 0.55 |

These figures reflect 12 native backtests: each calendar period is an independent reset and not a continuous two-year account. Do not compound to assert a single 2025-2026 CAGR or Sharpe.

## Instrument attribution and mechanism

H1 breakout 2026 YTD closed PnL by asset: US100 +2537 synthetic price units (39 trades), US500 +935 (28 trades), DE30 -487 (38 trades). 2026 H1 +2.99% is substantially better than 2025 -2.27%; observed regime dependence, not proof of executable source edge. D1 positive in both 2025 and 2026 under proxy assumptions.

Source weights beat equal-risk return in both windows, but 2026 source-weighted Sharpe (0.86) and max DD (-2.71%) are both WORSE than equal risk (0.91 and -2.26%). The original risk-diversification superiority falsifier is not satisfied in 2026. In 2025 standalone D1 had the highest return (+6.79%) and daily Sharpe (2.14) with only 11 trades.

## Input and execution audit

- Four canonical Dukascopy index-minute stores: `index_minute_ES`, `index_minute_NQ`, `index_minute_DAX`, `index_minute_EUSIDXEUR`.
- Daily partition acceptance records inspected through 2026-10-11. All included file partitions had a corresponding acceptance JSON; **short days remain common**, and accepted data does not imply every price sample is broker-executable.
- Complete 2025 source data present; 2026 data have a common upper exclusion at 2026-10-12 UTC. EU50's latest eligible raw file was 2026-10-09.
- `scripts/audit_mechanicalpremia_authorized_2025_2026.py`: all **12** summary/fill/trade/daily-equity sets verified, no out-of-period fills, no native order rejects, and all 12 final `broker.equity == broker.cash + marked positions` checks passed.
- Original indicators and source universe unchanged. Per-symbol `ml4t.engineer.compute_features` ATR, BB, EMA are used. Existing independent feature-parity checks against TA-Lib, and 13 targeted regression tests passed.
- No actual MT5 broker symbol clock, MQL5 initial-stop-on-entry equivalence, or CFD tick value/lot size is certified. The H1 entry-minute stop gap is unchanged from earlier sessions.
- No verified broker ASK price, spread, financing, currency conversion, real execution slippage. This remains a **synthetic bid-price-proxy experiment** and not live-CFD economics.

## Scientific decision

**Recent-period result: POSITIVE synthetic strategy returns, but broker-economic qualification INCONCLUSIVE. No promotion.**

2025 original source risk mix offered apparent improved Sharpe/DD vs equal risk, but did not outperform D1 standalone Sharpe. In 2026 source risk mix yielded higher raw return but worse Sharpe and worst DD vs equal-risk. Without qualified costs, stops, continuous FX-aware accounting and an unobserved future final test, **PROMOTION CANDIDATE is not justified**.

**Reproducibility:**
- New adapter: `scripts/mechanicalpremia_authorized_2025_2026_adapter.py`
- Native runner: `scripts/run_mechanicalpremia_authorized_2025_2026.py`
- Resumable job: `scripts/batch_mechanicalpremia_authorized_2025_2026.py`
- Eligibility audit: `scripts/audit_mechanicalpremia_authorized_2025_2026_data.py`
- Artifact audit: `scripts/audit_mechanicalpremia_authorized_2025_2026.py`
- Batch results: `run_log/research_sessions/mechanicalpremia-authorized-2025-2026-ytd-v1/yearly_native/`
- Complete batch log: `run_log/research_sessions/mechanicalpremia-authorized-2025-2026-ytd-v1/batch_log.jsonl` (the corrected latest terminal entry is 12 of 12).
- Frozen spec: `config/research_sessions/mechanicalpremia-authorized-2025-2026-ytd-v1.yaml`

No live orders. This work remains uncommitted; unrelated dirty work is preserved.
