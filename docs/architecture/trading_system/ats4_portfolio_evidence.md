# ATS-4 daily sleeve evidence slice

`src.portfolio_evidence` provides immutable `SleeveIdentity`, `SleeveEvidence`,
`TrialDisclosure`, `RiskBudgetPlan`, and `PortfolioComparison` records. Supply
one sleeve per unique `strategy_id`; its full strategy version, spec/code hashes,
data snapshot, cost model, calendar, selection family, return basis and
denominator are retained in the result.

## Return and budget contract

Each sleeve declares `ReturnUnit.CAPITAL` or `ReturnUnit.RISK`, ISO dates, and
aligned gross, nonnegative execution drag, signed carry and net series. All four
series share the declared `return_basis_id` and a positive
`period_capital_denominator` for each date. The denominator may be a scalar,
broadcast to all dates, or a same-length tuple of actual per-date capital values;
the result retains the resolved tuple. Construction enforces
`net = gross - execution_drag + carry` within that common denominator. This
avoids manufacturing cost from independently compounded gross and net wealth.
For prior-net-equity denominators, a price-gross contribution is a same-period
return component on realized net capital; it is not an independently
capitalized no-cost gross-equity path. Accordingly, gross overlay outputs are
finite contribution series and are not independently compounded or used for
drawdown claims; equity-path validation and drawdown apply to net and stressed
overlays.
Positive carry may make net exceed gross. A capital-only sleeve can omit
`risk_fraction`; R-to-capital conversion and capital-to-R budgeting require the
caller to provide a positive risk fraction defined against that denominator.

`RiskBudgetPlan.budget_unit` is mandatory. `BudgetUnit.CAPITAL` weights are fixed
capital fractions and total at most 1. `BudgetUnit.RISK` weights are fixed
fractions of capital at risk and multiply the sleeve's explicitly converted R
return. Both use only caller-declared weights and risk units: there is no
optimizer, stop inference, or sizing recommendation. Baseline and candidate
weights and `periods_per_year` are retained in the result's complete `plan`.
Annualization is explicit (commonly 252 for exchange sessions or 365 for
calendar-day crypto); the caller must choose it. For a M8 sleeve and a cash baseline, pass both
as `SleeveEvidence` with the same exact dates and allocate their fixed capital
weights in the baseline tuple. A modeled zero-return cash baseline must be
identified as an assumption in its spec; do not report that assumption as an
observed cash return. An empty baseline weight tuple denotes a zero-return
reference overlay; it is not cash yield evidence.

The returned 1x/2x/3x stresses multiply execution drag only, preserve signed
carry, and are labeled fixed-exposure overlays; they do not re-execute trades.
Net and stressed capital paths must remain finite and strictly positive; gross
contributions must be finite but are not treated as independently capitalized paths.
Missing, duplicate, unsorted or unaligned dates are rejected; nothing is
intersected or zero-filled. `sleeve_loss_summaries` name each sleeve's down days
and loss severity. `pairwise_co_losses` separately report dates when both
members of each supplied pair lose and their summed loss severity. Candidate
overlay down days are reported separately from pairwise co-loss.

## Resampling, trials, and claim limits

Seeded paired block resampling samples common contiguous indices (block size
1..N, no wraparound) and applies those same exposed indices to every sleeve's
gross, drag, carry, net, candidate and baseline. Independent sleeve shuffles are
not used. The result retains indices, seed, and block size so callers can
reproduce the joint sample.

Every known attempt ID retains an outcome slot, including failed retries;
unknown count may be `None`, and missing known outcomes are explicit. Unknown or
missing history makes `selection_adjustment_allowed` false and appears in
`evidence_status`. Negative and inconclusive outcomes remain ordinary outcome
strings and do not lower evidence quality by themselves.

`barrier_claim_allowed` is always false. A daily return overlay has no raw
intraday path and is not a combined native account simulation; the result gives
both reasons explicitly even when input mark metadata says intraday-qualified.
It cannot establish path barriers, fills, account margin, netting, or execution
survival. Qualification booleans and hashes are caller self-attestations: this
module does not inspect source authority, verify hashes, or qualify costs,
carry, calendars, or marks.

When importable, `ml4t.diagnostic.api.PortfolioAnalysis(returns=...).compute_summary_stats()`
provides native total/annual return, volatility, Sharpe, Sortino, max drawdown,
VaR and CVaR; its status and values are returned separately. The independent
numerical audit compounds capital returns from initial wealth 1.0, so its
`audit_max_drawdown_initial_wealth` includes a first-day loss even where the
native summary's drawdown convention does not. Audit outputs also include
compounded return, empirical 5% tail loss and overlay loss days/severity. Native
statistics and the independent audit are diagnostics, not profitability or
deployment decisions.

## Qualified M8 evidence bridge

`src.engine.ats4_sleeves.demonstration` consumes three `NativeScenario` values
with native results and full independent reconciliation ledgers. It does not
invoke a second execution simulator. The event protocol supplies verified
source, calendar, cost, code and history identities. The reusable low-level
contract itself still cannot verify caller claims.

For the frozen M8 case, source, native portfolio state, native equity and oracle
ledgers must contain exactly the same timestamps. Pre-2020 warmup is verified
flat at 100,000 and excluded from the economic sample. Each of the 1,258 scheduled
2020-2024 dates uses its last actual native UTC-day mark, matching the historical
`m8_n8.summarize_n8_scenario` policy. The bridge does not invent an exact exchange
closing bar, interpolate prices, or fill missing dates with zero returns.
The native daily position must be flat; every planned fill remains inside the
frozen session rules. Thirty-minute source marks are not account-barrier evidence.

Daily price-gross PnL comes from source opens and actual native fill quantities.
Execution drag is adverse fill-price movement plus native commission. Gross,
drag and net use the same previous native NET equity denominator, with initial
capital 100,000. Their arithmetic reconciles to the native daily equity change.
M8 has no stop-defined risk unit, so `risk_fraction=None`; no R figure is invented.
Zero carry follows the no-overnight model, and the cash baseline assumes zero
yield and fees. Neither is a new observed-market-cost qualification.

The frozen comparisons are M8 capital fractions 0, 0.25, 0.5 and 1 with the cash
remainder. All are retained; no best allocation is selected. All native 1x/2x/3x
cost cases are retained as stresses of ONE strategy. Seed 42, five-date blocks,
and 100 draws yield the same paired indices for all M8/cash and cost cases.
Cash comparison is not empirical multi-strategy diversification evidence; the
independent identical/opposite-sleeve fixtures test the general co-loss and
joint-resampling behavior. Fixed-exposure cost overlays remain distinct from
the three authoritative native re-executions.

The event run persists `portfolio_sleeves.json` containing the cash record and
three cost-case records with exact dated components and denominators. Its hash
is recorded alongside native orders, fills, portfolio state and oracle ledgers.
Nonfinite native summary statistics for a constant cash path are serialized as
null with `undefined_native_statistics`; they are never converted to zero or
used to claim performance. All negative results and unknown trial outcomes
remain visible. See `docs/audit/ats4_qualification_20261016.md` for acceptance.
