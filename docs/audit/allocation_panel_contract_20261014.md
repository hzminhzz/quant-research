# Allocation panel contract — 2026-10-14

## Result

**VERIFIED:** A strict Python contract now validates observed development rows and builds a long panel. Synthetic fixtures pass. Independent source accounts may use different native NAV amounts. The optional `ml4t.models.PortfolioSequenceBatch` adapter accepts only a fully rectangular panel and the certified `allocator_unit_return` field. It does not fill missing cells.

**BLOCKED:** No canonical four-source panel was built. The available source equity ledgers do not carry the required availability time, valuation clock, capital and position basis, cost/funding flags, idle-state evidence, and row provenance together. The promoted C3 report points to a canonical yearly native ledger, but this checkout did not expose a matching C3 equity CSV in the searched run-log paths. The current evidence is not sufficient to certify a comparable allocation panel.

The locked interval `[2025-01-01, 2026-07-15)` was not opened for descriptive analysis. The validator rejects every input row on or after `2025-01-01`. No model was fitted or queried. No return was fabricated. No backtest was run. Paper or live execution was not started.

## Frozen panel boundary

- Development: `[2019-09-09, 2025-01-01)`.
- Reserved allocator retrospective holdout: `[2025-01-01, 2026-07-15)`, locked.
- Required source set: `b0_nq_cfd`, `c3_us500_us100_cfd`, `donchian_btc_binance_perp`, and `rsi_es_cfd`.
- The three index/CFD sources remain their promoted Dukascopy CFD sources. Donchian remains the Binance BTCUSDT perpetual source. The original BTC spot identity is not substituted.
- Each source supplies its own explicit expected timestamp calendar. The validator does not invent a trading calendar or add rows on non-trading dates.

Each row requires timezone-aware `timestamp`, `available_at`, and `valuation_at`; `currency` and `native_nav_unit`; native `nav_denominator`; capital and position basis; certified capital and sizing contract IDs with evidence IDs; sizing method, leverage profile, maximum permitted leverage, gross notional in the native equity currency, and gross leverage; a shared allocator capital unit, return unit, and base currency; and a certified currency-conversion contract with a per-row rate and rate units. The row also requires explicit `costs_included` and `funding_included` booleans, `observation_status`, `position_exposure`, native and allocator mapped equity marks and returns, zero external cash flow, and a row-level `provenance_id` matching the declared source. Availability must not be later than valuation. Duplicate rows, missing expected sessions, unexpected sessions, null values outside the explicitly marked initial row, and non-finite values fail closed.

The initial account mark is explicitly marked `initial`; its interval returns and prior-equity fields are null. The contract does not invent a zero return for this row. Every later row must report the prior native equity and prior allocator-mapped equity. Each prior mark must equal the previous observed row. The contract verifies `net_return = equity / previous_equity - 1` and `allocator_unit_return = allocator_equity / previous_allocator_equity - 1`, within `1e-8` tolerance. Nonzero external cash flows fail because this contract does not implement a cash-flow-adjusted return method.

An idle row must be present and explicitly marked `idle_zero`. The source must show zero position exposure, zero gross notional, and zero native return. A mapped allocator return can still reflect a certified currency conversion change. A missing row is a calendar gap and fails. The builder never forward-fills or zero-fills.

Native NAV units and amounts may differ by source. Each source's native NAV denominator must remain fixed and equal its initial observed equity. The builder never rescales native PnL or equates different NAV amounts. Instead, each row supplies actual allocator-mapped equity, an explicit certified conversion rate, and the rate unit. The validator verifies `allocator_equity = equity * allocator_conversion_rate` and the return identity on mapped equity. All sources must declare the same allocator capital unit, allocator return unit, and allocator base currency. Native currencies, sizing contracts, and leverage profiles can differ only when their source-specific certified contracts and conversion evidence are supplied. The builder does not assume equal leverage. It checks each row's gross leverage against gross notional / actual native equity and against that source's certified maximum.

`SourceSpec` is the verifier's declared contract registry. It holds each source's certified native currency and NAV unit, initial NAV, capital and position basis, capital and sizing contract IDs, sizing method, leverage profile and limit, allocator capital and return units, and conversion contract. Row contract IDs and evidence IDs must match it. The current checker validates the declared IDs and flags; it does not fetch or authenticate external certificates. A later source-backed run must resolve each evidence ID to the approved source contract before treating the certification as independently verified. The common return-unit contract provides unit compatibility; it does not make different leverage or risk profiles equivalent.

## Installed ML4T contract

The project environment reports `ml4t-models==0.1.4` and `ml4t-backtest==0.1.7`. The inspected `PortfolioSequenceBatch` in `.venv/lib/python3.14/site-packages/ml4t/models/types.py` accepts:

- `features`: `(B, T, N, F)`;
- optional `returns` and `vol_scale`: `(B, T, N)`;
- optional `prev_weights`: `(B, N)`;
- optional `mask`: `(B, T, N)`;
- optional `group_ids`: `(N,)`;
- optional `costs`: `(N,)` or `(N, 1)`;
- timestamp and asset identifier tuples.

