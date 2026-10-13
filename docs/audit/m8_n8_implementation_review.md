# M8 N8 implementation and freeze record — 2026-10-13

## Authority and selection

The frozen research-lead decision selects one candidate: Nesnidal Model 8,
page 7, adapted as a Dukascopy NAS100 CFD price proxy. It is a retrospective,
price-only study of the already observed 2020-2024 source range. It is not CME
NQ futures, a pristine out-of-sample test, broker PnL, or trading approval.

The original 12-page PDF SHA-256 supplied by the research lead is
`b947c5aeaee61da3c8bf660b410b10bb25f5af74b53facc8f04d9a486658b526`. The
original PDF bytes are not in this worktree. The page-separated text transfer
is `run_log/m8/original_rulebook_extracted_pages.txt`; its SHA-256 is recorded
in the frozen session evidence. The supplied PDF hash was not reverified from
binary bytes in this worktree.

The strategy is long-only. It tests the strict rule
`close[t] > max(high[t-50:t])` after the completed 30-minute bar. It submits a
native market order for the next open and a native market exit for the
following open. There are no stop or target orders. The normalized baseline is
one $1-per-index-point research unit with $100,000 illustrative cash and no
leverage. The exact broker lot multiplier is unknown.

## Source, bars, sessions, and costs

The canonical catalog key is `index_minute_NQ`; its resolved source symbol is
`usatechidxusd`, a Dukascopy NAS100 CFD series. The implementation rejects a
different catalog identity. It reads minute files only through 2024-12-31 UTC,
with December 2019 used only for feature warmup. It does not read any 2025 data.
The 30-minute Parquet has 57,504 complete bars from 1,744,795 source minutes
across 1,584 daily files. Each retained bar has exactly 30 unique, contiguous
minute bars. A separate Python oracle checked every aggregate. Source and
derived-file hashes are in `run_log/m8/n8/source_fingerprints_recovery.json`.
The pre-recovery fingerprint file is preserved unchanged.

Eligibility does not inspect future bar presence. It uses the research-lead
summer/winter GMT hours, the XNAS weekday holiday calendar from
`exchange_calendars==4.13.2` as a conservative known-holiday filter, and a
complete-bar boundary rule. Signal, entry, and exit intervals must be wholly
inside the published schedule. After signals are frozen, missing scheduled
fill bars block the full trial as `EXECUTION_EXCEPTION`; the runner does not
drop those signals. Dukascopy special-holiday hours and early closes are not
available as a historical machine-readable source. Those cases remain a
limitation and fail closed when they create a missing selected fill.

Each fill includes 3 bps adverse price slippage/spread assumption plus 0.6 bps
explicit native percentage commission. The same components scale to 2x and 3x.
The commission evidence cites the lead-provided Dukascopy fee schedule and
rounds USD 52.5 per USD 1 million up to 0.6 bps per side. The spread and
slippage values are assumptions, not verified quotes. The official instrument
page citation and the $1/point arithmetic normalization do not establish this
source's broker lot conversion, margin, or executable PnL.

## Managed path and independent checks

The pilot runner requires the frozen ResearchContractV1, a real `preflight_run`
against the frozen session root, an identity-bound `RunPermitV1`, and an
append-only `AttemptLedger` reservation before it creates the named tmux job.
It uses the installed `ml4t-backtest==0.1.7` engine in next-bar mode. The native
result is audited for fill side, size, open price, timestamps, slippage,
commission, zero ending position, and cash/marked-position equity at every
engine mark. This arithmetic is an independent audit oracle; it does not
replace the native engine.

The gateway admits only `1m` and `30m`. Its 30m proof records availability at
the completed bar close. The approved `prior_n_high_low` extension computes a
strict prior 50-bar high with full warmup, partition isolation, numerical
oracle, and future-row mutation checks. Native `donchian_channels` is not used.
Missing or invalid feature proofs block preflight; proof exceptions are never
swallowed.

