# ATS-4 scientific protocols and operation

**Status:** Implemented core with one historical event protocol partially
qualified. This does not qualify broker execution, intraday account barriers,
protected evaluation, or trading approval.

## Protocol boundary

`CandidateSpec` keeps its existing serialized fields and `spec_hash`. An
unmarked candidate continues through the current cross-sectional funnel. A
separate strict spec has an explicit `protocol: event` discriminator and only
allows `strategy_id: m8_n8_cash_session_v7`; unknown protocols, strategies, and
extra fields fail closed. The typed protocol descriptors distinguish
cross-sectional, event, and path-dependent evidence. The generic path-dependent
descriptor does not assert that stops, targets, or intraday marks are qualified.

Factory and Workbench use the same M8 implementation. Factory dispatches event
protocols before the cross-sectional allocator, IC/HAC, neutrality, beta, and
short-stop gates. Workbench supports event `load`, `features`, `backtest`, and
`export_yaml`; `ic` records a rejected inapplicable request. Event backtests
remain development-only and never unlock a protected partition.
Typed event objects are revalidated at dispatch, including Pydantic models made
with unchecked construction/copy operations. Cross-sectional Workbench imports
defer the frozen M8 native adapter until event execution.

## M8 N8 authority and behavior

The exact rule is `close[t] > max(high[t-50:t])` after a completed 30-minute
bar, enter at `t+1` open, exit at `t+2` open, one normalized long unit, no
overlapping position, no overnight holding, no stop or target. XNAS session
eligibility includes DST and scheduled early closes. The independent signal
oracle computes the prior-high rule from source bars; a separate execution
oracle applies the one-position lifecycle. Session eligibility uses the frozen
calendar predicate; literal UTC DST and early-close fixtures in
`tests/test_m8_cash_calendar.py` provide the independent clock regressions.
Missing scheduled entry or exit bars block the study instead of dropping signals.

The source bridge is deliberately narrow: it checks Parquet footer bounds and
row count before decoding, validates the frozen source SHA-256 and schema, then
loads only the already-observed 2019 warmup through 2024 development data. It
binds to the frozen v7 session, feature contract, cost assumptions, calendar,
and historical result manifest.

The integration source authority is a preserved, read-only copy outside Git
worktrees at
`/home/quant/dev/quant/research_artifacts/ats4/20261016/source/prices_30m.parquet`,
SHA-256 `36e6a5dd5e16feb21ba5828ed306dc32c703d74143692dce1019322a52d159c8`.
The historical 2026-10-16 report retains the original worktree source path as
historical provenance; current execution no longer depends on that worktree.
The untracked qualification artifacts are copied to the sibling
`evidence/` directory (38 retained files, including both JUnit reports).
Provision this same authenticated source at the documented read-only path on
another host before running real replay; never substitute a different panel
or bypass the strict frozen-source hash check. Source data and bulk evidence
are intentionally excluded from source commits. Native ML4T Backtest runs all three frozen cost
scenarios. The independent oracle checks every expected and executed signal.
`reconcile_m8_n8` checks native submitted orders, fills, rejection/pending state,
portfolio cash/exposure/open positions, and every source-row portfolio/equity
mark. Orders, fills, cash/position ledgers, and portfolio-state rows are stored
as separate Parquet artifacts; compact per-scenario reconciliation summaries
stay in event evidence. New fills/equity are compared exactly with persisted
historical artifacts and metrics. Every output artifact is content-hashed in
the run evidence. Event identity binds reused research-control sources,
portfolio evidence, CLI, lockfile, native packages and calendar before and
after replay; a changed identity fails the run.

The recorded result is `PARTIALLY_QUALIFIED`: exact rule and historical parity
pass; the frozen economic decision remains falsified; costs remain assumptions,
and native marks reconcile at the 30-minute source-close cadence; intraday
account barriers remain unqualified. The 2020–2024 sample was already observed.
Verified history inventories nine frozen sessions: six records with native
attempt identities (including failures before engine launch), two preflight-only
records, and one earlier freeze-only record with no established outcome. It binds
six trial records and seventeen lifecycle events without treating those counts as
independent strategy selections. The missing outcome remains null; wider selection
history remains unknown. There is no DSR, new train/validation split, or out-of-sample claim. Factory
attempts remain separately linked from the hash-chained append-only trial ledger,
including prior failures and the current registration. The no-trade cash baseline
is $100,000 initial/final equity with zero return. No protected data was loaded.

