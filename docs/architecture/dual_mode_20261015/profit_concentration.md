# Non-gating profit-concentration diagnostics

> Explanatory evidence only. This document does not authorize live orders,
> deployment, a new trial, a selection change or a protected-window read.

## Purpose

AF30 sleeve and qualified-portfolio runs persist a deterministic monthly
net-return breakdown, top-1/top-2 profit concentration and a richest-month
exclusion sensitivity. The diagnostic exists to expose headline metrics that are
carried by a small number of months. It is **not** a qualification gate and it
does not alter the seven gates, disposition, DSR family, trial ledger, weights or
the frozen portfolio rule.

## Artifact and provenance

For a sleeve:

```text
run_log/sleeves_advanced_futures_30/<class>/<sleeve_id>/profit_concentration.json
```

The sleeve `casefile.json` carries a `profit_concentration` summary with the
artifact sha256, source-frame hashes, availability and `gating: false`.

For a qualified-only portfolio:

```text
run_log/portfolios/<portfolio_id>/<class>/profit_concentration.json
```

The `portfolio_record.json` carries the same hashed summary. Instrument-level
attribution is explicitly `UNAVAILABLE` at portfolio scope because the portfolio
is a weighted sleeve-return composition; headline returns are not split
arbitrarily.

All diagnostics are computed on the already supplied development window and
record `holdout_access: false`. They never read a protected partition.

## Definitions

- **Calendar month.** UTC month of the daily net-return date.
- **Monthly net return.** `prod(1 + daily net return) - 1` inside the month.
- **Monthly net PnL (sleeve).** Last native daily equity in the month minus the
  prior month-end equity, or declared initial cash for the first month.
- **Primary concentration.** Sum of the `k` largest positive monthly net returns
  divided by the sum of all positive monthly net returns. This denominator is
  bounded and remains defined when losses offset profits.
- **Net-denominated concentration.** Top-`k` sum divided by the arithmetic sum of
  all monthly net returns. It is reported only when the denominator is positive
  and top-`k` does not exceed it. Otherwise the value is `null` with one of
  `NON_POSITIVE_NET_PROFIT`, `ZERO_NET_PROFIT` or `OFFSET_BY_LOSSES`. This
  prevents a ratio above one or a sign-flipped "share".
- **Ties.** Ranked by value descending, then month ascending; the earliest tied
  month is the richest.
- **Richest-month ablation.** Every daily net return in the richest calendar month
  is set to exactly `0.0`. The date axis, observation count and annualisation are
  unchanged. No trade, weight or price is re-simulated. The report gives
  before/after Sharpe, maximum drawdown and compounded cumulative return, plus
  deltas. A richest-two-month variant is included.
- **Interpretation.** `EXPLANATORY_ONLY_NOT_AN_EXECUTABLE_COUNTERFACTUAL`.
  Skipping a month is a sensitivity of the realised series, not an implementable
  strategy.

## Instrument attribution

For sleeve scope, per-symbol daily net PnL is reconstructed from native artifacts:

```text
net_pnl = prior_quantity * (close - prior_close)
        + signed_quantity_delta * close - signed_notional
        - explicit_commission
        + funding_cashflow
```

`close` is the last causal close on or before the UTC date. The native execution
price already contains declared slippage, so the fill `slippage` field is
provenance only and is not charged a second time. Commissions are explicit fill
fields. Funding is the native cashflow for the position that held it.

The symbol totals must reconcile to the native daily equity change within the
accounting tolerance. Missing marks for an open position, nonfinite values,
funding without a tracked position, duplicate marks or an unexplained equity
difference fail closed with `INVALID_EVIDENCE`/`INVALID_ACCOUNTING`. In a runner,
such a failure is persisted as `status: BLOCKED` for the diagnostic only; it
cannot become `PASS` and it does not rewrite the gate outcome.

## Limitations

- Monthly PnL is account-currency PnL, not a risk-adjusted attribution.
- The ablation is a realised-series sensitivity, not a re-run and not evidence
  that a month was predictable.
- Instrument attribution depends on native fill/funding/mark completeness. When
  those artifacts are absent, the diagnostic says `UNAVAILABLE`; it never
  allocates headline return by an assumed weight.
- The diagnostic does not correct for multiple testing, regime selection or
  exposure already observed in earlier research.
