# VOLT BREAK Phase 4 native execution audit (2026-10-12)

## Decision

**BLOCKED for strict native strategy backtest.** The installed `ml4t-backtest`
engine cannot enforce the frozen TP/SL behavior with atomic one-cancels-other
(OCO) exits. Both exit orders can fill during one one-minute bar. A second
fill can reverse the position. The entry minute is also unprotected when the
strategy submits its bracket after the native entry fill. I did not run a
historical strategy trial or report strategy performance.

The result is an execution-capability finding. It is not a finding about
strategy profitability. The Phase 3 negative continuation diagnostics remain
the only observed strategy outcomes. Both ATR coverage variants remain
separate. Neither is selected.

## Frozen scope and source identity

- Phase 4 specification: `config/research_sessions/volt_break_nq_phase4_20261012.yaml`.
- Trial ledger: `run_log/research_sessions/volt_break_nq_20261012/phase4_trial_ledger_20261012.json`.
- Data source: canonical Dukascopy `USATECH.IDX/USD` one-minute BID CFD proxy at
  `/home/quant/dev/quant/ml4t-data/.data/store/index_minute_NQ`.
- Allowed partitions: 2018-2025 only. 2018 is warmup. 2019-2025 is the
  retrospective development period. I did not read 2026 outcome bars.
- The 2018-2025 source slice passed **96/96** SHA256 checks against the prior
  source manifest. Its manifest SHA256 is
  `fd810bef0a390a77972d22d1cb0100e6d17f46dec437bed5abf865f39e579e75`.
- The captured check is in
  `run_log/research_sessions/volt_break_nq_20261012/phase4_source_identity_20261012.json`.
- The source is BID CFD data. Provider volume is reported in units. It is not
  dated CME NQ contract data or verified CME trade volume. The computed VWAP
  would only be a proxy VWAP.
- No real orders were submitted. The canonical data store was not modified.

The primary 1,576 complete CT-day cohort and the two prior daily session
coverage variants remain as preregistered: strict 1,300-minute minimum and
coverage sensitivity 1,000-minute minimum. The Phase 3 reports show 63 and 217
first-hit days, respectively. Phase 4 did not compare their performance.

## Installed engine and focused checks

The installed version is `ml4t-backtest 0.1.7`. The API source is in
`.venv/lib/python3.14/site-packages/ml4t/backtest`. `NEXT_BAR` processes
pending orders at the current row's open before it calls the strategy. Orders
submitted by that callback become eligible on the next feed row. `STOP_PRICE`
uses the source open if the open gaps through a stop. Otherwise, a touched stop
fills at its trigger.

The default `FillOrdering.EXIT_FIRST` processes exits before entries. It does
not order a target against its sibling stop. The strategy interface has no
fill or position callback between sibling fills. A later `on_data` callback
runs after the Engine processes all eligible orders for that row.

The native fill source checks MARKET orders at the selected execution price,
LIMIT orders against bar high/low at the limit price, and STOP orders against
bar high/low. `STOP_PRICE` applies the gap-through-at-open rule. One-minute OHLC
data has no intrabar sequence. When the target and stop both trigger, the
Engine cannot identify which order happened first.

The `Broker.submit_bracket` helper submits an independent LIMIT and STOP order.
It assigns parent identifiers. It does not link the orders as OCO orders. The
broker has no OCO group argument or fill callback that can cancel the sibling
before same-row processing.

The focused synthetic suite is
`tests/test_volt_break_phase4_execution_20261012.py`. It passed **5 tests**:

1. A signal callback on the completed 09:59 minute fills at the 10:00 open.
2. A signal first released by the 10:00 callback fills at 10:01. This is one
   minute late for the frozen same-boundary entry rule.
3. A sell stop at 95 gaps through on an open at 90 and fills at 90.
4. A bracket submitted after the 15:01 entry fill cannot act during that
   entry minute. Its first eligible row is 15:02.
5. When one bar reaches both a 105 LIMIT target and a 95 STOP, both sell orders
   fill at the same timestamp. The second order reverses the one-contract long
   into a short position.

These are synthetic Engine checks. They do not read or evaluate historical
strategy signals.

## Trial disposition

| Trial group | Disposition | Reason |
| --- | --- | --- |
| Source identity and API audit | Completed | 96/96 source hashes match; installed API inspected. |
| Synthetic Engine timing and OCO | Completed, blocking | Timing and conflicting fills reproduced in tests. |
| Strict 1,300-minute variant, zero cost | Blocked | Exact OCO and entry-minute protection are unavailable. |
| Strict 1,300-minute variant, illustrative cost | Blocked | Same execution blocker. |
| Strict 1,300-minute variant, 2x cost | Blocked | Same execution blocker. |
| Coverage 1,000-minute variant, zero cost | Blocked | Same execution blocker. |
| Coverage 1,000-minute variant, illustrative cost | Blocked | Same execution blocker. |
| Coverage 1,000-minute variant, 2x cost | Blocked | Same execution blocker. |
| Independent fill and ledger audit | Not run | No historical strategy fills exist. |

I did not estimate PnL, trade count, win rate, profit factor, expectancy,
year stability, daily equity metrics, exit attribution, ambiguity counts,
ledger reconciliation, or positions after 14:30. Reporting these values would
require inventing or accepting contradictory fills.

## Research conclusion

Phase 4 is **BLOCKED**, not VERIFIED as a strategy backtest. The exact native
execution contract required by the frozen strategy is not available in the
installed engine. The tests verify the blocker and the next-bar timing rules.
They do not support or reject the economic hypothesis.

The next decisive question is whether a native engine version or approved
execution adapter can provide atomic OCO exits and protection at the entry
fill, while keeping Engine-owned order and account ledgers. Until then, keep
both ATR variants frozen and do not claim Phase 4 strategy performance.

## Reproduction

```bash
python scripts/verify_volt_break_phase3_sources_20261012.py
.venv/bin/python -m pytest -q tests/test_volt_break_phase4_execution_20261012.py
```

Pytest output is retained in
`run_log/research_sessions/volt_break_nq_20261012/phase4_pytest_20261012.log`.
