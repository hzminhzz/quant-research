# VWAP Pullback + ADX (B1/B2/B3) — Phase 5 and 6 verification

Date: 2026-10-12. Repo: `/home/quant/dev/quant/quant-research`.
HEAD `c095faa` on branch `main`. No commits or pushes made.
**Outcome: Phase 5 NQ.F full-period validation BLOCKED by missing data.
Independent cash-index proxy replication NEGATIVE for B2/B3.
Phase 6 development-only robustness completed, but statistically inconclusive.**
All research remains `EXPLORATORY / NOT_APPROVED`.

## Frozen boundaries and methodology

- The Phase 4 version-three strategy and native `ml4t-backtest` 0.1.7
  executable fill adapter were held fixed. B1=OR breakout, B2=OR+VWAP,
  B3=B2+ADX(14)>20 flat/falling. The TP is prior completed five-minute
  high, SL the prior twenty-minute low, long market next-minute open,
  and forced flat at 15:55 America/Chicago.
- New Phase 5/6 record: `config/research_sessions/vwap_pullback_adx_nq_20261012_proxy_v4_phase56.yaml`.
  Frozen **before** July–September strategy results were calculated.
- Intended retrospective validation: 2026-07-01 through 2026-10-11.
  Primary comparison: **complete July, August, September 2026 Chicago
  session months**, 64 expected full XNYS sessions. October 1–2 is
  partial; October 3–11 is missing. No October signals were scored.
- The **November 2026 onward prospective holdout is sealed**.
  Related Nasdaq 2026 research was already observed in other sessions;
  this is retrospective validation, not pristine independent OOS.
- There is no trained predictive model, so Phase 5 walk-forward means
  *three consecutive no-refit calendar-month folds*, not rolling
  retraining. No randomized splits, no optimization on July–September.
- One hypothetical NQ-equivalent contract; $20/point, 0.25-point tick;
  $1,000,000 accounting baseline; illustrative $2.50/side commission
  and one 0.25-point adverse tick for MARKET or STOP fills, zero adverse
  LIMIT slippage. Stress is two ticks per aggressive fill.
  Native linked OCO cancels siblings on full fills; not live broker OCO.

## Phase 5A — Primary NQ.F continuous futures proxy

Source `data/processed/vwap_adx_nqf_2026h2_validation_1m.parquet`
SHA256 `21bd6e367df44b934386e59e831c7e8090116de9d5fd9ac82ca8a8ff9d7c4839`,
from immutable LSE export
`/home/quant/dev/quant/ml4t-data/.artifacts/lse-orb/raw-nq/futures_NQ.F_1m.parquet`
SHA256 `c12e2aaf9e7a4bbe8224d09a53bc7416f7088a2693d87adf3de0138fbf6a8edd`.

Source has data to **2026-10-02 20:59 UTC** but July–September
cash-minute grid is incomplete on most session days. Of 64 scheduled
full cash sessions: **19 pass full 08:30–15:55 CT coverage**, 45 fail,
and **no August trading day passes**. The missingness is clustered
after July 20 and in August/September, not random.
No synthetic minute bars, alternate price interpolation, or lower
session-coverage threshold was used for primary approval.
**Phase 5 NQ.F 3-month primary validation is BLOCKED.**

A separate incomplete-source diagnostic ran native B1/B2/B3 on the
19 eligible sessions. It is *not* a valid three-month OOS estimate.

| Variant | Trades | Gross USD | Net USD base | Net USD two-tick |
|---|---:|---:|---:|---:|
| B1 | 64 | -895 | **-1,605** | -1,995 |
| B2 | 19 | -945 | **-1,190** | -1,340 |
| B3 | 14 | -355 | **-510** | -595 |

The 11 July sessions and eight September sessions are irregularly
distributed. They cannot be extrapolated to missing August days.
The recorded failure is in
`run_log/vwap_pullback_adx_nq_20261012_proxy_v4_phase56/phase5_primary_blocker.json`.

## Phase 5B — Separate NAS100 index-proxy cross-source replication

**This is a DIFFERENT asset/source and NOT a substitute for futures OOS.**
A separately frozen session, before its outcomes were inspected:
`config/research_sessions/vwap_pullback_adx_nas100_20261012_cross_source.yaml`.

Source: LSE `index_minute_NAS100`, `NAS100` *cash-index*
1-minute source `data/processed/vwap_adx_nas100_2026h2_1m.parquet`
SHA256 `da3891d4ae7d686da6832081f322c7b2571bcc92e0e0ce5581b860a7e9d66e17`.
It contains **64/64 full July–September cash sessions** after the
XNYS calendar filter. The price basis and vendor volume differ from
NQ.F. Reusing the NQ $20/point multiplier is hypothetical comparison
arithmetic, not an executable index PnL claim.

| Variant | Trades | Gross USD | Net USD base | Net USD two-tick |
|---|---:|---:|---:|---:|
| B1 | 174 | +2,079 | **+214** | -781 |
| B2 | 73 | -11,288 | **-12,243** | -12,833 |
| B3 | 47 | -2,141 | **-2,661** | -2,946 |

Disjoint month net USD by unchanged strategies:

| Variant | July (22 sessions) | August (21) | September (21) |
|---|---:|---:|---:|
| B1 | -68 | +703 | -421 |
| B2 | -777 | **-5,261** | **-6,205** |
| B3 | +1,917 | -1,675 | -2,903 |

Index-proxy B2 failed in all three months. Index-proxy B3 was
negative over three months. The ADX gate reduced losses vs B2
by **$9,582** on this feed, but did not establish positive net alpha.
The cross-source result falsifies generalization to this **specific
index price proxy**, not CME NQ.

## Phase 6 — Development-only robustness (January–June, 122 sessions)

