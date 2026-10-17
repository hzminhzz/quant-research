# Mechanical Premia Yen Squeeze proxy v3: final audit

**Session:** `mechanicalpremia-yen-squeeze-proxy-20261014-v3`
**Classification:** `EXPLORATORY`
**Approval:** `NOT_APPROVED`
**Research decision:** **The recorded results fail the frozen development falsifier.** Exact frozen-code attribution remains unverified because two frozen source fingerprints differ from the current files.
**Final test:** Not opened. No market data dated 2025-01-01 or later was read.

## Decision

Both 2-pip trials have negative closed-trade expectancy and negative marked daily-equity Sharpe in their stored native output. Both 4-pip trials have negative net profit. All six variants lose account equity. The stored results therefore fail the frozen proxy criteria. The wrapper source mismatch below means I cannot certify that every output came from the exact frozen driver and wrapper versions.

This is a result for the fixed-numeraire exploratory proxy. It does not establish broker execution or reject every possible yen carry hypothesis. The stop-protection gap and the account-data limitations below reduce confidence in the precise performance estimates. They do not change the sign of the results needed by the frozen falsifier.

## Frozen scope and identity

The frozen declaration is `config/research_sessions/mechanicalpremia_yen_squeeze_proxy_20261014_v3.yaml`. Its frozen session record is `run_log/research_sessions/mechanicalpremia-yen-squeeze-proxy-20261014-v3/frozen_spec.json`.

- Frozen spec SHA-256: `b220668d837a2932dce60ed98331794dd91b4d951a272832913e2a09e89df00b`.
- Frozen session SHA-256: `51635b909c84e66cf14cc8db49d0749d49b32bbc33046fd7f6061161ae729e91`.
- Development data: 2023-01-01 through 2024-12-31, inclusive.
- Final test boundary: 2025-01-01. The test remains protected.
- Instruments: USDJPY, GBPJPY, and CADJPY 1-minute OHLCV proxies.
- Account: USD 10,000 starting cash, fixed 150 JPY/USD price and PnL numeraire.
- Frozen trials: Donchian lookbacks 20 and 500 hours, each at 2, 4, and 6 JPY pips round-trip proxy cost.
- Backtest and feature packages: `ml4t-backtest 0.1.7`, `ml4t-engineer 0.1.4`, `ml4t-diagnostic 0.1.6.post2`; `ml4t-data 0.1.0b14` for the recorded CADJPY data gate.

All three Parquet snapshots match the frozen SHA-256 identities. Their hashes are in the terminal evidence file linked below. The frozen source inventory contains 280 files. I checked all 280 current files. Two current driver files do not match their frozen hashes: `scripts/mechanicalpremia_yen_squeeze_proxy_20261014.py` (frozen `6f9a2139c7f5043548a8979f25aaf8082789a39d57fc4930ce7369fcd6f2caff`, current `394279bee54c904f1cffe526ea803df65d2496d5148b470cee39464583529477`) and `scripts/run_mechanicalpremia_yen_squeeze_proxy_20261014.py` (frozen `76a0ca614e066b72f4bc2c15360300f3895c6c21825f5ecb4b08c6f368935650`, current `4a4f68ee0d1cf65116a811b51e3ee74f69f3fbdb7941479eedbb9bd16f40d27f`). Their current modification times are shortly after the 18:14:05Z freeze time. The `scripts/mechanicalpremia_yen_squeeze_native_strategy_20261014.py` strategy and feature adapter hash does match. The frozen wrapper contents are not preserved in the session artifacts, so this audit cannot determine the exact code delta or certify exact wrapper parity. I did not alter these files. USDJPY and GBPJPY came from the earlier processed snapshots. GBPJPY timestamps were naive in their source lineage and were localized to UTC. CADJPY came from Dukascopy-node staging. It is not canonical ML4T data. The combined source audit records 2,237,996 rows and zero rows at or after 2025.

The economic thesis was that carry and macro positioning could create trends after quiet H1 ATR windows. The frozen rule used completed H1 ATR14, the upper median of the prior 100 ATR observations, prior completed-bar Donchian channels, native stop orders, a 1% initial stop risk target, and native fixed slippage. The 20-hour window reflects the source code. The 500-hour window reflects a separate prose interpretation.

## Native result summary

Win count and win rate use rows with native status `closed`. Closed-trade expectancy is mean native PnL for those rows. Net profit and ending equity use native Engine results. Daily Sharpe is annualized at 252 periods per year from marked daily returns.

