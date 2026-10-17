# Hyperliquid XYZ anchored 20-level grid A/B — 2026-10-09

**Decision: EXPLORATORY / NOT APPROVED FOR LIVE DEPLOYMENT.**
No Arcus controller or production orders were modified.

## Thesis and design

User objective: generate genuine passive maker fills using fixed-price,
long-horizon inventory stacking and maker breakeven exits, not short-term
prediction. Compare independent, opposite-sided cycles (A) against a
SP500-long dynamic beta-linked XYZ100 short hedge (A4).

- Both markets are Hyperliquid HIP-3 perpetuals, not the exact SPY/QQQ
  perpetuals available on Lighter/Arcus.
- A: 20 simultaneously resting **SP500 bids**, 20 simultaneously resting
  **XYZ100 asks**, each with **$100 entry notional**. Anchors frozen until
  their **own** maker-limit basket exits at price recovery and net
  cash breakeven.
- A4: 20 simultaneously resting SP500 bids, **$100 clips**. It attempts
  dynamic XYZ100 short maker hedges only after SP500 buys fill; hedge quotes
  are conditional, so not all 20 can legally/rest consistently without
  overhedging an unfilled SP500 book. Net-breakeven is computed at the
  *linked basket* level. A4 **does not guarantee a hedge**, because a
  maker QQQ analog ask may never execute.
- Grid anchor levels: 2, 27, 52, ... 477 bps adverse to each cycle's
  starting reference. The 20-order side ladder spans ~4.77%.
- User correction: **$600 margin at 10× leverage = $6,000 maximum gross
  notional**, not $6,000 cash. Independent 40 orders reserve ~$4,000
  total, leaving ~$2,000 headroom. Max leg inventory allocation $2,000
  including outstanding entry orders; stop at $50 drawdown; $100
  global DD configuration is recorded but cannot be enforced across
  unrelated live accounts by this isolated historical simulator.
- Hard stop triggers taker-market unwinds, not falsely counted as
  successful maker-completed baskets. Simulated next-bar liquidation can
  exceed the nominal $50 drawdown by a gap or execution delay.
- No exchange-specific 10× liquidation, maintenance margin, funding
  timestamp, maker queue, or Arcus Points model was used.

## Frozen data and evaluation

- Source: CryptoHFTData-derived 1m Hyperliquid trade OHLCV in
  `/home/quant/dev/quant/ml4t-data/.data/store/crypto_futures_ohlcv_1m_HYPERLIQUID_XYZ_PERP`.
- Historical coverage: 2026-04-14 through 2026-10-08.
- Initial calibration: 2026-04-14 through 2026-04-30.
  Initial 1h log-return SP500-on-XYZ100 beta = **0.6290750695**;
  subsequent dynamic beta uses lagged 14-day 1h rolling data and smoothing.
- Development: 2026-05-01 through 2026-07-31, **132,239 joined
  minute bars**.
- Chronologically later test: 2026-08-01 through 2026-10-08,
  **99,360 joined minute bars**. **Not a pristine holdout**, because
  an overlapping calendar period was examined in previous Lighter
  research; nevertheless variant rules were fixed before the main runs.
- Known suspicious source gaps are flagged; no order fills are allowed
  in the first bar following a timestamp gap. Positions remain marked
  and accrue carrying cost across the elapsed time.
- Orders use the official **ml4t.backtest.Engine** with
  `ExecutionMode.NEXT_BAR` and native LIMIT order handling.
- A custom `ExecutionLimits` adapter enforces a **shared 10% of each
  reported bar's base volume for all eligible orders on that
  instrument**, avoiding 20× volume reuse. Ambiguous venue resolution
  fails closed. Limit-price touch requires one extra tick of high/low
  penetration. No fills are allowed with zero reported bar volume.
  Alternative 1% participation was evaluated after the base runs.
- Partial-fill variants retain the same resting order across partial
  executions; the order ledger reconciles each broker Fill by ID.
- Maker fee assumed zero. All maker fills are ***candidate*** fills,
  not verified post-only accepted orders or volume awarded by Arcus.
  Actual maker adverse selection, historical spread, true price sequence
  within each 1m bar, and queue probability remain unknown.
- Emergency taker fee plus slippage stress: 4.25bps of actual emergency
  taker notional.
- Base funding 0. Sensitivity carries inventory at an
  **assumed +5bps/day on gross notional**, *not* actual signed perpetual
  funding. It can change both PnL and which cycles complete.
