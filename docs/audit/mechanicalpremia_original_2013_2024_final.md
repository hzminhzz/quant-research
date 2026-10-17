# Mechanical Premia original four-index development: 2013–2024 final batch audit

**Status: ALL 72 NATIVE RUNS TERMINAL, 0 EXECUTION FAILURES; NOT APPROVED FOR VALIDATION OR LIVE USE.**

Research ID: `mechanicalpremia-original-four-2013-2024-v1`
Observed batch end: 2026-10-13 14:54:34 UTC.
Job log: `run_log/research_sessions/mechanicalpremia-original-four-2013-2024-v1/batch_log.jsonl`.
Year-level inputs/outputs: `run_log/research_sessions/mechanicalpremia-original-four-2013-2024-v1/yearly_native/year=YYYY/<trial>/cost_<multiplier>x/`.

## Frozen thesis and experimental scope

- Source: https://mechanicalpremia.substack.com/p/building-a-multi-strategy-portfolio
- Canonical Dukascopy 1m BID CFD quotes, years 2013–2024 ONLY; no >2024 partition scans for simulation.
- Original source coverage: H1 volatility-breakout on US500, US100, DE30. D1 EMA/Bollinger/ATR mean reversion on US500, US100, DE30 and EU50. DAX begins Sep 30 2013; EU50 begins June 2 2014.
- The source-weighted portfolio uses a **D1 76.64% / H1 23.36% nominal risk budget**; the comparator uses 50/50. No alpha parameter fitted.
- Synthetic $100k price-unit account **reset each year**; 12 separate annual native backtests. Never claim these annual returns form a live continuous account or cumulative CAGR/Sharpe.
- Placeholder direct costs per side: 1 bp commission + 2 bp slippage. Cost stresses multiply those components by 1.5 and 2.0; excludes observed ASK spread, overnight CFD financing, FX translation and actual contract multiplier.

## Results

Rows show **arithmetic mean of independent annual synthetic equity returns**, NOT annualized returns from a continuous 12-year portfolio.
Daily-equity Sharpe values shown are **arithmetic means of twelve separately computed annual daily-equity Sharpes**, NOT a reconstructed 12-year Sharpe. Year-by-year native `PortfolioAnalysis` risk metrics are saved in each summary.

| Candidate | Mean year return | Positive years | Closed trades (sum) | Closed win rate | Mean annual daily Sharpe | Worst within-year DD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| H1 source, 3 indices | -0.43% | 5/12 | 1,741 | 34.92% | -0.127 | -5.95% |
| D1 source, 4 indices | +2.33% | 8/12 | 82 | 81.71% | +0.677 | -8.32% |
| Equal-risk 7 sleeves | +1.02% | 8/12 | 1,823 | 37.03% | +0.304 | -4.92% |
| Source-weighted 7 sleeves | +1.40% | 8/12 | 1,823 | 37.03% | +0.377 | -6.60% |
| Source-weighted, 1.5x costs | +0.55% | 6/12 | 1,823 | not independently recomputed | not aggregated | not aggregated |
| Source-weighted, 2x costs | **-0.29%** | 5/12 | 1,823 | not independently recomputed | not aggregated | not aggregated |

D1 / both portfolio variants have **nine total year-end open trade occurrences** summed across years. Those positions are marked in native account equity but are NOT carried into following years; year reset creates an economically material discontinuity. The D1 win rate conditions on 82 closed trades and excludes nine year-end open occurrences.

### Comparison and falsifier

- Source-risk portfolio exceeds equal-risk annual return in 8 of 12 reset-year samples. Source-weighted does **not** exceed standalone D1 annual return in 8 of 12; only 4 of 12 years favor the source portfolio.
- Source-risk mean yearly return +1.40% is below standalone D1 +2.33%, and its mean yearly daily Sharpe +0.377 is below standalone D1 +0.677.
- Worst observed year-level DD is -6.60% for source weights vs -4.92% for equal-risk. **This is not a continuous-series drawdown comparison.**
- At 2x proxy direct costs, source-risk mean year return is -0.29%; 7 of 12 years are negative.
- Therefore, the frozen **source-weighted multi-sleeve diversification/promotion hypothesis fails the tested robustness criteria**. This is a REJECT for promotion **under current bid-only, synthetic-unit research assumptions**, NOT a broker-qualified disproof of the original published thesis.
- Cost and source parity defects also require the true CFD economic conclusion to remain INCONCLUSIVE.

