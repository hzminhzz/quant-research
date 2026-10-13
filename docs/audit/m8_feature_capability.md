# M8 feature capability check

**Observed:** 2026-10-13. This check records reusable gateway capability. It
does not select or certify a feature for the missing PDF strategy.

## Installed API

The active environment reports `ml4t-engineer==0.1.4` and
`ml4t-backtest==0.1.7`. The installed
`ml4t.engineer.compute_features` signature is:

```text
(data, features, *, group_col=None, timestamp_col=None, assume_sorted=False)
```

The `donchian_channels` registry callable has this signature:

```text
(high='high', low_col='low', period=20) -> tuple[Expr, Expr, Expr]
```

The callable returns upper, lower, and middle expressions. It includes the
current bar. The registry metadata says `input_type="close"`, which does not
describe its actual high/low inputs. The managed gateway rejects it with
`FEATURE_UNSUPPORTED`. Registry presence alone does not certify a managed
feature.

## Capability verified

The general plumbing test requested native ADX(14) and the approved
`prior_n_high_low` extension. The runtime proof confirms the installed Engineer
dispatcher ran ADX. It checks prior-high and prior-low values against an
independent oracle. It checks per-symbol inputs, warmup rows, source-row
preservation, input/output identity, and `available_at = timestamp + 1 minute`.
A mutation that uses future rows fails with `FEATURE_NUMERICAL_MISMATCH`.

[`feature_capability.json`](../../run_log/m8/feature_capability.json) records
the installed signatures, package identities, code hashes, proof hashes, and
runtime checks. The feature inputs are generated synthetic bars. This evidence
proves gateway plumbing only. It does not establish data-source readiness,
strategy semantics, or a result on the NAS100 CFD.

## Skills and invariants

The official ML4T skills catalog was loaded from
[`ml4t/skills`](https://github.com/ml4t/skills) at upstream `main` revision
`f0ea01919e0c517cd9b1e014724a520facd8a742`. No matching skill was installed in
the local skill paths. I read `compute-features`, `feature-validation`,
`lookahead-bias`, and `point-in-time` for this work. Their relevant invariants
are group-aware windows, no current or future bar in prior-range features,
explicit data availability, an independent numeric check, and no use of a
registered feature whose installed semantics do not match the request.

## Boundary

The original PDF is not available. The exact feature set for its rules is
unknown. Do not treat this proof as M8-B2 strategy certification. The next
decisive input is the original PDF, so the source pages and one rule can define
the actual feature request before a frozen trial.