The panel has 1,127 eligible signals, 805 executed round trips, 1,610 orders and
1,610 fills per cost scenario. All 57,504 source-row native cash, position,
exposure and equity marks reconcile in each scenario. Historical fill and equity
tables match exactly; independent arithmetic differs only by floating-point
rounding (maximum cash error approximately 1.05e-9 normalized currency units).

The real sleeve bridge completes for all 1,258 scheduled evaluation dates. It
preserves the frozen study's valuation policy in `m8_n8.summarize_n8_scenario`:
use the last actual native mark on each scheduled UTC date. An earlier bridge
iteration incorrectly demanded an exact XNAS closing bar and blocked
2023-11-24. That extra requirement was removed because it was not the historical
contract. No price, cash or return was interpolated. A missing scheduled date,
missing native/oracle source-row mark, or a nonflat daily valuation still fails.
This daily evidence cannot authorize intraday barriers.

`portfolio_sleeves.json` retains four immutable evidence records: modeled cash
and the same M8 strategy under three native cost assumptions. They are not four
independent strategies. Fixed 0%, 25%, 50% and 100% M8 capital overlays use the
cash remainder; no weights are optimized. Paired five-date blocks use seed 42
and 100 draws with identical indices across cases. The M8 sleeve has no declared
R-risk unit. Costs, carry, cash yield, and diversification limitations remain
explicit. Undefined native cash-baseline statistics are null with named reasons.

The native source identities and versions are included in each event evidence
report. Inspected runtime APIs in the verified environment:

```text
ml4t-backtest==0.1.7
Engine(feed, strategy, config=None, *, contract_specs=None, market_impact_model=None,
       execution_limits=None, lifecycle_version=LifecycleVersion.V1,
       execution_policy=None, target_intent_state=None)
ml4t-diagnostic==0.1.6.post2
PortfolioAnalysis(returns, benchmark=None, positions=None, transactions=None,
                  dates=None, risk_free=0.0, periods_per_year=252)
ml4t-engineer==0.1.4
compute_features(data, features, *, group_col=None, timestamp_col=None,
                  assume_sorted=False)
```

Engineer `maximum` is not used for the prior-high signal: its managed contract is
close-only. The existing approved `prior_n_high_low` feature route supplies the
high-price window and completed-bar availability.

## Remaining limits

- Historical spread, impact, financing, broker lot conversion, and executable
  CFD PnL are not qualified. Cost statuses remain `ASSUMED_NOT_QUALIFIED`.
- Thirty-minute source-close equity marks reconcile; the artifacts do not establish intraday marks
  suitable for account barriers or prop-firm drawdown transitions.
- The requested XNAS calendar resolves to XNYS in the installed calendar
  package; it is not independent evidence of Dukascopy historical execution
  hours.
- The adapted source is a CFD price proxy, not CME NQ futures. The source PDF
  binary is not present; the extracted pages and frozen rule references remain
  the available rule authority.

## Operation and verification

Use the locked environment. In the qualification VPS, `env` on PATH was a
no-op shadow; `/usr/bin/env` is therefore explicit. The verified interpreter is:

```sh
PY=/home/quant/.devspace/worktrees/quant-research-25440f7a/.venv/bin/python
/usr/bin/env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 POLARS_MAX_THREADS=2 \
  "$PY" scripts/quant.py validate config/candidates/ats4_m8_n8_cash.yaml
/usr/bin/env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 POLARS_MAX_THREADS=2 \
  "$PY" scripts/quant.py run config/candidates/ats4_m8_n8_cash.yaml \
  --run-log run_log/ats4_verification/public_cli
```

A completed run returns CLI code 3 with `PARTIALLY_QUALIFIED`, not an engineering
failure or trading approval. Its printed casefile points to hash-bound native
artifacts, independent ledgers, event sequences, source/runtime identity, known
history, and sleeve evidence. `--build-if-missing` cannot rebuild this frozen
source. Factory and Workbench share `run_m8_n8_event`; Workbench's event `ic()`
rejects the request without needing market data.

```sh
/usr/bin/env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 POLARS_MAX_THREADS=2 \
  "$PY" -c 'import sys,pytest; sys.exit(pytest.main(sys.argv[1:]))' \
  -o addopts= -q tests/test_dual_mode_*.py tests/test_m8_*.py \
  tests/test_managed_feature_policy.py tests/test_ats4_*.py \
  --junitxml=run_log/ats4_verification/final_regressions.xml
```

The qualification run collected 187 tests: 186 passed and one existing real-store
smoke test skipped because its explicit BTC/ETH canonical build was absent.
All 75 ATS-4 tests passed, including the real three-scenario event replay and
sleeve bridge. See `docs/audit/ats4_qualification_20261016.md` for identities,
acceptance scope, independent review, and integration requirements.