## Independent execution/artifact verification

- Exactly 72 unique `(year, trial, cost)` summary identities recovered; all 72 completed; batch state `completed=72, failed=0, total_planned=72`; terminal `ALL_TERMINAL` entry present; named tmux worker has exited.
- All 72 summaries assert native end-of-year broker **equity = cash + marked positions** to $0.01 tolerance. **Zero native rejected orders** across 72 runs.
- Eight regression tests passed for native execution, protected cutoff, source sleeve universe, next-minute entries and duplicated trading-unit independence.
- Direct outputs include native fills/trades/daily equity, not homemade price-return simulation. Any Sharpe/Calmar in source artifacts is from `ml4t.diagnostic.api.PortfolioAnalysis`.
- Data provider acceptance audit: `docs/audit/mechanicalpremia_data_2013_2024_v1.json`. At-source quote semantics are BID only; many incomplete/stale/zero-volume days, with fixed candle completeness exclusions.
- `2024` had been observed in an earlier session. These 12 years are **development/expanded history**, not untouched OOS, regardless of recency.

## Unresolved safety and economic qualification blockers

1. **Native H1 protective-stop entry-minute gap:** stop placed after entry, so source-level immediate protective semantics not met.
2. **Bid only:** no actual buy ASK, spread, broker market-order slippage calibration, or overnight CFD financing.
3. **Mixed currencies:** German and EU50 indexes quoted in EUR, US500 and US100 in USD; native synthetic account has no EURUSD conversion.
4. **Source sessions:** fixed 17:00 New York D1 boundary used across US and European brokers, not proven MT5 broker session.
5. **Year-boundary discontinuity:** marks on open trades counted but holdings not carried forward, and end-of-year liquidation cost not assessed.
6. **Historical sparsity:** historical data contains stale/zero-volume quotes and many short calendar days; no verified broker quote execution path.
7. **Synthetic contract sizing:** no actual CFD point value/lot specification or margin/currency conversion. Never call synthetic-dollar net PnL executable.
8. **No uncertainty interval/DSR:** complete historical selection footprint and independently validated continuous strategy equity are not established; PBO/DSR and corrected OOS significance undefined.

## Verdict

**REJECT candidate for promotion in its current original-source-risk, multi-index formulation; broker-economics validity INCONCLUSIVE.** Keep all failed, negative and incomplete data evidence. No protected final test and no live orders. For any strategy revision (fix stop timing, FX sizing, source broker clock, data filters or moving holdings across years), freeze a NEW trial/session BEFORE evaluation. No optimization on this frozen expanded trial.

Files: `scripts/mechanicalpremia_source_universe_2013_v1.py`, `scripts/run_mechanicalpremia_extended_2013.py`, `scripts/batch_mechanicalpremia_extended_2013.py`, `docs/plans/mechanicalpremia_original_universe_2013_2024_v1.md`.

## Final research-control state
- All seven preregistered research trials now have terminal `completed` records; zero pending. A `completed` research trial means the experiment was executed, NOT that a scientific quality gate passed.
- The read-only status command says `READY` and `approval_status: NOT_APPROVED`. This is ledger readiness, NOT strategy validation.
- The session's strict native input checker reports `audit.status: BLOCKED`: the frozen data identities are external canonical-store **JSON pointer manifests**, for which the built-in auditor returns `unsupported_data_format` on all four inputs. The external 2013–2024 per-day Dukascopy acceptance audit and direct read path were separately completed, but they do not repair the frozen SessionSpec check. Never silently replace the frozen spec or call its input audit PASS.
- Code and reports are present on the VPS working tree but are uncommitted and unpushed. Existing unrelated dirty work was preserved.

