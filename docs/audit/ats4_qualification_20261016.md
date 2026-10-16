# ATS-4 qualification record - 2026-10-16

## Acceptance decision

**Implementation and retrospective native-parity acceptance: PASS. Overall scientific/market qualification: PARTIALLY_QUALIFIED.** The existing cross-sectional route is preserved and one documented event strategy now has a native-backed, independently reconciled protocol. This is not approval of a profitable strategy, executable broker costs, a new out-of-sample result, generic stop/target protocols, portfolio account barriers, or trading operations.

The task was isolated on `feat/ats4-scientific-protocols` in `/home/quant/.devspace/worktrees/quant-research-25440f7a-13e55b9b`, based on `368d8f00beb5e51ac1f0e5215a339c770198c1ee`. Source checkout and concurrent ATS worktrees were not edited. No protected market outcomes were accessed, no trading operation was initiated, and no push or merge was authorized or performed.

## Reproducibility identities

| Identity | Verified value |
| --- | --- |
| Candidate | `m8_n8_cash_session_v7` |
| Explicit protocol | `event` |
| Spec SHA-256 | `191c733ff48ad08cd4d4fd9e640575f19d1791a48fe04f619a759c2e919f61aa` |
| Event runtime identity | `31a2eb9ae2d6ead8fe44850eb4ff702d6e10ec2ebabd5ff936616c3a67e0612d` |
| Common runtime identity embedded in event identity | `d1411b87d087b423e99ad8095d78088ac380525b6466c4cea02350663153d930` |
| Raw source SHA-256 | `36e6a5dd5e16feb21ba5828ed306dc32c703d74143692dce1019322a52d159c8` |
| Frozen history manifest SHA-256 | `ab27aa00ef40f3ab4e0b9e13924cd76802d2c9290482d0f00865cf077e217c6f` |
| Historical authoritative attempt | `e908ef2f-0d1d-44f4-a484-0203b616cbb4` |
| Historical report SHA-256 | `2d38aa080263c56df2f6ea4bd74e003fa567bd5cb8613380fd8c9fc37cedbc4b` |
| New public-CLI attempt | `20261016T084316-3ac05c3204` |
| Locked ML4T packages | Backtest `0.1.7`; Diagnostic `0.1.6.post2`; Engineer `0.1.4` |
| Calendar package | `exchange-calendars==4.13.2`, requested XNAS, resolved XNYS |

The event identity includes the unchanged common source identity plus reused research-control source files, portfolio evidence, CLI, lockfile, installed native Python source hashes and calendar source hashes. Full per-file hashes and inspected API signatures are retained in `event_evidence.json`. Identity before and after the native replay was equal. A commit changes Git identity but not these content identities when runtime sources are unchanged.

The immutable development source remains in the historical worktree:

```text
/home/quant/.devspace/worktrees/quant-research-c0f474ba/data/research_sessions/m8_n8_dukascopy_nas100_cfd_30m_v1/prices_30m.parquet
```

Its 57,504 rows span warmup beginning 2019-12-01T23:00:00Z through 2024-12-31T23:30:00Z. The economic interval is `[2020-01-01, 2025-01-01)`, already observed. Footer bounds, schema, count and source hash are checked before market rows are decoded. This bridge does not discover new datasets or grant protected-window access.

## Real strategy and reconciliation

M8 N8 uses strict `close[t] > max(high[t-50:t])`, next-open long entry and following-open exit, one normalized unit, initial capital 100,000, no overlapping positions, stop, target or overnight holding. Existing feature, calendar, signal, sizing, cost and sample-boundary contracts are unchanged. Raw prior highs include the original provider bars; there is no new cash-only lookback filter.

The bar label is the interval start. A decision using the completed bar is available at its end. The native order's label and semantic information-availability time are recorded separately; the exit decision is available at the following bar end. The pinned engine's order IDs and timezone-stripped dataframe clocks are explicit qualification constraints.

| Evidence, per cost scenario | Observed |
| --- | ---: |
| Eligible causal candidate signals | 1,127 |
| Executed one-position round trips | 805 |
| Native orders / fills | 1,610 / 1,610 |
| Source / native portfolio / native equity marks | 57,504 each |
| Scheduled daily valuation observations | 1,258 |
| Historical fill-table equality | Exact |
| Historical equity-table equality | Exact |