- All results are from separately initialized portfolios for each period,
  **not** an uninterrupted April-October account.

## Development results: frozen $100 order clips, 10% volume participation, 0 carry

| Variant | Completed candidate maker USD | Total candidate maker USD | Maker fill events | Peak-to-trough DD USD | PnL ex points USD | $50 stop? |
|---|---:|---:|---:|---:|---:|---|
| A 20-level independent | **3,000.949** | 4,100.758 | 38 | 50.8666 | -47.6070 | YES |
| A4 20-level passive dynamic hedge | **16,033.421** | 17,342.328 | 146 | 27.4014 | -5.7278 | No |
| A + native partial fills | **3,000.949** | 4,156.538 | 39 | 50.7006 | -47.4410 | YES |
| A + partial + sub-basket recycling | **17,109.286** | 18,667.081 | 196 | 50.8964 | -48.1698 | YES |
| A4 + native partial fills | **16,033.421** | 17,342.328 | 146 | 27.4014 | -5.7278 | No |

- Independent A hit stop **2026-05-08 ~14:02 UTC**, only ~7.6
  days into 92-day development. A partial hit stop May 8 ~13:52.
  A subbasket hit stop May 8 ~17:02.
- A4 had **74 SP500 entry-fill events and only 16 XYZ100 short
  hedge-fill events**. At period end, A4 held approximately **$697 SP500
  long with no XYZ100 short**, and its peak beta-residual exposure was
  ~$363. Therefore A4 should be labeled **attempted passive hedging,
  not guaranteed market neutrality**.
- Completed clean cycles: A independent **9 SP500 + 3 XYZ100**;
  A4 linked **47**. A subbasket **28 SP500 + 59 XYZ100**,
  many more cycles but forced stop.
- The research audit discovered a defect in an initial run: interrupted
  emergency-market baskets were recorded as successful completed
  cycles. This was fixed and all reported numbers were rerun.
  A's corrected completed volume is $3,001, **not $4,101**;
  A still had $4,101 of candidate maker fills overall. No forced
  taker volume is included in completed-volume figures.

## Chronologically later period: frozen $100 clips

| Variant | Completed candidate maker USD | Total candidate maker USD | Maker fill events | Peak DD USD | PnL ex points USD | $50 stop? |
|---|---:|---:|---:|---:|---:|---|
| A independent | **799.527** | 1,899.373 | 18 | 50.6066 | -47.6722 | YES |
| A4 linked | **200.084** | 200.084 | 2 | 0.3031 | +0.0925 | No |
| A partial | **799.527** | 1,952.314 | 19 | 50.6573 | -47.7229 | YES |
| A subbasket | **9,596.486** | 10,853.628 | 111 | 50.6360 | -49.4555 | YES |
| A4 partial | **200.084** | 200.084 | 2 | 0.3031 | +0.0925 | No |

- Independent A stop: **2026-08-04 17:36 UTC**, ~3.7 days in.
  A subbasket stop ~2026-08-04 19:43 UTC.
- The later A4 account completed **one 2-fill SP500-only
  basket** and **zero XYZ100 hedge fills**. It had low drawdown
  principally because **it hardly traded at all**, not because
  beta neutrality had been demonstrated.
- As A4 requires SP500 bids to fill before quoting a QQQ-analog
  hedge, it cannot produce continuous standalone XYZ100 volume
  during a persistent bull trend.

## One-change-at-a-time / post-hoc sensitivities

### Partial fills

A to A_partial differs **only** by allowing fill fragments across
consecutive bars at the same fixed 20×$100 levels. At 10%
bar participation, A saw one partial execution in development
and one later; volume and stop outcome barely changed.
A4_full versus A4_partial returned identical base results.

### Sub-basket recycling

A_partial to A_subbasket changes the inventory exit rule only:
each filled level can close its own breakeven limit and rearm its
fixed level, without requiring the full portfolio to re-anchor.
The subbasket earned much more ***simulated*** completed volume
($17.1k development, $9.6k later), but still triggered
$50 drawdown early. No evidence of long-run sustainable
volume under these limits.

### Smaller $50 clips (post-hoc sensitivity only, not the main request)

The frozen baseline stays **20×$100**. In separate `--clip-usdc 50`
diagnostics, the two-sided A orders reserve ~$2k rather than $4k
and use less inventory per fill.