| Trial | Trade rows (closed + partial) | Wins among closed | Expectancy / closed trade | Net profit | Ending equity | Daily Sharpe | Calmar | Max drawdown |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `PORTFOLIO-20-2PIP` | 1,422 (1,416 + 6) | 502 (35.45%) | -$5.40 | -$7,503.03 | $2,496.97 | -0.70 | -0.52 | -80.50% |
| `PORTFOLIO-20-4PIP` | 1,410 (1,405 + 5) | 477 (33.95%) | -$6.34 | -$8,753.55 | $1,246.45 | -1.20 | -0.62 | -89.90% |
| `PORTFOLIO-20-6PIP` | 1,402 (1,397 + 5) | 444 (31.78%) | -$6.70 | -$9,423.10 | $576.90 | -1.74 | -0.71 | -95.22% |
| `PORTFOLIO-500-2PIP` | 264 (264 + 0) | 97 (36.74%) | -$10.30 | -$2,718.17 | $7,281.83 | -0.58 | -0.41 | -28.09% |
| `PORTFOLIO-500-4PIP` | 264 (264 + 0) | 91 (34.47%) | -$13.52 | -$3,568.02 | $6,431.98 | -0.84 | -0.44 | -35.68% |
| `PORTFOLIO-500-6PIP` | 261 (261 + 0) | 87 (33.33%) | -$16.91 | -$4,414.34 | $5,585.66 | -1.14 | -0.46 | -44.14% |

The 20-hour trade files also contain 5–6 rows marked `partial`. The native trade ledger PnL sum includes these rows and matches the account change. The closed-only expectancy above is the mean PnL from the native closed-trade rows; the win count is checked from those same rows. The 500-hour trade files have no partial rows. This status difference is retained as reported by the native result API.

The native Engine applies the frozen per-fill slippage on both entry and exit. Fixed slippage per fill was $0.00006667, $0.00013333, and $0.0002 in the scaled quote-price units for the 2-, 4-, and 6-pip variants. Native fill and trade ledgers show the same per-fill amount on both sides. Engine total slippage costs reconcile to the native trade-ledger costs. Commission is zero. There is no second cost deduction outside the Engine. Total Engine slippage costs range from $1,261.64 to $10,053.91 across these runs because the engine applies per-unit slippage to filled quantities.

## Calendar returns

Values below are native marked daily-equity returns from the stored period diagnostics. They show each development year and quarter. No 2025+ period is present.

| Period | 20-2 pip | 20-4 pip | 20-6 pip | 500-2 pip | 500-4 pip | 500-6 pip |
|---|---:|---:|---:|---:|---:|---:|
| 2023 | -21.83% | -47.35% | -65.48% | -16.85% | -22.84% | -28.14% |
| 2024 | -68.06% | -76.33% | -83.29% | -12.42% | -16.64% | -22.28% |
| 2023 Q1 | +16.77% | +8.77% | -1.80% | -2.32% | -3.84% | -4.92% |
| 2023 Q2 | -8.63% | -18.55% | -22.78% | -8.45% | -10.06% | -12.31% |
| 2023 Q3 | -28.33% | -35.43% | -45.58% | -10.53% | -13.40% | -15.51% |
| 2023 Q4 | +2.22% | -7.98% | -16.35% | +3.92% | +3.02% | +2.01% |
| 2024 Q1 | -27.23% | -34.95% | -42.25% | -1.75% | -3.15% | -5.69% |
| 2024 Q2 | -6.05% | -17.70% | -26.78% | -0.48% | -3.22% | -4.80% |
| 2024 Q3 | +23.98% | +24.89% | +21.33% | +19.22% | +20.53% | +18.23% |
| 2024 Q4 | -62.31% | -64.59% | -67.43% | -24.87% | -26.21% | -26.78% |

## Native pair attribution

Each table cell is `closed trades / total native ledger PnL / closed-trade expectancy`. PnL includes all native trade rows for that pair, including any rows marked `partial`.