The independent arithmetic oracle does not call the production audit to construct expected prices or balances. It checks native order asset/type/status/quantity/price/creation/fill timing, pending and rejected state, native fills, cash, position-derived exposure, open positions, native portfolio equity and native equity at every source row. The maximum absolute cash differences are `8.731149137020111e-10`, `6.257323548197746e-10`, and `1.04046193882823e-9` normalized currency units for 1x/2x/3x. Maximum fill-price error is `3.637978807091713e-12`; quantity and exposure errors are zero. These are floating-point reconciliation differences, not differences from the historical tables, which match exactly.

| Native cost assumption | Adverse price impact / commission per fill | Net PnL, normalized research units | Final equity |
| --- | --- | ---: | ---: |
| 1x | 3 bps / 0.6 bps | -6,082.949970604313 | 93,917.05002939569 |
| 2x | 6 bps / 1.2 bps | -14,441.236859295866 | 85,558.76314070413 |
| 3x | 9 bps / 1.8 bps | -22,799.523666075343 | 77,200.47633392466 |

The frozen economics status remains `FALSIFIED_NONPOSITIVE_GROSS_OR_BASE_NET_EXPECTANCY`. Native gross PnL already includes adverse fill-price impact and excludes commission; it is not the bridge's price-gross PnL calculated from raw source opens. Values are normalized at one research unit per index point, not verified broker PnL or lot sizing. No parameters or allocations were selected to improve this result.

## Scientific acceptance matrix

| Requirement | Result and evidence |
| --- | --- |
| Cross-sectional schema, hash and execution behavior | PASS: unchanged CandidateSpec serialization/hash; legacy dual-mode regressions passed. |
| Appropriate gate routing | PASS: event dispatched before cross-sectional allocation, IC/HAC, beta, neutrality and short-stop checks; forbidden-call fixtures include the funnel's imported call sites. |
| Native feature and execution use | PASS: existing managed feature gateway and ML4T Engineer/Backtest/Diagnostic APIs, with installed signatures and versions recorded. |
| Signal causality and fill timing | PASS: independent prior-high and execution-lifecycle oracles; lookahead and same-bar mutation fixtures. |
| Calendar and DST | PASS for frozen schedule: literal UTC golden fixtures include DST, early close and protected-boundary cases. Provider execution-hours authority remains limited. |
| Order/fill completeness | PASS: missing, duplicated, wrong-side/asset/type/quantity, rejected and pending-order fixtures; full native scenario reconciliation. |
| Cash, position, costs and equity | PASS under frozen assumptions: independent full-mark arithmetic, isolated portfolio-equity and cash mutations, commission and timing mutations. |
| Data and evidence integrity | PASS: frozen hashes, predecode bounds, strict identity/schema, missing/changed authority rejection and runtime drift guard. |
| Daily valuation fidelity | PASS: last actual native mark per scheduled UTC date, as in the historical study; no interpolation or zero-filled missing dates. |
| Portfolio evidence | PASS for daily fixed-weight evidence: same-denominator components, exact alignment, initial-wealth drawdown, tails, pairwise co-loss, explicit risk-unit conversions and shared block indices. |
| Known trial accounting | PASS within disclosed scope: nine freezes, six attempt identities, two preflight records, one freeze-only unknown outcome, six trial records and seventeen lifecycle events. Wider history unknown. |
| Realistic observed execution costs / CFD multiplier | NOT QUALIFIED: historical assumptions, not observed spreads, broker fills or financing. |
| Fresh OOS or selection-adjusted inference | UNAVAILABLE: 2020-2024 already observed; incomplete wider history and one missing known outcome. |
| Generic stop/target or intraday account-barrier protocols | UNSUPPORTED: descriptor/seam does not certify these capabilities. |
| Trading authority | NONE. |

## Portfolio evidence and the valuation correction

The completed bridge preserves all 1,258 scheduled dates and consumes reconciled native state rather than reconstructed equity alone. Raw-open price-gross PnL, adverse slippage plus actual native commission, zero modeled carry and net PnL share the SAME preceding native NET equity denominator. Initial denominator is 100,000. M8 has `risk_fraction=None`: a stop-based R denominator is not invented.

An intermediate bridge demanded the exact XNAS closing bar and blocked 2023-11-24. Review of the immutable `src/research_control/m8_n8.py` daily valuation established that this was an added requirement, not the frozen protocol. The final bridge uses the last ACTUAL native mark on each scheduled UTC date, verifies it is flat and reconciled, and records the exact timestamps. A whole missing scheduled date or missing native/oracle row still blocks. No missing exchange-close price was synthesized. The independent final reviewer confirmed this correction against the historical implementation. A daily mark is not evidence for intraday account barriers.

