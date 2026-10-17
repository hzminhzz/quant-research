# Lighter anchored volume farming A/B study — 2026-10-09

**Status: EXPLORATORY. Not approved for live Arcus deployment.**

## Research decision

The hypothesis under test is **not** market prediction or pairs convergence.
The main thesis is that a long SPY fixed-anchor DCA basket and a separate
short QQQ fixed-anchor DCA basket can generate opposing inventory turnover,
independently reset their anchors on *completed breakeven limit exits*, and
perhaps produce higher volume per drawdown than a linked SPY/QQQ hedge.

**The independent strategy works mechanically in this 1m-bar simulation.**
Its downside is material: an unfinished short can accumulate unrealized losses
despite dozens of earlier zero-loss completed cycles. We cannot select a
production strategy from these results because Lighter OHLCV lacks historical
queue position, bid/ask, aggressor direction, and actual Arcus funding/points.

## Variant definitions and what makes them different

| Variant | Model |
|---|---|
| **A** | Independent SPY-long / QQQ-short fixed-anchor grids. Each has its own $100/$50 entry clips, basket cash ledger, breakeven maker exit, cycle reset and new anchor. QQQ can reset lower after buying back shorts during a decline; SPY can reset at a new higher price after recovery. **No forced hedge.** |
| **A0** | SPY-long fixed-anchor grid alone; basket must recover to anchor and close at breakeven |
| **A1** | A0 plus QQQ-short *maker* hedge, 50% of frozen return beta |
| **A2** | As A1, at 75% of frozen return beta |
| **A3** | As A1, at 100% of frozen return beta |
| **A4** | As A3, but rolling 14-day hourly return beta updated with hourly smoothing, using only known past information |

In A, SPY and QQQ do **not** wait for each other's fills. They can complete
cycles independently. In A1-A4, the QQQ hedge only becomes an entry candidate
after a SPY fill, and the combined position must achieve **joint** projected
cash breakeven before passive exits. If the QQQ maker hedge does not fill,
the controller can remain unhedged. Hedging is *not* guaranteed.

**No dual-order self-matching or wash trading is modeled or recommended.**
All simulated fills require a price move and independently reported external
market volume, albeit without trade-side/queue verification.

## Data, chronology and point-in-time contract

- Source: Lighter SPY/USDC:USDC + QQQ/USDC:USDC perpetuals, via installed CCXT.
- Valid range: 2026-01-22 16:00 UTC through 2026-10-09 07:38 UTC.
- 373,899 UTC minute bars **per instrument**, no missing minutes after launch.
- Data source: `/home/quant/dev/quant/ml4t-data/.data/store/crypto_futures_ohlcv_1m_LIGHTER_USDC_PERP`.
- Initial beta calibration: prior sample through 2026-02-21, hourly
  SPY-on-QQQ return beta = **0.297624724**, correlation = **0.5461653**.
- Development: 2026-02-22 through 2026-07-31: **230,400 minutes**.
- Later chronological evaluation: 2026-08-01 through 2026-10-09 07:38:
  **99,819 minutes**.
- Caution: this later window was **already inspected in the prior grid
  experiment**. It is temporally later but is not pristine unseen OOS.
- Separate phases begin flat and independently initialize anchors; they are
  not a single uninterrupted portfolio running across the split.
- Code: `scripts/run_lighter_anchored_volume_ab_20261009.py`.
- Frozen config: `config/research_sessions/lighter_anchored_volume_ab_20261009.yaml`.
- The initial strategy specification preceded the A/B runs; during QA, an
  exit-price drift defect was found and fixed; **all definitive table figures
  below were rerun** after that fix. Do not treat this as independent OOS
  strategy selection.

## Common assumptions

- $1,000 initial simulated balance.
- Gross entry budget $600; SPY inventory budget $400 and QQQ $200.
  Entry cap is checked including outstanding *entry* orders.
- Signed SPY clip $100; QQQ independent clip $50.
- Four fixed price levels per basket: first maker clip **2 bps**
  away from anchor, then next at **25/50/75 bps** adverse distance.
- Exit maker limit must satisfy cycle cashflow breakeven **after accrued
  cost** and a $0.05 reserve. SPY long also must recover its fixed anchor;
  QQQ independent short must recover to or below its fixed anchor.
- Fixed anchor never moves while a cycle is active. Re-anchor only when
  that particular basket is completely flat.
- Strategy risk halt at $50 peak-to-trough drawdown or negative
  initial-equity loss, with $630 mark-value gross-emergency threshold
  to catch adverse price drift above the $600 entry budget.
- All normal orders use **native ml4t.backtest LIMIT orders** on a
  future minute bar. A quote requires at least **one tick of price
  penetration**, and enough total reported minute trading volume for the
  *whole clip*. Two volume availability assumptions were run: 100% and
  25% of reported one-minute total base volume.
