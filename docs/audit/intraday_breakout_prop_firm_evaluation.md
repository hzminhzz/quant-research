# Quantitative Audit & Decision Memo: Intraday Volatility Breakout

**Strategy Name**: Peter's Intraday Volatility Breakout (0.40 * ATR(5))  
**Date**: 2026-10-07  
**Evaluation Scope**: 2018–2026 (9 Calendar Years, 4,392,174 1-minute bars, 7,826 trades)  
**Instruments Tested**: `ES`, `NQ`, `US30`, `CL`, `XAUUSD`, `DAX`, `BTC`  
**Final Decision**: **REJECTED / NOT APPROVED FOR PROP FIRM CHALLENGE DEPLOYMENT**  

---

## 1. Executive Decision Summary

The strategy demonstrates positive long-term alpha in personal compounding accounts (+117% to +166% cumulative return over 2018–2026), but is **fundamentally unsuitable for prop firm challenge rules (FTMO, Topstep, Apex, FundedNext)**. 

The strategy's drawdown profile directly violates hard evaluation limits:
- **Max Overall Drawdown**: Reached **16.5% to 39.6%** during market consolidation years (2022, 2024, 2025). Any drawdown exceeding 8.0%–10.0% results in immediate account liquidation.
- **Max Daily Loss**: Multi-asset exposure across 7 assets at 0.33% risk per trade produces an unhedged daily risk cap of **4.62%**, directly threatening the 4.0%–5.0% maximum daily loss circuit breaker.

---

## 2. Key Empirical Results (2018–2026)

| Metric | Multi-Asset Basket (6 Assets) | With Bitcoin Futures (7 Assets) | Spot Gold Standalone | Prop Firm Tolerance Limit | Breach Status |
|---|:---:|:---:|:---:|:---:|:---:|
| **Cumulative Return** | **+166.21%** | **+117.13%** | **+37.84%** | N/A | Pass (Long-term) |
| **Max Trailing Drawdown** | **20.05%** | **39.66%** | **10.82%** | **8.0% – 10.0%** | **CRITICAL BREACH** |
| **Profit Factor** | 1.095 | 1.042 | 1.118 | $\ge 1.30$ | Marginal |
| **Win Rate** | 42.1% | 41.8% | 40.5% | $\ge 50.0\%$ | Low Win-Rate Drag |
| **Worst Single Year** | -4.08% (2023) | -25.14% (2025) | -5.70% (2018) | Max -5% Daily | Severe Loss Run |
| **Profitable Years** | 5 of 7 (71.4%) | 5 of 9 (55.6%) | 5 of 9 (55.6%) | High Consistency | Cyclical |

---

## 3. Four Fatal Flaws Under Prop Firm Constraints

1. **Correlation Stacking**:
   US equity indices (`ES`, `NQ`, `US30`) share a 90%+ correlation. On false breakout mornings, all three trigger simultaneously and stop out at the open, generating coordinated losses of ~2.0% within a single session.
2. **Wide Fixed Stop (0.4 * ATR at Open)**:
   Taking a full $-0.4 \times \text{ATR}$ loss when price retraces to the open is viable for a personal account with a 30% drawdown budget, but too volatile for an 8% trailing maximum loss constraint.
3. **Absence of Midday Profit Locking**:
   Intraday runs of $+1.0 \times \text{ATR}$ often mean-revert by late afternoon in low-volatility regimes. Letting open profits retrace back to the open stop-loss creates high equity volatility.
4. **Regime Cyclicality**:
   The system generates the majority of its alpha in volatility expansion regimes (2018, 2020, 2021). During extended consolidation regimes (2022, 2024, 2025), drawdowns persist for months.

---

## 4. Archival and Audit Ledger

- Primary 7-Year Multi-Asset Audit: `run_log/peter_6asset_7year_backtest_result.json`
- 7-Asset with Bitcoin Audit: `run_log/peter_7asset_with_btc_backtest_result.json`
- Advanced ML4T Phases 4–7 Audit: `run_log/advanced_validation/`
- Execution Lessons Recorded: `docs/lessons/01_breakout_execution_and_regime_testing.md` and `AGENTS.md` (Section 8, Rules 5 & 6)
