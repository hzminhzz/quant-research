# Research Lesson: Intraday Breakout Order Execution & Regime Sensitivity

**Date**: 2026-10-07  
**Case Study**: Peter's Systemic Intraday Volatility Breakout (0.4 * ATR(5))  
**Applies to**: Intraday breakout strategies, stop-order simulation, and regime conditioning across all asset classes.

---

## 1. The Core Execution Error: Market Orders vs. Stop Orders

### The Mistake
When implementing a threshold breakout rule:
```python
# WRONG: Post-hoc condition check submitting a market order
if bar["high"] >= long_trigger:
    broker.buy(symbol, shares=shares)  # Submits a market order!
```
In event-driven backtesting, `broker.buy()` places a market order that fills at the **next bar's open** or the **current bar's close**. On fast 1-minute bars:
1. The price has already surged past the breakout barrier by the time the bar closes.
2. The backtest buys at the top of the bar rather than at the trigger level.
3. When stopping out at the open, checking `if bar["low"] <= stop_loss` and calling `broker.close_position()` sells at the bottom of the bar below the open.
4. **Result**: An artificial 5–15 bps slippage penalty on every single trade, completely destroying positive expectancy (-21.34% net return).

### The Correct Implementation
In live trading and in reference software (RealTest, TradeStation), breakout systems use **exchange-native Stop Orders**:
```python
# CORRECT: Native Stop Order filling at the exact trigger price
broker.submit_order(
    asset=symbol,
    quantity=shares,
    side=OrderSide.BUY,
    order_type=OrderType.STOP,
    stop_price=long_trigger,
)
```
When price touches `long_trigger`, the engine fills the order **at `long_trigger`** (plus actual modeled execution slippage, e.g. 0.5 bps).

---

## 2. Regime Sampling Bias: Do Not Evaluate Momentum in a Low-Vol Vacuum

### The Mistake
Evaluating an intraday breakout strategy exclusively on a recent quiet period (e.g., January 2024 to June 2025).
- Low-volatility environments (VIX 12–15) produce narrow opening ranges ($0.4 \times \text{ATR}$ is small).
- Morning noise triggers false breakouts that immediately mean-revert back to the open, hitting stops.
- This creates a **false negative rejection** of a valid strategy.

### The Correction
Always evaluate strategies across full multi-year cycles covering different macro volatility regimes:
- **High Volatility (Expansion / Crash)**: 2020 (+35.07% net return, PF = 1.418), 2022 (+9.72% net return, PF = 1.106).
- **Low Volatility (Chop / Grinding Bull)**: 2019 (-7.09%), 2024 (+10.21%).
- **Full 2018–2024 Evaluation**: **6 out of 7 years profitable**, +145.4% cumulative return on ES/NQ alone.

---

## 3. Mandatory Checklist for Future Sessions

- [ ] **Order Type Verification**: Does the strategy use touch/barrier triggers? If so, use `OrderType.STOP` with `stop_price`, NEVER delayed market orders after `bar['high'] >= trigger`.
- [ ] **EOD Session Invariant**: Always ensure `is_session_end` identifies the final bar of the session (`timestamp == timestamp.max().over(['symbol', 'date'])`), preventing accidental overnight holds.
- [ ] **Multi-Regime Verification**: Never reject a momentum/breakout strategy based on a single low-volatility period. Test across at least 3 distinct volatility regimes (expansion, contraction, trend).