- Maker fees assumed 0 bps; no maker slippage assumption. Emergency risk
  exits are market orders with **assumed** 2.25 bps taker fee plus
  2.0 bps slippage adjustment (total 4.25 bps).
- Baseline carry/funding **0**; explicit gross-notional **5 bps/day**
  positive carrying-cost sensitivity on A/A3/A4. This 5-bps/day
  rate is a hypothetical stress, NOT historical funding.
- The ML4T Engine handles fills and position/cash state. Strategy-owned
  cycle ledgers track realized cashflow, accrued carry, anchored state,
  resting orders and completed-cycle notional.
- No funding history obtainable with the installed CCXT Lighter adapter's
  historical funding API (`fetchFundingRateHistory = False`).
- This is a candle-touch proxy with limits; **not a validated
  maker-eligible volume estimate**. No actual queue depth, trade
  aggressor, post-only exchange acknowledgement or Arcus price-basis
  histories are in the OHLCV.
- The backtest is long-only SPY and short-only QQQ; it does not optimize
  pairs by beta for strategy A.
- Gross marked exposure can move above $600 before risk responses execute;
  in one stress path it triggered the $630 emergency.

## Base results — zero assumed funding, 100% of reported bar volume available

### Development (February 22 – July 31)

| Variant | Completed candidate maker volume | Completed cycles | Max drawdown USD | PnL ex. points USD | End-cycle unresolved inventory |
|---|---:|---:|---:|---:|---|
| A independent | **$8,291.54** | **42** (37 QQQ + 5 SPY) | $39.96 | **-$18.31** | QQQ short |
| A0 SPY alone | $3,003.90 | 8 | $34.49 | +$4.77 | Flat |
| A1 50% hedge | $1,380.14 | 2 | $29.12 | -$4.24 | QQQ short |
| A2 75% hedge | $1,469.50 | 2 | $26.48 | -$7.48 | QQQ short |
| A3 100% hedge | $1,558.73 | 2 | $24.09 | -$9.79 | QQQ short |
| A4 dynamic hedge | **$12,050.01** | 20 | **$19.78** | **+$7.40** | Flat |

No variant hit a risk stop in the above base development run.
Independent A's QQQ short completed many cycles and reset its QQQ
anchor from approximately **607.18** initially to **571.56**
at its latest completed cycle; long SPY remained independently managed.
The completed long SPY cycles have median holding **510 minutes**;
completed short QQQ cycles have median holding **9 minutes** but
a 95th percentile exceeding **4,600 minutes**. The independent
design has highly variable holding duration.

### Later chronological evaluation (August 1 – October 9)

| Variant | Completed candidate maker volume | Completed cycles | Max drawdown USD | PnL ex. points USD | End-cycle unresolved inventory |
|---|---:|---:|---:|---:|---|
| A independent | **$1,099.63** | 6 (2 QQQ + 4 SPY) | **$22.04** | **-$19.00** | QQQ short about 0.291 QQQ |
| A0 SPY alone | $400.08 | 2 | $0.35 | +$0.19 | Flat |
| A1 50% hedge | $429.72 | 2 | $0.35 | +$0.19 | Flat |
| A2 75% hedge | $444.68 | 2 | $0.35 | +$0.19 | Flat |
| A3 100% hedge | $459.50 | 2 | $0.35 | +$0.19 | Flat |
| A4 dynamic hedge | $492.57 | 2 | $0.35 | +$0.20 | Flat |

The independent QQQ strategy performed exactly as proposed while a downtrend
persisted *and existing short inventory could be closed*. In this later
upward-trending interval, it was left with an unfinished QQQ short,
whose marked loss overwhelmed the small profits from earlier completed
cycles. Note that **clean exit on completed baskets does not guarantee
a clean *portfolio* exit**.

### Stricter liquidity: only 25% of reported minute volume available

| Phase | Variant | Completed volume | Max DD | PnL ex. points | Stopped? |
|---|---|---:|---:|---:|---|
| Development | A independent | $5,891.93 | $50.07 | -$46.71 | Yes |
| Development | A0 solo | $1,802.08 | $35.17 | +$2.66 | No |
| Development | A1 50% | $200.27 | $29.87 | -$5.48 | No |
| Development | A2 75% | $200.27 | $27.26 | -$8.54 | No |
| Development | A3 100% | $200.27 | $24.93 | -$10.74 | No |
| Development | A4 dynamic | $4,086.19 | $24.25 | +$2.88 | No |
| Later | A independent | **$899.59** | **$0.22** | +$0.35 | No |
| Later | A0-A4 (each) | $400.08 | $0.35 | +$0.19 | No |

