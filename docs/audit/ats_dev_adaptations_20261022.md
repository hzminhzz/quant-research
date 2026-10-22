# Untested source-bound crypto cross-sectional adaptations (2026-10-22)

Status: development-only research completed for three previously untested
`research_inbox` theses. All three reached a terminal factory disposition of
`FALSIFIED_STAGE_2`. No candidate is QUALIFIED, no protected row was read, no
Stage 4 ran, and nothing was promoted or deployed.

## Scope and environment

| Item | Value |
| --- | --- |
| Branch | `feat/ats-untested-source-adaptations-20261020` |
| Base | `origin/main` = `9771b737` (PR #90), branch created from the remote, not local `main` |
| Worktree | `/home/quant/.devspace/worktrees/quant-research-04ac7293` (isolated) |
| Python | `/home/quant/dev/quant/quant-research/.venv/bin/python` (Python 3.14, locked environment) |
| Original checkout | `/home/quant/dev/quant/quant-research` — not modified; its two local-ahead commits and dirty AF30 work were left untouched |
| Sources | `research_inbox/*/thesis.yaml`, kept byte-identical |

## Data identity

* Panel: `full_530_20261015`, `manifest_hash`
  `69ed952e9dee296bf0a24de9fce819fdc515f32926f783874da56fd8650a242f`,
  `protected_test_start` `2026-01-01T00:00:00Z`, hourly, ingested 2026-10-15 from
  the local Binance USDT-perpetual raw store.
* Development load over `[.., 2026-01-01)`: 8,296,320 rows, 484 symbols present in
  the development window (530 symbol directories exist; 46 have no row inside the
  window), 1,838,120 point-in-time membership rows.
* This is the same panel identity the earlier 2026-10-20 adaptations used, so the
  data snapshot is unchanged by this work. `panel_root` in the three specs is the
  absolute path to that read-only snapshot in another worktree
  (`quant-research-25440f7a/data/vault/full_530_20261015`); identity is enforced by
  the manifest hash, and `DataVault.load` opens development files only.
* Refused: `data/vault/crypto_perps_1h` (8 symbols) declares
  `quality_summary.execution_qualified: false`, which makes the funnel raise
  `INCONCLUSIVE_STAGE_3` by design, and eight names cannot support a top-40
  cross-section.
* Refused: `markets_20261015` / `markets_v2_20261019` FX/index/metals panels are
  price-only with no observed directional swap. The funnel blocks Stage 3 for
  them; no synthetic cost/carry adapter was invented to get past the gate.
* Qualification caveat, stated rather than exploited: the 530-symbol manifest
  carries no aggregate `quality_summary` key, while per-entry provenance records
  `execution_qualified: false`. No crypto spread was measured; the declared
  cost model folds a zero spread into 9 bps one-way slippage. Results below are
  therefore **modeled-cost development economics**, not venue execution
  qualification.

## Screening

All 112 `research_inbox` theses were read. Five sources were already exposed and
were excluded as untested candidates: `crypto_xs_funding_velocity_dislocation_basket_v1`,
`crypto_xs_funding_carry_exhaustion_basket_v1`, `crypto_xs_90d_high_anchoring_basket_v1`,
`crypto_xs_max_return_salience_basket_v1`, `crypto_xs_wick_asymmetry_basket_v1`.

Eligibility required: an economic mechanism distinguishable from those five; a
formula expressible in the runtime's allowlisted expression grammar; inputs
present in the canonical 12-column schema (`timestamp, symbol, open, high, low,
close, volume, carry_rate, spread_bps, session_id, bar_in_session, is_tradable`);
and a plain UTC hourly next-bar-open clock.

### Documented rejections

| Source | Reason |
| --- | --- |
| `crypto_xs_corwin_schultz_spread_basket_v1` (`b3820933…581402`) | The Corwin–Schultz estimator requires `ln`, `sqrt` and `exp`. The grammar has no such operations; substituting a range-ratio proxy would be a different estimator, so the source was rejected rather than silently reformulated. |
| `crypto_us_session_intraday_momentum_v1`, `crypto_london_orb_breakout_v1`, `crypto_weekend_dislocation_reversal_v1`, `crypto_xs_session_drift_divergence_basket_v1`, `crypto_xs_same_weekday_seasonality_*` | Need hour-of-day or day-of-week extraction from the timestamp. The grammar exposes no timestamp-component operation, and a bar-offset proxy would misfire on missing hours. |
| `crypto_xs_kyles_lambda_basket_v1`, `crypto_xs_taker_flow_imbalance_basket_v1`, `crypto_xs_stealth_trade_size_basket_v1`, `crypto_xs_vpin_adverse_selection_basket_v1` | Require `taker_buy_volume`, `quote_volume` or trade `count`. The snapshot keeps base traded quantity only. |
| 19 `crypto_ml_*` theses | Require a trained model artifact, feature pipeline or on-chain/order-book corpus — not a declarative CandidateSpec. |
| `crypto_spot_perp_basis_dislocation_reversal_v1` (`eeed9469…f9450`) | Needs spot prices alongside perpetuals. The canonical crypto panel has no spot leg. |
| CFD/FX/index/metals theses (`audusd_policy_carry_cfd_v1`, `bta_nq_monday_bb10_atr5_cfd_v1`, `us500_*`, `gbpusd_*`, `dax_*`, `fomc_*`, `oil_to_cad_*`, `hanna_*`, `robotwealth_*`, `quantinsti_*`, `etf_ml_*`, `alvarez_*`) | Price-only or index-proxy data with no qualified cost/carry adapter. |

### BTC residual momentum

`crypto_xs_btc_residual_momentum_basket_v1` (`872dbbe7…7aed7`) was explicitly
evaluated. The stated blocker — a `top40` / `00:01` clock mismatch — **does not
apply here**: the snapshot supports a 530-symbol point-in-time top-40 ranking with
`minimum_assets: 40` (abstain, never narrow) and a next-bar-open fill at 01:00 UTC
after a 00:00 decision bar. It was not selected this round for two stated reasons,
not for a data reason: its 14-day residual-return construction is a long chained
rolling-beta expression with high specification risk, and it is a continuation
construct in a panel where every continuation construct tested below had a
negative rank IC. It remains untested and eligible; no narrowing or relabeling was
performed to make it fit.

## Candidates, source mapping, and results

Common contract for all three: `market_scope: BINANCE_UM_USDT_PERP`,
`top_n: 40`, `minimum_assets: 40`, `lookback_bars: 720`,
`minimum_history_bars: 720`, 5 long / 5 short at 1x gross, `rebalance_bars: 72`,
`label_horizon_bars: 72`, 3x ATR(24) frozen stops, `timing_lag: 1`, commission
5 bps + slippage 4 bps one-way with spread folded into slippage,
train `2020-04-01 → 2024-01-01`, validation `2024-01-01 → 2026-01-01`, protected
declared `2026-01-01 → 2026-10-01` but never read.

Clock: a decision bar stamped `t` (bar open) has its OHLCV and funding information
only at `t+1h`; the allocator schedules bars whose epoch is 0 modulo 72h from the
train start, so a 00:00 UTC decision fills at the 01:00 UTC next-bar open. The
sources' "00:01 same-bar" clock is replaced explicitly in every spec.

Baseline: the sources offer only an equal-weight universe basket or buy-and-hold,
which are not ranked features. Each spec uses a 168h cross-sectional momentum
baseline instead, documented as a researcher departure that makes
`require_baseline_ic_improvement` stricter rather than weaker.

| Candidate | Source (SHA-256 of `thesis.yaml`) | Core construct | Spec SHA-256 | Attempt | Terminal |
| --- | --- | --- | --- | --- | --- |
| `ats_crypto_xs_variance_ratio_dev_adaptation_20261022` | `crypto_xs_variance_ratio_basket_v1` (`9469e931…e15e`) | Lo–MacKinlay `VR(24) = Var(r24)/(24·Var(r1))` over 336h; long high | `a54cebc8…c0728` | `20261022T041331-5337d4ff9f` | `FALSIFIED_STAGE_2` |
| `ats_crypto_xs_volume_return_corr_dev_adaptation_20261022` | `crypto_xs_volume_return_correlation_basket_v1` (`f3f8935f…fae8`) | corr(hourly return, normalised volume change) over 336h; long high | `90ca8db9…39de` | `20261022T041728-01b9a42e1b` | `FALSIFIED_STAGE_2` |
| `ats_crypto_xs_amihud_asymmetry_dev_adaptation_20261022` | `crypto_xs_amihud_asymmetry_basket_v1` (`52810af6…8fe3`) | 168h downside/upside Amihud impact ratio; long high | `132722b6…c073` | `20261022T042058-cc9e6313ec` | `FALSIFIED_STAGE_2` |

### Researcher choices that differ from the source text

| Candidate | Source says | Implemented |
| --- | --- | --- |
| Variance ratio | log returns; `Var24` over `k=0..312`; `max(·,1e-8)` | simple `pct_change` (no log op); 336-bar rolling std of overlapping 24h returns; `max` via `where/gt` floor |
| Volume–return correlation | Spearman rank correlation | Pearson correlation (no time-series rank op); volume change normalised by trailing 336h mean base quantity |
| Amihud asymmetry | no window named | 168h sums for both sides; `|r| / (close·volume)` with a 1e6 USD denominator floor; ratio of sums (no count/sign op) |

All three declared `source_spec_status: local_adaptation`; none claims `exact`
transcription and none claims the cited papers were replicated.

### Stage outcomes (exact)

Stage 1 (`PASS` for all three): exact prefix invariance at cutoffs
`2020-07-14T15:00Z`, `2023-12-05T19:00Z`, `2024-08-23T10:00Z`; 8,296,320 panel
rows; 1,838,120 PIT membership rows; development last timestamp
`2025-12-31T23:00Z`.

Stage 2 (train-only, next-open entry, 72h open exit, Spearman IC per timestamp,
HAC with 72 lags; 1,136,320 eligible rows, 1,133,440 usable, 28,336 paired IC
periods):

| Candidate | mean IC | HAC t | baseline mean IC | baseline HAC t | mean-IC gate | HAC gate | baseline increment |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Variance ratio | **-0.01222** | -1.54 | -0.03485 | -3.95 | fail | fail | pass |
| Volume–return corr | **-0.06006** | -7.21 | -0.03485 | -3.95 | fail | fail | fail |
| Amihud asymmetry | **-0.03158** | -3.93 | -0.03485 | -3.95 | fail | fail | pass |

Stage 3 and 4: not reached. The factory stops at the first failing stage, so no
cost-inclusive equity, Sharpe, beta or stop-fraction evidence exists for these
three specifications. `holdout_access` is `false` and `development_only` is `true`
in all three casefiles:
`run_log/dual_mode/<candidate_id>/<attempt_id>/casefile.json`.

### Cross-cutting observation (not a new claim)

All three continuation-flavoured constructs carry a negative 72h rank IC in the
2020-04 → 2024-01 train window, and the 168h momentum baseline does too
(-0.0349, t -3.95). The previously registered `wick_asymmetry` adaptation — a
reversal-flavoured construct — measured +0.043 on the same panel and horizon.
That pattern is consistent with a cross-sectional 72h reversal regime in this
sample. It is reported as an observation, not as evidence of an edge: acting on
it would require a newly registered, pre-declared reversal specification counted
in the same selection family. Re-running the falsified candidates with a flipped
sign after seeing these outcomes is exactly the post-hoc optimization this
protocol forbids, and was not done.

## Why no candidate can be QUALIFIED here

`scoped_dsr` requires at least 10 prior attempts in `(market_scope,
label_horizon_bars)` **and** at least 10 distinct priors with aligned daily-return
artifacts. This workspace family (`BINANCE_UM_USDT_PERP`, 72 bars) has 3 prior
attempts and none produced daily returns, so Stage 3 would end
`INCONCLUSIVE_STAGE_3` with `dsr_unavailable` /
`native_dsr_minimum_track_record_not_met` even if the economics were favourable.
`prior_trial_ids` is therefore empty in all three specs — declaring those trials
would hard-block Stage 3 while adding no aligned evidence — and the factory still
counts every registered attempt automatically. This is a structural evidence
limit of the workspace, reported rather than worked around.

## Ledger provenance

`run_log/trial_ledger.jsonl` in this worktree is a **copy** of the canonical
append-only ledger at `/home/quant/dev/quant/quant-research/run_log/trial_ledger.jsonl`
taken at 78 records (SHA-256 `ce435230767d7b89afecd9cfce849daddd5426ec1d5b0682e3bc1614f7f737a1`),
after which this work appended 6 records (register/complete per candidate). The
canonical ledger was not modified; it advanced from 76 to 78 records under a
concurrent workstream between two reads, which is why the fork is disclosed with
an exact hash. The chain was not rewritten, and no prior record was edited or
removed.

## Reproduction

```bash
cd /home/quant/.devspace/worktrees/quant-research-04ac7293
export PYTHONPATH="$PWD"
PY=/home/quant/dev/quant/quant-research/.venv/bin/python

for f in config/candidates/*_dev_adaptation_20261022.yaml; do
  "$PY" scripts/quant.py validate "$f"
done
for f in config/candidates/*_dev_adaptation_20261022.yaml; do
  "$PY" scripts/quant.py run "$f" --development-only --run-log run_log
done
"$PY" -m pytest tests/test_ats_20261022_source_adaptations.py -q
```

Each run takes roughly two minutes on the 8.3M-row development load.

## Not claimed

No Stage 3/4 execution, no holdout read or claim, no QUALIFIED disposition, no
evidence that the cited papers' results were replicated, no venue-execution or
spread qualification, no promotion, deployment, broker access or live order
authority. The three source theses and every prior manifest remain byte-identical.
