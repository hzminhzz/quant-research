# VWAP Pullback / ADX — Dukascopy-only source correction

Date: 2026-10-12. Branch: main, HEAD c095faa.
Session: `vwap_pullback_adx_dukascopy_20261012_v1`.
Outcome: **Native Dukascopy CFD proxy replay complete for 2026 available periods.
Full July–September validation BLOCKED. Deployment NOT_APPROVED.**

## Source, fidelity and registered deviation

Only the rebuilt **Dukascopy USATECH.IDX/USD 1-minute OHLCV** data were
used in this new backtest:
`/home/quant/dev/quant/ml4t-data/.data/rebuild/duk21_usatechidxusd/index_minute_NQ/`.
This is a Dukascopy CFD quote-feed stored under the local `NQ` alias,
**not the LSE `NQ.F` series and not an exchange-traded CME NQ future**.

Data materialization:
`data/processed/vwap_adx_dukascopy_2026_1m.parquet`
SHA256 `4ce2efcf496fb77d936d12d866ef5ed5d1e1869879a6b30434a1d0232bb75425`,
243,444 source rows, 222 hashed daily source files,
2025-12-01 to 2026-08-17. The existing Dukascopy staged
archive extends to 2011, but the registered tests here use
the **2026** period; no 2011–2025 strategy returns were calculated.

Source checks: no null values, invalid OHLC, negative-volume rows
or duplicate timestamps; 453 zero-volume source minutes.
Reported `volume` is vendor quote-activity/tick-volume proxy,
**not CME actual contract volume**. Cash-open cumulative
typical-price VWAP uses Dukascopy volume and is a *proxy VWAP*.

The intended original CME 15:55 CT exit is **not available in Dukascopy**.
This was registered *before* new returns were computed as a
**source-specific changed execution variant**. The variant queues
a native market exit after the 15:13 CT bar and fills at the
**15:14 CT bar open**. The morning 08:30–08:59 CT opening range,
OR-breakout, later wick touch and VWAP reclaim, ADX14>20
non-increasing gate, next-bar entry, pre-entry 5/20
completed 1-minute TP/SL and stop-first/OCO handling are unchanged.

- Initial cash $1 million for Sharpe/DD accounting;
  illustrative **one NQ-equivalent $20/point** position and
  **0.25 point** tick/TP/SL rounding. Actual CFD notional,
  volume semantics, spread, fees and lot sizes are not verified.
- Base cost: hypothetical $2.50 USD per side plus 0.25
  point adverse MARKET/STOP slippage only, zero resting LIMIT
  price slippage. Stress: 2 and 4 adverse ticks.
- Native `ml4t.backtest.Engine`, `ml4t.backtest.Strategy`
  using the prior v3 legal-limit adapter. No hand-rolled
  backtest loop or synthetic missing minute insertion.
- Source change and cutoff were registered as a NEW frozen
  session, not by modifying the older NQ.F sessions.

## Data gate

| Period | XNYS full cash sessions | Eligible complete 08:30–15:14 CT sessions | Limitation |
|---|---:|---:|---|
| Jan–Jun 2026 development | 123 | **103** | 20 excluded for zero vendor-reported volume somewhere within cash hours |
| Jul–Aug 17 validation | 33 | **33** | Complete only through Aug 17 |
| Aug 18–Sep 30 | not scored | **0 available** | Absent from this Dukascopy rebuilt source |

The 103 and 33 included days each contain the complete
**405-bar cash-session minute grid**. The XNYS holiday/early-close
calendar and Chicago DST were applied. No 15:55 bar is simulated.

## Registered B0 / B1 / B2 / B3 results, illustrative costs

B0 no trade has zero trading PnL. All USD numbers below are
fictional NQ-equivalent conversions of CFD price differences.

| Variant | Dev trades | Dev base net USD | Jul–Aug17 trades | Jul–Aug17 base net USD |
|---|---:|---:|---:|---:|
| B1: opening range only | 287 | **-6,161.12** | 90 | **+1,315.64** |
| B2: OR + VWAP reclaim | 119 | **+2,849.48** | 32 | **-1,334.32** |
| B3: B2 + ADX slope gate | 83 | **-2,943.38** | 24 | **+2,168.42** |

