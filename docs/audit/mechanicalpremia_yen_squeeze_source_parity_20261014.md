# Source parity: Mechanical Premia Yen Squeeze (2026-10-14)

Source: https://mechanicalpremia.substack.com/p/trading-the-squeeze-a-multi-currency
Published: 2026-09-16 by Mechanical Risk Premia. Retrieved through TinyFish public-page content fetch, 2026-10-14.
Purpose: MQL5 rule audit BEFORE any performance outcomes. Source is not a claim of executable broker parity.

## Source-code facts

- Universe `USDJPY,GBPJPY,CADJPY`, H1 clock on chart symbol, 1-second `OnTimer` handler.
- **Contradiction:** prose says 500-hour breakout. Actual source defaults to `input int lookback_bars = 20;`. Frozen primary trial uses original code 20; 500 comparison is a distinct preregistered trial.
- `iATR(symbol, PERIOD_H1, 14)` computed once. At each new H1, reads 100 completed ATR values using `CopyBuffer(handle, 0, 1, 100, atr_100)` with array-as-series. `previous_atr = atr_100[0]`; filters `previous_atr < ArraySort(atr_100)[50]`, i.e. upper median of 100 values including previous ATR.
- Entries: `CopyHigh(..., 1, lookback_bars)` and corresponding low, both include last fully completed H1, exclude current forming H1. BuyStop at highest high only if above current ask. SellStop at lowest low only if below current bid. Code can submit BOTH pending orders in the same H1 because `Position_State_Checker` executes before creating either order.
- Both pending stop orders use `ORDER_TIME_SPECIFIED`, expiry `TimeCurrent()+3600`, not necessarily the wall-clock next H1 boundary. Orders are NOT programmed as OCO; opposite pending orders can coexist and are not cancelled when one fills. No per-symbol aggregate risk limit beyond a pre-order broker margin check.
- Initial stop is price at pending entry plus/minus 2.0*previous completed H1 ATR; no take-profit.
- Lot uses `AccountInfoDouble(ACCOUNT_BALANCE)`, symbol-specific tick size/value and lot step/min/max, 1% default risk. Min-lot clamp can exceed nominal target. Requires actual broker metadata and settlement conversion.
- Manager checks only once each >=60 seconds, anchored on `TimeCurrent()`. Fetches previous fully completed H1 ATR. Long stop candidate = current bid - 2*ATR; short candidate = current ask + 2*ATR. Uses `PositionModify` if ratchet improves by more than 2 * SYMBOL_POINT (or no prior stop). Never widens stops.
- `OnTick()` empty; `OnTimer` calls executor before manager.
- Missing in source: fixed venue, spread, swap/financing, historical bid/ask execution data, server timezone and FX account conversion. Report any 1m bar proxy as APPROXIMATION, not exact MT5 tick execution.

## Verification gates

1. Exact native `ml4t.engineer` ATR14 and Donchian 20/500 feature compute, with causal 100-ATR upper median equivalence. Library-only primitives; no handwritten indicator loops.
2. Native `ml4t.backtest` STOP order submission, trigger (including gap fill), expiry, simultaneous opposite pending orders, protective stop and modification. Never simulate fills in Python.
3. Native price to account cash/equity reconciliation for two JPY-quote crosses (USD base and GBP base). Without verified contract and currency conversion, label economic metrics not broker-equivalent and stop promotion.
4. Preserve the prior eight preregistered trials. Source mismatch does not authorize tuning or adding new variants.

Disposition: Source rules resolved; cross-broker execution parity remains UNCERTIFIED. The SOURCE-PARITY trial may be administratively linked as completed audit, but it is not a native reproduction result.