| Trial | USDJPY | GBPJPY | CADJPY |
|---|---|---|---|
| `PORTFOLIO-20-2PIP` | 503 / -$4,354.73 / -$8.47 | 451 / -$598.03 / -$1.88 | 462 / -$2,550.26 / -$5.48 |
| `PORTFOLIO-20-4PIP` | 496 / -$4,536.30 / -$9.05 | 451 / -$1,512.08 / -$3.88 | 458 / -$2,705.16 / -$5.83 |
| `PORTFOLIO-20-6PIP` | 494 / -$4,224.59 / -$8.50 | 446 / -$1,907.02 / -$4.28 | 457 / -$3,291.49 / -$7.12 |
| `PORTFOLIO-500-2PIP` | 106 / -$2,857.92 / -$26.96 | 80 / +$745.69 / +$9.32 | 78 / -$605.95 / -$7.77 |
| `PORTFOLIO-500-4PIP` | 106 / -$3,149.22 / -$29.71 | 79 / +$542.42 / +$6.87 | 79 / -$961.23 / -$12.17 |
| `PORTFOLIO-500-6PIP` | 105 / -$3,428.79 / -$32.66 | 79 / +$203.43 / +$2.58 | 77 / -$1,188.99 / -$15.44 |

The per-pair trade PnL sums reconcile to each portfolio’s native trade PnL. This completes `SINGLE-PAIR-ATTRIBUTION`. Cost increases reduce net profit and closed-trade expectancy for both lookback families. No pair or variant was selected.

## Execution and accounting audit

The frozen engine-gate evidence covers native STOP gap fills at the worse open, native cancel/update, native short fills, fixed slippage sign at 1x/2x/3x, and same-bar opposite STOP behavior. The strategy ran through `ml4t.backtest.Engine`; features came from `ml4t-engineer`. The code and output files were inspected. No custom simulator or custom PnL path was used.

The six result sets pass these artifact checks:

- All three input snapshot hashes match the frozen identities.
- All six summaries, fills, trades, and daily-equity Parquet files match their result manifests.
- Every native fill has `price_source=open`. Recorded market timestamps and native trade timestamps end before 2025.
- Native entry and exit slippage each match the frozen per-fill amount. Native total slippage cost matches the trade-ledger cost. Commission is zero.
- The native trade PnL sum matches the native account change in each run. The daily close-to-prior-close return series compounds to ending equity.
- Each ending snapshot has zero open positions and zero gross/net exposure. Cash equals equity at the final timestamp. The engine reported a maximum of three concurrent positions in each variant. Shorts were present in all six. The 20-hour variants had 9–11 rejected orders for insufficient buying power; the 500-hour variants had none.

The daily Parquet `pnl` field is not an additive account ledger. `ml4t.backtest.Result.to_daily_pnl` defines it as same-day `close_equity - open_equity`; its `return_pct` uses `close_equity - prior-day close_equity`. The latter compounds to the ending account equity. The final audit records both the exact discrepancy and this library definition.

The full `ACCOUNTING-AND-GAP-AUDIT` remains **failed / inconclusive**. The retained output does not include the per-bar `portfolio_state` series or a complete order lifecycle ledger. Terminal cash, equity, exposure, trade PnL, daily return, fill cost, and reported gap counts reconcile. The saved data cannot independently reconstruct every intermediate cash balance, position, and mark as the frozen trial requested.

The native proxy also has a known one-minute protection gap. It records 261–1,417 unprotected entry bars and 15–33 entry-bar stop breaches per run. Breaches trigger a native market exit on the next eligible bar. The 20-hour variants record 3–4 same-minute opposite STOP fill groups; the 500-hour variants record none. The Engine nets simultaneous opposite orders. This is not broker hedge or OCO behavior. These events are in the native output, not removed from the result.

## Trial ledger and attempts

The three pre-outcome gates were already recorded before these six performance trials:

| Trial | Ledger status | Result |
|---|---|---|
| `DATA-CADJPY-PROVENANCE` | completed | Three-pair 2023–2024 identity bound; staging and timezone caveats retained. |
| `ENGINE-STOP-ORDER-AND-CASH-GATES` | completed | Native proxy behavior passed; one-minute protection gap and opposite-order netting remain. |
| `FEATURE-AND-CLOCK-PARITY` | completed | Feature availability audit reports zero future-availability violations. |

All six frozen portfolio runs completed with existing native output summaries. Their ledger entries link directly to each `summary.json`. The queue log reports `QUEUE_TERMINAL`; it shows exit code 0 for the five queued runs. No matching run or queue process appeared in the visible process table. The sandbox denied access to the host tmux socket, so tmux session status could not be checked independently. No backtest was repeated and no retry was made.