Development gross / two-tick stress:
B1 gross -$3,031.12 / two-tick -$7,856.12;
B2 gross +$4,299.48 / two-tick +$1,994.48;
B3 gross -$2,013.38 / two-tick -$3,458.38.

Validation gross / two-tick stress:
B1 gross +$2,280.64 / two-tick +$800.64;
B2 gross -$929.32 / two-tick -$1,579.32;
B3 gross +$2,418.42 / two-tick +$2,038.42.

Jul–Aug 17 monthly net, explicitly partial August:
- B1: July -$282.26, Aug 1–17 +$1,597.90.
- B2: July -$1,189.78, Aug 1–17 -$144.54.
- B3: July +$2,193.90, Aug 1–17 -$25.48.

## Phase 6 development-only robustness

| Variant | One-tick base | Two ticks | Four ticks | Target breach +1 tick |
|---|---:|---:|---:|---:|
| B1 | -$6,161.12 | -$7,856.12 | -$11,246.12 | -$8,303.88 |
| B2 | +$2,849.48 | +$1,994.48 | **+$284.48** | +$2,849.48 |
| B3 | -$2,943.38 | -$3,458.38 | -$4,488.38 | -$3,748.38 |

Conservative +1 tick limit-breach test is **not** a
true order-book queue or passive fill-probability model.
Positive B2 four-tick net PnL is marginal and remains unverified.

**Uncertainty:** 10,000 circular five-trading-session block-bootstrap
replications of actual native daily realized PnL:
- Development 95% total-PnL intervals B1
  approximately [-$21,238,+$8,473], B2
  [-$7,561,+$13,459], B3 [-$12,505,+$5,796].
- Validation 95% total-PnL intervals B1
  [-$6,406,+$8,389], B2 [-$4,532,+$2,040],
  B3 [-$1,109,+$5,063].
- B3 minus B2 matched days: development -$5,792.86
  with block CI [-$16,580,+$4,782]; validation
  +$3,502.74 with block CI [+$792,+$6,450].
  The latter is **exploratory** after multiple earlier
  strategy/source examinations and over a short non-pristine
  retrospective sample. Neither B3 alone nor B2 alone
  has a positive interval excluding zero.

## Audit and decision

`scripts/audit_vwap_pullback_adx_dukascopy_20261012.py`
independently inspected all 24 native backtest variants
(nine development, nine validation, three 4-tick
development, three passive-limit development).
Audit: `run_log/vwap_pullback_adx_dukascopy_20261012_v1/independent_dukascopy_audit_v2.json`.

- **PASS_MECHANICAL_CFD_PROXY**, zero mismatches:
  source identity, pre-entry 5/20 price levels, next-minute
  entry timing, market/stop slippage, legal passive limit,
  15:14 CT flat, no overnight carry or unintended reversal,
  and trade/equity ledger reconciliation.
- 19 focused Dukascopy + existing related regression
  tests passed. July-August returns cannot qualify
  a complete July–September gate; November 2026
  prospective holdout was not touched.
- **Decision**: Continue exploratory research, but
  neither B1/B2/B3 has stable positive returns across
  development and available chronological validation.
  September source gap and unverified CFD execution
  costs/true futures volume remain `BLOCKED / UNKNOWN`.
  **No strategy approved for live execution**.

## Reproducibility

Frozen config:
`config/research_sessions/vwap_pullback_adx_dukascopy_20261012_v1.yaml`.
Runs:
`scripts/run_vwap_pullback_adx_dukascopy_20261012.py`.
Materialization:
`scripts/materialize_vwap_adx_dukascopy_20261012.py`.
Audit:
`scripts/audit_vwap_pullback_adx_dukascopy_20261012.py`.
Tests:
`tests/test_vwap_pullback_adx_dukascopy_20261012.py`.
Native artifacts:
`run_log/vwap_pullback_adx_dukascopy_20261012_v1/{development,validation,robustness,stress4tick}/`.
Older v2-v4 NQ.F/LSE results were preserved as historical,
but **not used in this source-replacement backtest**.
No unrelated files modified, no git commit or push.