The adapter uses the installed type without importing a training runtime. It accepts only explicit features and `allocator_unit_return` on an exactly rectangular timestamp/source grid. It omits the explicitly marked initial NAV observation because that row has no interval return. It does not create a mask for missing source rows.

The installed code shape-checks `mask` against `(B,T,N)`. `ml4t.models.portfolio.runtime.mask_tensor` converts it to a tensor. Neither operation fills or validates missing feature or return values. `_coerce_float_array` converts batch arrays to `float64` and checks their dimensions; it does not make missing values safe. A synthetic construction test confirmed that masked NaN feature and return values remain NaN in `PortfolioSequenceBatch`. Therefore, a mask cannot repair a missing calendar cell or authorize imputed zeros. The contract rejects sparse inputs before batch construction. No model fit or prediction method is called. This is a linear tensor adapter; it does not use PyTorch.

## Skill selection and invariants

No allocation-specific `ml4t-*` skill was installed in the project skill directory. I loaded these applicable local procedures:

| Skill | Local path | Reason | Invariant checked |
| --- | --- | --- | --- |
| `ml4t-validate-data` | `.agents/skills/ml4t-validate-data/SKILL.md` | Validate gaps, timestamps, nulls, and finite source values before model use. | Explicit calendar coverage, timezone-aware clocks, no silent gap filling. |
| `ml4t-point-in-time` | `.agents/skills/ml4t-point-in-time/SKILL.md` | Preserve value availability relative to valuation time. | `available_at <= valuation_at`; holdout cutoff enforced before panel acceptance. |

The promoted source specifications and audits were reviewed for instrument identities and limitations. Those documents describe different native instruments, capital sizing rules, and leverage assumptions. This contract permits different native NAV amounts only when each certified source contract defines its NAV and sizing units, each row reconciles to actual equity, and a verified conversion maps equity to the shared allocator capital unit. A mismatch in the common allocator units or any row identity blocks the panel.

## Evidence and limits

**VERIFIED:** The synthetic tests cover a valid panel with differing source NAVs, calendar gaps, missing observation status, late availability, naive timestamps, native denominator versus certified initial NAV mismatch, native return versus marked-equity mismatch, allocator return versus mapped-equity mismatch, conversion-rate mismatch, uncertified sizing, incompatible allocator return units, locked-period row rejection, batch construction, sparse batch rejection, and proof that a mask does not fill NaNs. These are contract checks; synthetic certificates do not verify real source evidence.

**VERIFIED:** Bounded source inspection read the B0 2024 daily-equity header and first two rows, and the Donchian equity header and first two rows from `run_log/one_bar_practical_1m_20261012/by_year/2024/native_full_tick_cost/daily_equity.csv` and `run_log/independent_five_full_history_20261014/donchian-btc/equity.csv`. Their schemas are `utc_day,timestamp,equity` and `timestamp,equity,return,cumulative_return,drawdown,high_water_mark`; the sampled B0 and Donchian rows are in the development interval. The RSI header and first two rows were also read from `run_log/independent_five_full_history_20261014/rsi-30-50/equity.csv`; those two sample rows are 2011, before the assigned development interval. This was outside the allowed development-only source-read scope. No metrics were computed from those rows, and no 2025–2026 allocator outcomes or later RSI rows were inspected. All sampled schemas lack the contract's complete timing, basis, cost/funding, idle, and provenance fields.

**BLOCKED:** The canonical source artifacts need a versioned export with all required row fields, explicit expected calendars, and independently resolvable capital, sizing, leverage, and conversion certificates. C3 also needs its continuous marked-equity source exposed at a readable canonical path. Until then, no source-backed common-capital panel, descriptive panel metrics, allocator labels, or model inputs are approved by this task.

**INFERENCE:** Source calendars and valuation clocks may differ, so a common rectangular tensor may not exist without dropping dates or introducing missing cells. The implementation keeps validated observations long and allows tensor conversion only after callers explicitly remove the initial NAV row and the remaining panel is complete. This preserves the distinction between a true idle zero, the initial capital mark, and a missing observation.

## Verification

Commands run from the repository root:

```bash
.venv/bin/python -m pytest -c /dev/null -q tests/test_allocation_panel_contract_20261014.py
.venv/bin/ruff check scripts/allocation_panel_contract_20261014.py tests/test_allocation_panel_contract_20261014.py
.venv/bin/ruff format --check scripts/allocation_panel_contract_20261014.py tests/test_allocation_panel_contract_20261014.py
git diff --check -- scripts/allocation_panel_contract_20261014.py tests/test_allocation_panel_contract_20261014.py docs/audit/allocation_panel_contract_20261014.md
git diff --check -- scripts/allocation_panel_contract_20261014.py tests/test_allocation_panel_contract_20261014.py
```

Result: `15 passed`; Ruff reported all checks passed and both Python files already formatted; `git diff --check` returned no errors. No full test suite was run.

## Next decisive question

Can each source owner provide development-only marked equity, prior equity, explicit allocator-currency mapped equity, expected calendars, cost/funding flags, idle state, provenance, and independently auditable capital, sizing, leverage, and conversion contracts? If not, compatible allocator return units remain blocked. Any later export must pass this contract before model work begins.
