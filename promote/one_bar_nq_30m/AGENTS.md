# One-bar NQ 30m: promoted B0 strategy

**Current research status: PROMOTED_FOR_FURTHER_RESEARCH.** The user selected and retained **B0 (original fixed 50-point protective stop)** as the promoted research version. It is NOT retired, superseded, or replaced by the later stop experiments.

Research promotion is distinct from live trading authorization. `approval_status: NOT_APPROVED` describes the unresolved live deployment qualification, not failure of research promotion.

## Canonical B0

- 50 completed 30-minute bar breakout, long/short stop entries, intended opposing-order cancellation, one illustrative NQ-equivalent contract, fixed nominal 50-point ($1,000) protective stop, exit at next 30-minute opening, maximum two entries per Chicago session.
- Native annual practical replay: 5,462 trades, modeled net +$166,107.92 from 2013 through July 14, 2026. The 2026 partial-year result was -$14,166.96. This is a BID-only Dukascopy CFD-proxy backtest, not verified dated CME fills.
- The promoted package's historical scripts and ledgers remain evidence for B0; do not select older superseded calculations in preference to `run_log/one_bar_practical_1m_20261012/`.

## Separate experiments: NOT B0 replacements

- Fixed-% stop: 0.3425068% of actual entry fill, one NQ-equivalent; 2026 -$18,743, worse than B0. Trial completed, not selected.
- B2 ATR/MNQ: 1.5 x ATR20 and nominal $1,000 MNQ risk sizing; 2026 -$9,704.29 but weaker overall evidence and boundary limitations. Inconclusive, not selected.
- Do not re-run these variants merely to select a historical winner. Never relabel already-observed history as fresh OOS. These trials remain in root run_log/ and docs/audit/.

## Limitations still requiring verification before live trading

- Native broker has no atomic OCO; one-minute OHLC cannot unambiguously order all fills.
- Practical annual replay records 98 delayed scheduled exits; exact same-boundary fills are not verified.
- BID-only index/CFD proxy differs from dated CME NQ bid/ask, fees, roll and margin terms.
- Independent annual resets are not a continuous multi-year broker account; no untouched OOS confirmation of B0 is available.

## Review authoritative evidence

- `docs/audit/one_bar_practical_1m_20261012.md`
- `docs/audit/one_bar_nq_percent_stop_20261012.md`
- `docs/audit/one_bar_nq_b0_b2_risk_comparison_20261012.md`
- `docs/audit/one_bar_execution_remediation_20261012.md`

**Agent instruction:** Continue research from the promoted B0 specification, preserve its identity and promotion, and keep live deployment decisions separate.