| Phase | Variant | Completed volume | Max DD | PnL | Stopped? |
|---|---|---:|---:|---:|---|
| Development | A | $1,902 | $50.57 | -$49.27 | Yes |
| Development | A4 | $13,059 | $6.13 | +$10.41 | No |
| Later | A | $1,801 | $50.63 | -$48.78 | Yes |
| Later | A4 | $1,802 | $0.67 | +$1.78 | No |

Because this reduces deployed exposure, it is not
capacity-matched to the $100 clips. It is a post-hoc
diagnostic, not a model-selection proof.

### Funding/financing sensitivity

Hypothetical 5bps/day gross-inventory carrying charge:

| Phase | Variant | Completed volume | Max DD | Net ex points |
|---|---|---:|---:|---:|
| Development | A | $3,603 | $50.85 | -$48.99 |
| Development | A4 | **$1,201** | $35.92 | -$26.48 |
| Later | A | $800 | $50.57 | -$48.19 |
| Later | A4 | $200 | $0.31 | +$0.07 |

The A4 development result is **sensitive to holding cost**.
Historical signed funding could be positive or negative; do
not equate this cost sensitivity with actual Hyperliquid rates.

### 1% volume participation stress

After the main experiment, the maximum per-minute shared
volume budget was reduced from 10% to **1%**.
The broad ranking did not change; nearly all $100 clips still
had enough reported volume to fill under the candle-touch
assumption. In development, A and A4 completed-volume results
were unchanged at $3,001 and $16,033, respectively.
This does **not** validate actual maker queue fills.

## Decision

**Do not deploy either version based on 1m bars alone.**

1. Under a fixed $50 drawdown stop, independent 20×$100
   bid/ask stacking runs out of safe capital very quickly:
   ~7.6 days in development and ~3.7 days in later evaluation.
2. Sub-basket recycling multiplies candidate maker volume but
   does not eliminate tail inventory loss; it reaches the
   drawdown stop on similar dates.
3. A4's apparent risk advantage is partially a *lower
   actual exposure / fewer fills* effect; it is not guaranteed
   neutral. Passive XYZ100 maker hedges did not reliably
   follow SP500 entries.
4. Keeping the $100 clip while having $600 initial margin
   and a $6k gross ceiling is mechanically possible:
   20×$100 on each entry side reserves $4k at once,
   but $50 risk stop limits achieved candidate volume far
   more than the gross cap does.
5. The next decisive comparison should test inventory
   sizing conditional on **actual gross risk** and the
   tradeoff between partial passive hedging and emergency
   cost, followed by venue-specific Arcus quote execution
   measurement if deployment is contemplated.

## Reproduction

```bash
cd /home/quant/dev/quant/quant-research
.venv/bin/python -m scripts.run_hyperliquid_xyz_full_ladder_ab_20261009 --phase development
.venv/bin/python -m scripts.run_hyperliquid_xyz_full_ladder_ab_20261009 --phase later
.venv/bin/python -m scripts.run_hyperliquid_xyz_full_ladder_ab_20261009 --phase development --variants A_full20 A4_full20 --carry-bps-per-day 5
.venv/bin/python -m scripts.run_hyperliquid_xyz_full_ladder_ab_20261009 --phase later --variants A_full20 A4_full20 --carry-bps-per-day 5
.venv/bin/python -m scripts.run_hyperliquid_xyz_full_ladder_ab_20261009 --phase development --variants A_full20 A4_full20 --clip-usdc 50
.venv/bin/python -m scripts.run_hyperliquid_xyz_full_ladder_ab_20261009 --phase development --volume-participation 0.01
.venv/bin/python -m pytest -q -n 0 tests/test_hyperliquid_xyz_full_ladder_ab_20261009.py
.venv/bin/ruff check scripts/run_hyperliquid_xyz_full_ladder_ab_20261009.py tests/test_hyperliquid_xyz_full_ladder_ab_20261009.py
```

Research config:
`config/research_sessions/hyperliquid_xyz_20level_anchored_volume_ab_20261009.yaml`.

Results:
`run_log/hyperliquid_xyz_20level_anchored_volume_ab_20261009/`.

Implementation:
`scripts/run_hyperliquid_xyz_full_ladder_ab_20261009.py`.

11 focused tests cover full 20x$100 ladders, shared volume
budget, full/partial fills, no ghost zero-volume fills,
10×/$6000 limits, and crucially that emergency taker
unwinds never qualify as successful completed maker cycles.

All created source artifacts remain uncommitted in the
pre-existing dirty quant-research tree. No live strategy
was modified or started.