The stricter OOS model often prevents QQQ hedge orders from filling,
so A1-A4 collapse mechanically to SPY-only exposure. This is not evidence
that the portfolio has achieved a hedge. Equally, the smaller risk in A's
stricter OOS may be because problematic short inventory **never filled**.
The rankings therefore depend on fill assumptions.

### Hypothetical carrying cost of 5 bps/day of gross inventory

This is a **scenario** and is not the actual exchange's funding history.

| Phase | Variant | Completed volume | Max DD | PnL ex. points | Notes |
|---|---|---:|---:|---:|---|
| Development | A | $13,301.96 | $44.41 | -$28.74 | Unfinished QQQ short |
| Development | A3 | $1,558.73 | $31.86 | -$23.60 | Incomplete pair |
| Development | A4 | $1,623.13 | $30.26 | -$17.43 | Gross-value emergency halt |
| Later | A | $1,099.64 | $28.89 | -$26.19 | Unfinished QQQ short |
| Later | A3 | $459.50 | $0.36 | +$0.17 | Flat |
| Later | A4 | $492.57 | $0.35 | +$0.17 | Flat |

Carry alters quote price thresholds and *which* baskets complete, so its
effect need not be a simple constant reduction from no-carry PnL.
In the A carry-stress development run the quote-repricing frequency
increased considerably: 5,994 submitted quotes versus 261 base.
Queue-priority costs are absent from the bar-based simulator, making
such estimates especially fragile.

## Safety, modeling, and interpretation

1. All reported maker volume is **candidate** maker notional, inferred
   from OHLCV with one-tick penetration and total-volume gates. It cannot
   establish if the order would reach the book, how long it would rest,
   whether contra-side flow would fill it, or whether Arcus would count it.
2. Whole clips are all-or-none; historical partial fills are absent.
   An actual $100 order can accumulate fills across many trades, unlike
   this simplified model.
3. All six variants share the same risk and notional ceilings but are not
   equal-risk *exposure time*: A can quote both assets independently
   while B waits on SPY fills, which is intentionally part of the thesis.
4. Separate phases reset at start; a continuous live deployment might
   carry a trapped position across a phase boundary.
5. Zero maker fee does **not** mean zero economic cost. Persistent
   funding, adverse selection, basis divergence, stale marks, emergency
   market exits, opportunity cost and liquidation remain.
6. Because 1m realized volume is sparse (SPY 31.0% and QQQ 43.8%
   zero-volume minutes; median active-minute notional only ~$16 and ~$11),
   any claimed point-farming volume from touch fills is a provisional
   quantity, not independently validated. Incentive payouts are not
   included in net PnL and their award formula is not assumed.
7. User intent is *organic maker liquidity*. Do not add intentional
   wash trades, cross-self-orders or artificial volume generation.
8. **A4 is not a confirmed winner**: the strong no-carry development
   result was not repeated in the later segment and reversed under the
   carrying-cost stress.
9. The zero-loss completed-cycle constraint was mechanically audited.
   Across the final reported base and volume-sensitivity runs there were
   **zero attributed fills missing from the cycle ledger** and zero
   completed cycles with net losses above $0.005.
   In an early QA run one negative cycle was detected; the stale
   exit-limit recalibration defect was fixed and final results rerun.

## Reproducibility

```bash
cd /home/quant/dev/quant/quant-research
.venv/bin/python -m scripts.run_lighter_anchored_volume_ab_20261009 --phase development
.venv/bin/python -m scripts.run_lighter_anchored_volume_ab_20261009 --phase oos
.venv/bin/python -m scripts.run_lighter_anchored_volume_ab_20261009 --phase development --max-participation 0.25
.venv/bin/python -m scripts.run_lighter_anchored_volume_ab_20261009 --phase oos --max-participation 0.25
.venv/bin/python -m scripts.run_lighter_anchored_volume_ab_20261009 --phase development --variants A A3 A4 --carry-bps-per-day 5
.venv/bin/python -m pytest -q tests/test_lighter_anchored_volume_ab_20261009.py
```

All JSON evidence lives under:
`run_log/lighter_anchored_volume_ab_20261009/`.

Files created in the already-dirty `quant-research` checkout, preserving
preexisting source and jobs. No live bots were stopped or modified; no
trades were submitted. New files remain uncommitted.

## Research decision / next step

Neither strategy is approved. The independent two-cycle model **can**
produce extra downward-market maker volume, but it carries QQQ short risk
in a rally; no clean exit is guaranteed merely because prior baskets
closed at nonnegative PnL. The dynamic-hedge model controls development
drawdown but is sensitive to funding, queue assumptions, beta drift and
capital accumulation.

**Next decisive experiment:** record synchronized Arcus SPY/QQQ L2 book,
trades (with aggressor side), fills, reference/mark prices, and funding.
Replay native post-only queue-aware orders under actual lot/tick limits
and maker-to-maker recycling before translating candidate volume into
Arcus points or deploying any controller.