The baseline is explicitly modeled zero-yield, zero-fee cash. Candidate capital weights are frozen at 0%, 25%, 50% and 100%, with the cash remainder, all reported without optimization. The three cost runs are stresses of one strategy, not diversified sleeves. Native 1x/2x/3x re-executions are distinguished from fixed-exposure drag overlays. Seeded paired resampling uses common five-date blocks, seed 42 and 100 samples. Synthetic identical/opposite sleeves demonstrate dependence preservation; M8 versus cash does not establish multi-strategy diversification. Undefined constant-cash native statistics are null with named fields, never performance zeros.

Historical metric text referring to Sundays/six-day CFD annualization is inherited from the old shared summarizer and retained for immutable parity. The new sleeve report states the actual XNAS scheduled-date sampling and explicit 252-period convention. No historical report was rewritten.

## Tests, review and retained evidence

- Full native/JIT-enabled main-workspace regression: **186 passed, 1 skipped, 0 failures, 0 errors**, 187 collected, 229.107 seconds. JUnit: `run_log/ats4_verification/final_regressions.xml`.
- The skip is `tests/test_dual_mode_real_store.py::test_real_btc_eth_development_only_native_smoke`, requiring its explicit BTC/ETH canonical build. It is not the M8 replay.
- Dedicated ATS-4 suite: **75 passed**, including the real three-cost factory run, full independent native reconciliation, public-CLI dispatch and real sleeve conversion. JUnit: `run_log/ats4_verification/ats4_full.xml`.
- Scoped Ruff and `git diff --check`: passed.
- Public CLI completed with exit **3**, `PARTIALLY_QUALIFIED`, no engineering exception. It used no test stub for native execution.
- Final read-only review by agent `agt_5621e818`: no P0/P1 findings in other-authored protocol, authority, portfolio and integration code. That agent authored the numerical reconciler, so its review of that component is not independent; supervisor review and independently specified literal/mutation fixtures provide the separate challenge. No claim of a wholly separate research team is made.

The durable public-CLI case is:

```text
run_log/ats4_verification/public_cli/dual_mode/m8_n8_cash_session_v7/20261016T084316-3ac05c3204/
```

It contains `casefile.json`, `event_evidence.json`, `event_oracle.json`, native orders/fills/equity/portfolio state and independently rebuilt accounting Parquet files for all three cost cases, and `portfolio_sleeves.json`. The latter retains four full immutable records: cash plus three cost cases of M8. Artifact hashes are in event evidence; the append-only hash-chained ledger is in the public-CLI run root. Raw evidence is retained locally rather than duplicated into Git. Negative/red-test development evidence was not substituted for the final passing acceptance reports.

Environment and verification limitations are explicit: OpenCode was unavailable in the connected DevSpace target list, so bounded Codex workers were used under supervisor control. Some worker sandbox runs could not create namespaces or JIT caches; the final main-workspace suite ran the native JIT and isolation tests successfully. Initial commands using the PATH-shadowed no-op `env` produced no test evidence and were excluded; valid commands used `/usr/bin/env`. Tool-blocked standalone diagnostic commands were not executed and were not counted. See the operating document for exact runnable commands.

## Integration requirements

Integrate the ATS-4 commit into the verified common-base lineage, resolving the three shared entrypoint files carefully: `scripts/quant.py`, `src/engine/funnel.py`, and `src/workbench.py`. Do not copy another ATS worktree or overwrite concurrent edits. The legacy CandidateSpec implementation, historical M8 modules/artifacts and dependency lockfile were not modified.

Preserve the historical source and authority files and the pinned environment. The current bridge deliberately names a read-only file in the historical worktree; deleting that worktree removes its source authority. Relocation, new strategy rules, new dates, new cost assumptions or upgraded native versions require explicit adaptation and fresh qualification, not a changed hash to make an existing claim pass. This is not a general replacement for DataVault or an arbitrary strategy-loader interface.

After integration, rerun all listed legacy/native/ATS-4 regressions and the public-CLI qualification because merged runtime contents will have a new content identity. Retain each new attempt and its evidence. Generic stop/target models, observed executable costs, finer barrier marks, multi-strategy combined-account execution and fresh protected evaluation remain separate work. No push, merge, deployment or trading authority is implied by this record.