Trade count, win rate, expectancy, and total PnL come from native engine
metrics. Daily returns use the last native equity mark per scheduled UTC CFD
trading date, including Sundays. Open dates without a trade have zero returns;
schedule-closed dates are omitted, and a missing mark on an open date blocks.
The installed `ml4t.diagnostic.api.PortfolioAnalysis` computes Sharpe, annual
return, maximum drawdown, and Calmar at 252 periods per year. This is a
convention for the six-day broker schedule, not a claim about the literal
annual count of sessions. An independent sample-variance, wealth-path, and
Calmar arithmetic check runs against the API outputs. Undefined values
remain null. Intraday engine Sharpe is not reported. There is one declared
primary candidate; the three cost levels are a fixed stress set, not a
parameter search. No DSR or pristine OOS claim is made from incomplete legacy
trial history.

The result runner retains native fill/equity tables and a hash manifest. A
completed-artifact re-entry first recomputes the current permit, then requires
an exact attempt, permit, session, trial, code/config/data identity, and all
three cost scenarios. It reads every Parquet table, checks native fills/equity
columns and row counts, and requires an independent audit `PASS` for each
scenario. Wrong identity, fake or truncated Parquet, incomplete tables,
missing audit, and tampered bytes fail closed. Active or uncertain jobs block
duplicate execution. A vanished worker remains `LEASE_UNCERTAIN` until its
lease expires. After tmux confirms absence, its attempt becomes terminal
`ABORTED`; a retry receives a distinct, counted attempt ID. Same-attempt
interrupted replay is not supported because it would reopen a terminal attempt
and violate the control-plane contract. A completed artifact can be reused
only after full permit and native-table validation. The run permit validates one January 2020
exit-clock anchor. Runtime independently enumerates the full frozen evaluation
signal set and validates actual t+1/t+2 bars, native fills, and every native
equity/cash ledger row. The permit is not represented as per-fill coverage.

## Method references and verification

No matching local ML4T methodology skills were installed. The following
official ML4T skills were read in full from upstream revision
`f0ea01919e0c517cd9b1e014724a520facd8a742`:

- `data/build-bars` and `data/validate-data` for complete 1m-to-30m aggregation,
  continuity, OHLC validation, and independent bar checks.
- `features/compute-features`, `features/feature-validation`,
  `concepts/lookahead-bias`, and `concepts/point-in-time` for strict prior-bar
  semantics, warmup, grouping, and completed-bar availability.
- `backtest/run-backtest`, `backtest/cost-model`,
  `concepts/transaction-costs`, and `concepts/backtest-overfitting` for native
  next-open execution, explicit component costs, cost stress, and frozen trials.
- `advanced-ai/agent-state-memory`, `advanced-ai/agent-tool-contracts`, and
  `advanced-ai/research-operator` for immutable identity, attempt evidence, and
  recovery limits.

Their invariants are checked by the candidate-specific tests below, native
preflight, the source fingerprint, and the independent fill/cash audit. A skill
description alone is not treated as evidence of correctness.

Focused pre-freeze verification (after final acceptance corrections):

- `uv run ruff check src/research_control scripts/run_m8_n8.py scripts/prepare_m8_n8_data.py tests/test_m8_n8_execution.py tests/test_m8_n8_recovery.py tests/test_m8_agent_qualification.py tests/test_attempts.py` — clean.
- M8 and managed-control regression set (`tests/test_attempts.py`, `tests/test_casefile.py`, `tests/test_agent_efficiency.py`, `tests/test_m8_agent_qualification.py`, the N8 data/execution/recovery tests, feature capability, and research-control tests) — 72 passed.
- `uv run python -m pytest -q` — 276 passed, 1 skipped.
- Repository-wide `uv run ruff check .` reports 603 pre-existing findings across unrelated files. The task-owned Python files pass the scoped Ruff command above; unrelated files were preserved.
- Synthetic native-engine execution confirms next-open entry, following-open exit, 3 bps adverse slippage, 0.6 bps commission, and independent cash/equity reconciliation. It is an implementation fixture, not an N8 candidate result.

The single frozen session and its intent, cost evidence, multiplier limitation,
calendar rule, source fingerprints, and declared trial are stored in
`run_log/research_sessions/m8_n8_dukascopy_nas100_cfd_30m_v1/` and
`run_log/m8/n8/`. The 2025+ holdout stays unopened. No real orders are sent.
