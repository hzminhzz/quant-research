# Forensic Summary

## Verdict
VERIFIED FACT: the old edge was not mainly a DST artifact. On the common 2017–2024 development window, local-session/DST correction reduced gated P&L by only 12.34R. The largest measured losses were the coupled executable-entry/calendar/intrabar correction (-62.77R) and validation correction (-53.51R). Pure 4→6 bp costs removed another 20.75R with scores frozen. SPX availability correction by itself was small (-2.95R). The corrected raw ORB materially outperformed the meta-gated strategy in development, while both raw and gated strategies were negative on the frozen 2025–2026 holdout because 2026 itself was strongly negative.

## Performance waterfall

| Stage | Trades | WR | Net R | Common daily Sharpe | MDD | Delta R | Native/packed Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|
| R0_legacy_parity | 767 | 56.19% | 168.95 | N/A | N/A |  | 1.419 |
| R1_timezone_DST_only | 875 | 54.74% | 156.61 | N/A | N/A | -12.34 | 1.251 |
| R2_R3_PIT_nextbar_EOW_intrabar_bundle | 850 | 52.47% | 93.84 | 0.921 | -0.207 | -62.77 | 0.847 |
| R4_correct_validation | 788 | 53.43% | 40.33 | 0.428 | -0.323 | -53.51 | 0.408 |
| R5_correct_portfolio_accounting | 788 | 53.43% | 40.33 | 0.428 | -0.323 | 0.00 | 0.408 |
| R6a_6bps_fixed_4bp_scores | 788 | 52.41% | 19.57 | 0.208 | -0.365 | -20.75 | 0.198 |
| R6b_authoritative_6bps_cost_aware_refit | 713 | 52.73% | 27.88 | 0.313 | -0.259 | 8.31 | 0.291 |

## Biggest measured causes
- PIT/next-bar + EOW/intrabar mechanics bundle: -62.77R.
- validation package: -53.51R.
- pure 4->6bp costs, scores frozen: -20.75R.
- timezone/DST sessions: -12.34R.
- SPX availability correction within legacy-like mechanics: -2.95R.

## Meta model
- Development: raw ORB 90.71R / Sharpe 0.703; gated 27.88R / Sharpe 0.313. Meta uplift = -62.83R.
- Frozen holdout: raw ORB -9.81R / Sharpe -0.358; gated -17.01R / Sharpe -0.840. Meta uplift = -7.19R.
- AUC decays from ~0.553 in the early development era to 0.496 by the 2024 inner validation. The 0.50 cutoff is a frozen raw-score threshold, not a calibrated probability threshold.

## 2026
- Gated: -29.53R. Raw ungated: -33.23R. Meta gating therefore improved 2026 by only +3.71R; the primary strategy itself failed in 2026.

## Legacy reproducibility / DSR
- Current-data legacy parity reproduces the old headline shape closely but not exactly. Exact legacy parity is blocked by missing immutable historical data provenance.
- DSR_UNREPRODUCIBLE_LEGACY_TRIAL_UNIVERSE remains authoritative; the trial ledger does not justify historical n_trials=42 or a 99% DSR claim.

## Next research decision
**C. Continue with targeted robustness research.** Freeze the meta model out of the next experiment and test whether the corrected ungated ORB has stable forward/regime robustness. Do not tune the frozen holdout. The immediate research target is the 2026 raw-ORB regime failure, not another meta threshold or parameter search.


## Correction: pure timezone attribution

The earlier R1 label was too broad. The repository's timezone-only lane uses the corrected session/calendar path for every asset and then retrains one shared meta model. That allowed JP225/HK33 results to move despite having no DST clock change.

A corrected counterfactual freezes JP225/HK33 to their exact legacy event objects and changes only DE30/NAS100 session clocks:

- Pure timezone R: 168.95R -> 154.97R, delta -13.97R.
- JP225: candidates 244 -> 244; gate spillover +2.98R.
- HK33: candidates 242 -> 242; gate spillover -2.16R.
- DE30 treated sleeve selected delta: +6.56R.
- NAS100 treated sleeve selected delta: -21.35R.

JP/HK score/gate movement in this counterfactual is shared-model spillover, not a timezone effect.