Source and strategies unchanged from v3. Use native `ml4t.Engine`,
and a bounded engine adapter for +1 tick extra passive sell-limit
touch confirmation. This changes ONLY a price-touch assumption; it is
not actual queue modeling. It does not amend entry rules.

| Variant | Base one-tick net USD | Two-tick net USD | Four-tick net USD | Passive target +1 tick net USD |
|---|---:|---:|---:|---:|
| B1 | +3,405 | +1,585 | **-2,055** | +3,395 (317 trades) |
| B2 | +6,850 | +6,000 | **+4,300** | +6,850 (115 trades) |
| B3 | +4,310 | +3,840 | **+2,900** | +4,310 (77 trades) |

Four ticks represents a large uncalibrated adverse slippage
assumption for every aggressive side. It turns B1 negative.
B2/B3 remain positive in development, **not proof of live profits**.
The +1 tick passive limit buffer does not change B2/B3 results on
these bars; that is an insufficient queue stress, not evidence that
passive fills are certain.

Development month net PnL, USD:

| Variant | Jan | Feb | Mar | Apr | May | Jun |
|---|---:|---:|---:|---:|---:|---:|
| B1 | +960 | +3,660 | **-5,050** | +2,420 | +1,250 | +165 |
| B2 | +1,045 | +2,290 | -1,115 | +1,640 | +5,430 | -2,440 |
| B3 | +2,155 | +5,135 | **-6,400** | +2,585 | +2,260 | -1,425 |

Block-bootstrap (10,000 circular 5-session resamples of daily PnL),
95% interval for **the 122-session development total**:
- B1: approx **[-$17,265, +$21,860]**.
- B2: approx **[-$7,465, +$19,565]**.
- B3: approx **[-$10,910, +$18,930]**.

All development-block intervals include zero.
For B3 minus B2, observed -$2,540; 5-session block interval approx
**[-$15,750, +$9,496]**, indicating insufficient precision
to prove incremental ADX value. These bootstraps do not
resimulate order fills under randomized price paths and do not replace
genuine market-regime coverage. The short six-month history and
incomplete global trial count make DSR/PBO **UNREPRODUCIBLE**.
Do not fabricate an adjusted Sharpe or call a passing cost scenario
proof of low overfitting.

As a supplementary descriptive diagnostic, on the **NAS100 index**
July–Sep B2 5-session-block bootstrap 95% total interval was
approximately **[-$21,222,-$3,995]** and on B3
**[-$9,907,+$3,929]**; repeated daily-return blocks may not
capture real regime uncertainty.

## Verification

Implementation:
- `scripts/materialize_vwap_adx_phase5_validation_20261012.py`
- `scripts/run_vwap_pullback_adx_phase5_20261012.py`
- `scripts/run_vwap_pullback_adx_phase5_incomplete_diagnostic_20261012.py`
- `scripts/run_vwap_pullback_adx_phase6_20261012.py`
- `scripts/materialize_vwap_adx_nas100_cross_source_20261012.py`
- `scripts/run_vwap_pullback_adx_nas100_cross_source_20261012.py`
- `scripts/audit_vwap_pullback_adx_phase56_20261012.py`

Evidence and audits:
- `run_log/vwap_pullback_adx_nq_20261012_proxy_v4_phase56/phase56_independent_audit_v2.json`
- `run_log/vwap_pullback_adx_nq_20261012_proxy_v4_phase56/phase6/all_trials.json`
- `run_log/vwap_pullback_adx_nq_20261012_proxy_v4_phase56/phase5_incomplete_nqf_19sessions/all_trials.json`
- `run_log/vwap_pullback_adx_nas100_20261012_cross_source/phase5_cross_source/all_trials.json`

Native Engine runs: B1/B2/B3 each with gross/base/two-tick
scenarios for both Phase 5 datasets; B1/B2/B3 each with four-tick
and extra one-tick passive-limit confirmation for Phase 6.
Audit verifies next-bar entry, prior-5/20 completed-bar levels,
all nonzero-fee aggressive and passive fill semantics, no
limit underfill, no noncausal fills, all exits <=15:55 CT,
one entry and one exit per native trade, zero unexpected
reversals and all native cash/trade reconciliations.
An initial audit falsely reordered same-timestamp order IDs
lexicographically (e.g. `ORD-101` before `ORD-99`) and was
preserved as a failed diagnostic. The corrected `v2` audit
preserves native fill-journal order; all executions pass.
- Focused regression suite: 28 tests passed.
- Frozen v2, v3 and the November prospective holdout were not edited.
- All unrelated dirty work remained unmodified. No commit/push.

## Final classification and next action

1. **Phase 5 primary NQ.F:** `BLOCKED / INCONCLUSIVE` due 45/64
   missing full cash sessions, source present only to October 2.
   Do NOT call partial-data negative PnL true NQ three-month OOS.
2. **Cross-source NAS100:** Completed **independent exploratory
   replication**, strongly adverse for B2 and negative for B3.
   Do NOT call this actual CME NQ return.
3. **Phase 6:** Completed for B1/B2/B3. B1 fragile to 4-tick
   adverse costs. B2/B3 stronger development cost tolerance but
   no convincing block-bootstrap positive alpha evidence.
4. **Deployment:** `NOT_APPROVED`. Real CME dated contracts,
   validated exchange-traded volume, bid/ask/queue execution,
   broker fees and live OCO/partial fills still unverified.

A qualified Phase 5 NQ futures validation requires **recovering
July–September CME/NQ per-minute trading data for the 45 missing
sessions from a documented primary source** and checking the
same frozen strategy once on the repaired source, recorded as a
new source-dependent trial. Do not fill with index or CFD prices
without naming it a different proxy. Do not peek at the
November prospective holdout.
