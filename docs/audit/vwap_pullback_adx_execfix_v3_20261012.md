# Strategy 2 VWAP Pullback + ADX — Execution remediation (v3)

Date: 2026-10-12. Repository: `/home/quant/dev/quant/quant-research`.
Branch `main`, implementation base HEAD `c095faa`.
Status: **EXECUTION-SIMULATOR REPAIR VERIFIED; EXTERNAL CME VALIDATION BLOCKED**.
Session: `vwap_pullback_adx_nq_20261012_proxy_v3_execfix`, `EXPLORATORY / NOT_APPROVED`.

## Change scope

The prior Phase 4 native engine runs were correct about signal timing but incorrectly
charged adverse fixed slippage on resting sell LIMIT target orders. This meant an
order to sell at or above X could record X minus 0.25/0.50 points in a cost-aware
run. That violates a limit order's execution price floor.

This work **did not rewrite or overwrite** v2 artifacts, the frozen original/v2
specs, indicators, signal triggers, TP/SL levels, date window or trial history.
Instead a new v3 frozen session declared the correction before it was executed.

The v3 adapter, `scripts/run_vwap_pullback_adx_execfix_v3_20261012.py`,
uses `ml4t.backtest.Engine` 0.1.7 with `LegalLimitFillExecutor`, a
`FillExecutor` subclass. It invokes **the installed native fill/accounting
engine** for every fill. It temporarily applies the installed `NoSlippage`
model only while executing a LIMIT fill and restores the configured slippage
model for MARKET and STOP orders. We did not modify `.venv` or site-packages.

### Native OCO correction to the previous diagnosis

`ml4t-backtest` 0.1.7's native `FillExecutor.execute` already cancels other
pending orders sharing a `parent_id` after a fully filled child. The frozen
v2 Strategy already assigns `parent_id` to stop and target before the next-bar
fill; for these 1-contract, non-partial-fill simulations this is native
**fill-time sibling cancellation**. Therefore, the previous blanket
statement that native OCO was unavailable was inaccurate.

Independent tests verified stop-first on a synthetic dual-hit bar, cancellation
of target sibling, no reverse position, stop gap-through behavior, and a legal
resting sell limit price floor under nonzero market-order slippage.
**This proves native simulated sibling handling, not atomic broker/exchange
OCO guarantees or partial-fill safety.**

## Scope

- LSE provider-defined `NQ.F` continuous futures **proxy**. Exact CME
  quarterly contract identities, roll rules, trade volume and bid/ask prices
  remain unverified.
- Frozen `data/processed/vwap_adx_nqf_2026h1_1m.parquet` SHA256
  `a0670b34b2175ca0df4a7ab98fa79bb02650cf4cce64ed67261ad29f706ebaad`.
- Jan 1–Jun 30, 2026 development only; 122 complete 08:30–15:55 CT
  trading sessions after excluding the March 6 source gap.
- NQ-equivalent one contract, $20/point, 0.25 point/tick, initial
  1,000,000 USD *only for account-metric illustration*.
- Base cost: $2.50 commission per side, 0.25-point adverse slippage
  per MARKET or STOP fill, zero adverse limit slippage.
  Stress: same $2.50 commission and 0.50-point adverse MARKET/STOP
  slippage. Fee quotes remain unverified.

## Results

| Strategy | Trades | Corrected base win rate | Corrected base net PnL USD | Daily Sharpe | Calmar | Max DD % | Stress net PnL USD |
|---|---:|---:|---:|---:|---:|---:|---:|
| B1: OR only | 320 | 79.69% | +3,405 | 0.537 | 0.896 | 0.787 | +1,585 |
| B2: VWAP, no ADX | 115 | 50.43% | **+6,850** | **1.531** | **2.795** | **0.508** | **+6,000** |
| B3: VWAP + ADX | 77 | 72.73% | +4,310 | 0.938 | 1.246 | 0.716 | +3,840 |

Net PnL under original no-cost model remains B1 +$6,825, B2 +$8,275,
B3 +$5,165. Legal-limit repair increases base PnL by exactly $5 per limit
fill: B1 +$1,380 (276 limit exits), B2 +$300 (60 exits), B3 +$300 (60).
The correction does not change signals, entry/exit timestamp, exit order type,
or trade count in any of the nine variants.

