# Standing research market policy: CFD and perpetual targets

**Effective for all new research sessions.** This policy defines the user's intended
execution markets. It does not rewrite frozen research sessions or relax the
source-integrity checks in `ResearchContractV1` and `RunPermitV1`.

## Target markets and preferred research sources

- **Execution scope:** Broker CFDs (indices, commodities and FX) and crypto
  perpetual swaps. CME futures are research references, **not required
  execution targets**.
- **Source preference:** Inspect the canonical `ml4t-data` catalog first.
  Prefer Dukascopy CFD quotes for price-based index/commodity/FX research and
  the appropriate spot/perpetual venue feed for crypto. Qualify coverage,
  timestamps, source identity, and price and volume semantics before use.
- **Prior work:** Search frozen sessions, trial ledgers and reports first.
  Existing negative results and observed evaluation periods remain observed.

## Adaptation rule for a strategy specified on futures

When a paper, PDF or strategy describes CME NQ/ES/GC/NKD or another futures
contract, and suitable CFD data exist:

1. Preserve the author's original instrument, rules and empirical claims as
   **source references**, not the executable research specification.
2. Register a **new, explicitly named CFD adaptation** before freezing a new
   session. Declare the actual broker, instrument, source symbol, canonical
   catalog key, `product_class: cfd`, and `role: price_proxy` where applicable.
   Bind the true volume semantics and applicable session and timezone.
3. Preserve price-based signal definitions where meaningful. Record any changed
   open/exit clock, tick/lot conversion, stop/target risk, financing, spreads,
   slippage and leverage as **adaptations**. Verify that the required entry and
   exit bars exist on the actual feed.
4. Use native ML4T feature and backtest components and normal frozen
   experiment/RunPermit verification. Report **historical CFD price research**
   separately from claims about tradable venue execution.
5. A missing CME contract, CME traded volume, roll history or CME metadata
   **alone is not a data blocker** for a separately registered, otherwise
   qualified price-based CFD adaptation. Proceed without downloading CME data.

The original futures strategy and the CFD adaptation are *different research
objects*. Do not change the identity of an existing frozen session to convert
one into the other. If a feature requires true exchange-traded volume, treat
broker quote/tick-volume VWAP as a separately named feature hypothesis; it is
not a faithful CME VWAP. A fidelity-dependent candidate can be marked
`SPEC_INCOMPLETE` or `DATA_UNAVAILABLE` while independent candidates proceed.

## Rejection and research authority

Continue to **block the affected trial** for misidentified sources, missing
time-critical price bars, unverified timestamps, unacceptable gaps, causal
leakage, fabricated contract costs/multipliers, or false execution/volume
claims. Do not bypass the strict `ResearchContractV1` or `RunPermitV1`
source matching. No historical proxy test authorizes live trading.

For perpetuals, declare the actual venue and settlement, fees, funding, and
margin/liquidation assumptions; do not borrow CFD costs or trading hours.

The default applies to all new strategy research, including material adapted
from futures-only publications. An explicit future user decision to study
exchange-traded futures as a target market requires a separate, recorded scope
change; it cannot be inferred from a PDF mentioning CME.
