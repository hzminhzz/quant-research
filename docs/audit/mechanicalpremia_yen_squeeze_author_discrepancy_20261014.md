# Yen Squeeze — published MT5 performance versus native ML4T proxy

Date: 2026-10-14. **Read-only forensic comparison.** No re-run, no new trial, no protected holdout access, no deployment.

## Source
- Mechanical Risk Premia, 2026-09-16: https://mechanicalpremia.substack.com/p/trading-the-squeeze-a-multi-currency
- Author reports 1,423 trades (984 long, 439 short), win rate 39.21%, PF 1.35, avg win $109.55, avg loss -$52.39, net +$15,810.60, equity max DD 14.26%. **Self-reported, trade-level log/broker/test dates not supplied**.
- Prose says 500-hour breakout; embedded MQL5 code has default `input int lookback_bars = 20`. Do not presume which generated the public performance.
- EA uses `iATR(symbol, PERIOD_H1, 14)`, high/low of previous completed H1 bars, 1-hour pending stop orders, 1% `ACCOUNT_BALANCE` sizing from actual tick values/lots, SL 2x ATR attached to entry, 60-second `PositionModify` trailing (bid/ask).

## Verified local result
- Original three-pair **2023-01-01 through 2024-12-31** frozen session: `mechanicalpremia-yen-squeeze-proxy-20261014-v3`.
- Frozen baseline `PORTFOLIO-20-2PIP`, native ML4T Engine: 1,422 trade rows (1,416 closed + 6 partial), 785 long and 637 short rows; closed 502 wins/914 nonwins (35.45%). Avg win $95.67; avg nonwin -$60.90. Native trade PnL -$7,503.03; 2-pip fixed all-in proxy slippage costs $6,124.81. Accounting add-back -$1,378.22, **not** a zero-cost counterfactual because cost changes sizing/path. Long PnL -$2,572.44, short PnL -$4,930.59.
- Native 500h/2pip: 264 closed, -$2,718.17. Both windows negative at 4/6pip.
- The similar 1,423/1,422 counts are **not** a match of timestamps, direction, or fills. Our long/short mix (55.2/44.8%) sharply differs from published 69.1/30.9%; no common sample dates provided.

## High-priority source/feature mismatch found AFTER frozen trial
- Installed `ml4t.engineer.features.volatility.atr.atr_numba` uses Wilder's recursive ATR smoothing: (13*previous_atr+TR)/14.
- MetaQuotes' shipped/example MT5 `ATR.mq5` uses rolling simple mean TR, recurrence: previous_atr+(TR_today-TR_14_bars_ago)/14.
- Evidence: MetaQuotes code in https://github.com/zephyrrr/MLEA/blob/master/MQL5/Indicators/Examples/ATR.mq5 lines 549-558 and an MQL5 source excerpt https://www.mql5.com/en/forum/291190 ; installed Python source `.venv/lib/python3.14/site-packages/ml4t/engineer/features/volatility/atr.py` lines 62-130.
- Author's EA calls standard `iATR`; numeric parity of that specific installed MT5 indicator with the example implementation is **NOT YET** tested on identical bars, but this is a directly supported algorithmic discrepancy.
- ATR affects the strict low-ATR median gate, 2*ATR initial stop, trade quantity, and trailing stop: potentially different entries/sides and exits even when both are called ATR14. Previous native "feature parity passed" was **causal availability**, NOT iATR reference numerical parity. Do not continue claiming feature *source* parity.

## Other verified divergences
- Native proxy `Strategy.on_data` submits protective STOP **after** detecting entry; author attaches an SL to pending MT5 entry. Our original logs counted 1,417 unprotected entry-minute bars and 29 that breached their stop. Effect on PnL not yet causally decomposed.
- Native `ExecutionMode.NEXT_BAR` on 1m data, `StopFillMode.NEXT_BAR_OPEN`, artificial quote half-spread for validity checks, synthetic adverse fixed per-fill slippage, fixed 150 JPY/USD numeraire; MQL runs on broker bid/ask with timer and attached stop. The local data lacks actual spread, swap and lot-size/broker metadata.
- Native sizes on `broker.get_account_value()` (equity); source sizes `AccountInfoDouble(ACCOUNT_BALANCE)`. This may affect later positions.
- Native 11 rejected entries due to buying power in baseline, 4 same-minute opposite STOP fill groups. MT5 broker/netting/hedging behavior is unverified.
- Frozen executable wrapper/driver fingerprints changed after freezing; full intrabar cash/position/order lifecycle not retained. Do not certify exact frozen-code execution reproduction.
- **Historical window is an unknown**: the author provides neither tester dates nor broker/tester settings, while local 2023-24 is fixed. This alone prevents a matched performance comparison.

## Research conclusion
Current evidence rejects the **recorded 2023-24 broker-neutral ML4T proxy under its frozen criteria**, not the unspecified MT5 test in the article. It is scientifically invalid to claim the author's strategy fails or is disproven, or conversely that his published profits are independently verified.

## Next decisive test (future separate preregistered parity session)
1. Reproduce original MT5 ATR14 values on a small identical H1 bar fixture. Use native ml4t-engineer registered features or a certified tested composition/extension to implement the MT5 recurrence; do not handroll unrelated indicators.
2. Compare decision-level rows (ATR14, median, channel, buy/sell pending price, H1 clock) before any new PnL test. Freeze the test definition first.
3. Verify native engine STOP/attached protective-stop behavior, earlier intra-minute fills, bid/ask, 1% BALANCE sizing, account conversion, source margin/netting and timer semantics. Explicitly disclose unsupported parity.
4. Obtain author's MT5 tester dates, broker symbol specifications, tested lookback and raw trade export; without them, author PnL cannot be matched.
5. Any revised simulation is a NEW development trial using eligible development-only data, not a rerun/reinterpretation of the frozen v3 results; keep 2025+ holdout closed.
