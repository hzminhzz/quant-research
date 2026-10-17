# DAX month-end liquidity-rebound fixed-cost MVP — REJECT

**Interpretation:** purely hypothetical execution costs on Dukascopy BID-only CFD proxy. Do not treat as executable historical broker PnL.

Observed complete paired months: **73** (2018–2024, last entry anchor November 2024); missing post-event months: **0**.
Frozen Phase 3 signal decision: **PASS**.

## Base scenario (5 bps per side, 8% APR ACT/365 financing)
- Candidate mean monthly net per EUR100k: **-0.0727%**; native EUR net **-5,305.31**.
- Control mean monthly net: **-0.1844%**; native EUR net **-13,459.03**.
- Paired candidate - control: **0.1117%**; HAC(3) 95% CI **[-0.6117%, 0.8351%]**.
- Candidate win rate **49.32%**; control **39.73%**.

## Double-cost sensitivity (10 bps per side, 16% APR finance)
- Candidate mean net: **-0.2829%**; paired mean **0.1071%**.

## Native execution and scientific limits
- Actual `ml4t.backtest.Engine` order fills at the next observed 1-minute bar open; exact 09:11 and 17:11 Europe/Berlin fill assertions.
- All trade fills, fees and ACT/365 financing are reflected in the native broker cash ledger and independently reconciled.
- Bid-only series does not contain historical executable asks. Commission/slippage/financing are user-authorized fixed **assumptions**, not proven broker fees.
- No verified Dukascopy dividend cash adjustments, price/performance index variant, lot step, contract multiplier, or source-to-live quote parity.
- No strategy tuning or test-period peeking; no live orders.
- A result `VALIDATE` supports only a separately authorized deeper validation program and does not authorize trading.

Input hashes: source 5ff928567df21757d59f6efe34145e34403669d77dabe3b1cfe485e227c2d6a4; event plan 4784aef34906b8b42ba33fa95de9ff0fb930eb6b684b9d73943f84aa09030c8e.
