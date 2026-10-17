# Mechanical Premia Yen Squeeze native adapter

## Scope

This adapter implements the frozen 20-hour source rules as an `ml4t.backtest.Strategy`. It does not run the historical 2023–2024 trial. It does not access 2025 or later market data. The existing audit, trial ledger, and reports remain unchanged.

The code uses registered `ml4t.engineer` ATR14 and Donchian20/500 features. It uses the source-compatible upper median from `audit_mechanicalpremia_yen_squeeze_native_20261014.py`. Each H1 feature becomes available at the H1 close. The adapter joins features to minute bars only when `available_at <= timestamp`.

## Execution boundary

The installed ML4T Engine supports native STOP submission, gap fills, updates, cancellation, and account accounting. The engine does not attach a protective STOP child to a pending STOP entry. Its `submit_bracket` API does not provide this pending STOP parent contract. A stop submitted from the strategy callback after an entry fill is submitted after the fill bar, leaving that bar without source-required protection.

The adapter therefore raises `UnqualifiedExecution` for source-equivalent execution. `synthetic_mode=True` enables deterministic adapter tests only. `run_native` accepts those fabricated bars and leaves all fills, cash, positions, and equity to ML4T Engine. It does not estimate broker performance.

`BrokerTerms` requires tick size and value, minimum/maximum/step lot, margin currency, point size, spread, account currency, and quote-to-account conversion. For MQL sizing, `SYMBOL_TRADE_TICK_VALUE` is already account-denominated; the adapter does not multiply that tick value by the exchange rate again. Sizing rounds down to the lot step. It rejects a minimum-lot override and rejects absent or invalid terms. No live connectivity or order path exists.

## Rules represented

- Use the last completed H1 ATR14 and the upper median of the current and prior 99 completed ATR values.
- Use the last completed H1 Donchian20 channel. Donchian500 is available as a separate source-prose comparison setting.
- Submit eligible buy and sell stops through native Broker calls. Do not submit a stop if its threshold has already crossed the current spread-adjusted proxy quote.
- Request 1-hour pending-order expiry and cancel through native Broker at the first strategy clock at or after expiry.
- Once a position is visible, submit and ratchet a native protective stop from completed-H1 ATR and bid/ask proxy marks. The adapter tracks the protective order by its own order ID. It never repurposes the source's remaining opposite entry STOP as a protective exit. If native protection is missing while the position remains open, it fails closed. This behavior is test-only because it cannot close the pending-entry protection gap.
- Do not create custom fills, equity, or PnL. Native Engine result state is the accounting source.

## Selected skills and invariants

- `ml4t-compute-features`, `.agents/skills/ml4t-compute-features/SKILL.md`: use registered features and sorted time series.
- `ml4t-lookahead-bias`, `.agents/skills/ml4t-lookahead-bias/SKILL.md`: expose H1 values only at the H1 close.
- `ml4t-run-backtest`, `.agents/skills/ml4t-run-backtest/SKILL.md`: use native Engine orders and future-bar fills.
- `ml4t-cost-model`, `.agents/skills/ml4t-cost-model/SKILL.md`: do not claim costs without instrument-specific terms.

The local feature skill describes cross-sectional grouping, but this adapter computes one symbol per feature stream. The registered features run on the sorted single-symbol H1 series. No panel-wide statistic is used.

## Verification

Run the focused tests with:

```bash
.venv/bin/pytest -q tests/test_mechanicalpremia_yen_squeeze_native_strategy_20261014.py
.venv/bin/python -m py_compile scripts/mechanicalpremia_yen_squeeze_native_strategy_20261014.py tests/test_mechanicalpremia_yen_squeeze_native_strategy_20261014.py
```

The tests cover registered feature warmup and availability, future-feature rejection, native Engine stop gap fills and equity, native stop modification, one-hour cancellation, protective-order versus opposite-entry separation, source execution rejection, and sizing term gates. Both targeted files passed together: 18 tests. Python compilation also passed. Synthetic bars are not strategy performance evidence.

## Open gates

Cross-broker execution remains unqualified. Required source broker terms, bid/ask history, account conversion, and CADJPY are not supplied by this adapter. Native parent/child pending STOP protection is also unavailable in the installed Engine API. The frozen historical backtest remains blocked and no economic conclusion follows from these unit tests.