B2-vs-B3 difference on corrected base daily returns:
- Total B3 minus B2 net PnL: **-$2,540**.
- Paired session average: **-$20.82/day** across 122 sessions.
- 10,000 paired bootstrap draws, 95% confidence interval for the
  daily difference approximately **[-$114.51,+$67.66]/day**.
- The marginal ADX effect remains **INCONCLUSIVE**; B2 remains the
  stronger in-sample development candidate. No new hyperparameter
  search and no holdout inspection.

## Verification

- Native bracket unit suite: five focused tests passed.
- Existing Phase 3, Phase 4, and independent FX execution regressions:
  together **22 tests passed**. Synthetic tests explicitly cover
  immediate TP, stop-first double touch, gap-through STOP, no OCO double
  fill, native commission, limit price floor, and next-open timestamp.
- `scripts/audit_vwap_pullback_adx_execfix_v3_20261012.py` independently
  compared all nine native trade/fill/order paths to the saved v2 trials.
- Audit verdict: `PASS_PROXY_NATIVE_EXECUTION_REPAIR` for all nine.
  Illegal limit-price fills=0. Nonzero LIMIT slippage=0.
  Fee/market-stop slippage mismatches=0. All 122 days remain within
  H1 development. All signals, fill order types and timestamps unchanged.
  All native realized trade totals reconcile to native account equity.
- The installed library version is pinned to `ml4t-backtest==0.1.7`.
  If its APIs or fill semantics change, `LegalLimitsEngine` rejects the
  run pending inspection.

## Provenance

- Config:
  `config/research_sessions/vwap_pullback_adx_nq_20261012_proxy_v3_execfix.yaml`.
- Implementation:
  `scripts/run_vwap_pullback_adx_execfix_v3_20261012.py`.
- Audit:
  `scripts/audit_vwap_pullback_adx_execfix_v3_20261012.py`.
- Regression:
  `tests/test_vwap_pullback_adx_execfix_v3_20261012.py`.
- Native runs:
  `run_log/vwap_pullback_adx_nq_20261012_proxy_v3_execfix/phase4_remediated/`.
  Contains `all_trials.json`, `remediation_audit.json` and separate
  `B1/B2/B3_{gross,cost,stress}` trade/fill/equity files.
- Session registry: `T0_native_oco_limit_contract_test`,
  `T1_corrected_native_replay`, `T2_independent_reconciliation`
  recorded as completed exploratory trials.
- Prior v2 remains unchanged and independently reproducible.
- No git commit or push was made. Pre-existing dirty work was preserved.

## Remaining external/epistemic blockers

Software-level price-floor and sibling-cancel bugs are corrected **for the
registered native replay**. It is impossible to certify true CME execution
from the available LSE continuous series or Dukascopy index CFD data alone.

1. **Dated CME NQ/MNQ contracts and rolls**: the available LSE NQ.F
   manifest says `provider-defined series` and does not identify contract
   month, roll calendar or adjustment. The local Dukascopy data is a CFD
   index. No raw matched CME month chain was found in the available
   canonical store. Source-level roll identity remains BLOCKED.
2. **True CME traded volume**: LSE `volume` field is vendor reported,
   not independently verified exchange contract volume. VWAP remains
   a source-weighted proxy. This is a data provenance blocker.
3. **Passive limit queue eligibility**: minute OHLC highs touching the
   limit do not guarantee a fill. A live-like model needs bid/ask trade
   prints or queue/order-book data, or a separately frozen conservative
   fill-rate model. No such evidence was present.
4. **Commission, spread, market impact**: the user's brokerage tier,
   exchange/clearing fees, per-contract spread and actual fill records
   were not provided or verified. $2.50/side is illustrative.
5. **Production**: no brokerage OCO/partial-fill validation or four-week
   paper-trading exercise. No protection against live connectivity failure
   or real-time contract expiry is implied.
6. **OOS**: July–October retrospective validation and November prospective
   holdout remain sealed. Previously seen 2026 index results cannot be
   reclassified as untouched data.

Therefore **Phase 4 proxy replay is verified; live/exact-CME execution
remains BLOCKED / UNKNOWN**. Do not promote to live or loosen the
holdout to make the result look better.

Next decisive evidence is contract-resolved minute futures data with
exchange-reported contract volume, bid/ask quotes where possible, and the
actual broker execution fee schedule. Otherwise continue as explicitly
labeled exploratory proxy research only.