| Trial | Ledger status | Evidence |
|---|---|---|
| `PORTFOLIO-20-2PIP` | completed | `run_log/mechanicalpremia_yen_squeeze_proxy_20261014/PORTFOLIO-20-2PIP/summary.json` |
| `PORTFOLIO-20-4PIP` | completed | `run_log/mechanicalpremia_yen_squeeze_proxy_20261014/PORTFOLIO-20-4PIP/summary.json` |
| `PORTFOLIO-20-6PIP` | completed | `run_log/mechanicalpremia_yen_squeeze_proxy_20261014/PORTFOLIO-20-6PIP/summary.json` |
| `PORTFOLIO-500-2PIP` | completed | `run_log/mechanicalpremia_yen_squeeze_proxy_20261014/PORTFOLIO-500-2PIP/summary.json` |
| `PORTFOLIO-500-4PIP` | completed | `run_log/mechanicalpremia_yen_squeeze_proxy_20261014/PORTFOLIO-500-4PIP/summary.json` |
| `PORTFOLIO-500-6PIP` | completed | `run_log/mechanicalpremia_yen_squeeze_proxy_20261014/PORTFOLIO-500-6PIP/summary.json` |
| `SINGLE-PAIR-ATTRIBUTION` | completed | `docs/audit/mechanicalpremia_yen_squeeze_proxy_v3_terminal_audit_20261014.json` |
| `ACCOUNTING-AND-GAP-AUDIT` | failed | `docs/audit/mechanicalpremia_yen_squeeze_proxy_v3_terminal_audit_20261014.json`; terminal reconciliation passes, full path audit remains inconclusive. |

Earlier two-pair registrations remain as historically recorded failures. This report does not edit or reclassify them.

## Limitations and next decisive question

The evidence uses a fixed 150 JPY/USD numeraire. It does not use historical conversion. USDJPY source mix remains unresolved. GBPJPY naive timestamps were localized to UTC under an unverified assumption. CADJPY is noncanonical Dukascopy staging with an assumed UTC interpretation. The data has no historical bid/ask. The trials do not model swap, financing, or changing FX conversion. Broker tick size, lot step, minimum lot, and exact margin rules remain unknown. The one-minute protection gap and native opposite-stop netting are proxy behavior. The frozen costs are exploratory all-in fixed proxies, not verified broker costs. They do not establish market impact or broker equivalence.

The strongest next question is whether a new prospective session can freeze a source-matched wrapper and retain full per-bar native account state, while also obtaining verified symbol terms, timestamp provenance, bid/ask, financing, and immediate protective-stop behavior. Do not rerun or repair these frozen trials. Any future work must keep the frozen 2025+ final test protected and register a new exploratory session if the execution contract or thesis changes. These results do not approve deployment.

## Evidence and verification record

The machine-readable audit records all six result SHA-256 values, frozen input identities, trial metrics, pair attribution, annual/quarter returns, fill-cost checks, account reconciliation checks, and execution counts:

- [`mechanicalpremia_yen_squeeze_proxy_v3_terminal_audit_20261014.json`](mechanicalpremia_yen_squeeze_proxy_v3_terminal_audit_20261014.json)
- [`mechanicalpremia_yen_squeeze_proxy_v3_source_identity_20261014.json`](mechanicalpremia_yen_squeeze_proxy_v3_source_identity_20261014.json)
- [`mechanicalpremia_yen_squeeze_proxy_v3_data_gate_20261014.json`](mechanicalpremia_yen_squeeze_proxy_v3_data_gate_20261014.json)
- [`mechanicalpremia_yen_squeeze_proxy_v3_engine_gate_20261014.json`](mechanicalpremia_yen_squeeze_proxy_v3_engine_gate_20261014.json)
- [`mechanicalpremia_yen_squeeze_proxy_v3_feature_gate_20261014.json`](mechanicalpremia_yen_squeeze_proxy_v3_feature_gate_20261014.json)

The applicable local methods read for this audit were `ml4t-run-backtest`, its declared dependency `ml4t-cost-model`, and `ml4t-transaction-costs`. Their checks were tied to native later-bar fills, cost application on both fill sides, retained fill/trade/equity ledgers, and marked daily returns. The existing data, feature-clock, and engine gates were also inspected. The focused test command `.venv/bin/python -m pytest -q tests/test_mechanicalpremia_yen_squeeze_proxy_20261014.py tests/test_mechanicalpremia_yen_squeeze_native_20261014.py tests/test_mechanicalpremia_yen_squeeze_native_strategy_20261014.py` passed: 25 tests. The tests use synthetic engine scenarios and do not load protected market data or rerun portfolio trials.
