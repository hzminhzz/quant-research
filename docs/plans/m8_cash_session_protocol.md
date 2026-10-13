# M8 N8 US cash-session protocol

**Status:** Preregistered exploratory adaptation. Record before any result output.

## Research question and source

The source text is `run_log/m8/original_rulebook_extracted_pages.txt`, which
contains 12 page-marked pages. Model 8 appears on page 7. The supplied PDF
binary is not in this checkout. The research lead waived binary transfer. This
study uses the extracted text and retains the existing source manifest. This
limitation does not establish the PDF binary hash from this checkout.

The original rule uses a continuous futures price series. This adaptation uses
the canonical Dukascopy `index_minute_NQ` source, symbol `usatechidxusd`, and
the existing 30-minute file at
`data/research_sessions/m8_n8_dukascopy_nas100_cfd_30m_v1/prices_30m.parquet`.
It is a CFD price proxy. It is not CME NQ futures or proof of broker execution.
Keep its stored source fingerprints unchanged.

## Post-hoc design influence and calendar

The earlier 24-hour/extended-hours experiment is terminally blocked. Its
attempt `70841083-b113-4319-8981-dfaef88c13ab` found 26 missing scheduled fill
bars among 2,491 eligible signals. Its native engine did not start. It has no
native fills, equity, or strategy outcome. Preserve the failure and count it as
an observed attempt. Do not patch or replay it.

Most missing times align with XNAS cash-session closes, including 20:00Z or
21:00Z regular closes and July 3/December 24 early closes. This discovery
influenced this new protocol. The result is retrospective and does not provide
untouched out-of-sample or profit-robustness evidence. This is a second,
separate exploratory attempt.

Use the installed `exchange_calendars==4.13.2` XNAS schedule, bounded to
2020-01-01 through 2024-12-31. In this package, XNAS resolves to the XNYS
calendar implementation. The schedule provides the same verified dates and
times for the requested weeks, but it is not an independent Nasdaq calendar
implementation. The official reference states Nasdaq regular hours are
09:30-16:00 America/New_York and 13:00 early closes apply on listed dates:
[Nasdaq holiday schedule](https://www.nasdaq.com/market-activity/stock-market-holiday-schedule)
and [Nasdaq Trader notice ETA2024-84](https://nasdaqtrader.com/TraderNews.aspx?id=ETA2024-84).
The exchange schedule does not prove Dukascopy execution availability.

For bar start `t`, require the completed signal bar `[t,t+30m)` to fit the
known session. Require planned opens `t+30m` and `t+60m` to be inside the
half-open XNAS session and strictly before `2025-01-01T00:00:00Z`. Compute
eligibility only from `t`, the frozen boundary, and the schedule. Do not query
future source row presence to select signals. After fixing the signal set,
require both real provider bars for every signal. Any missing bar blocks the
whole run. Do not drop signals or create fills.

## Causal rule, trial and limits

Use strict `close[t] > max(high[t-50:t])` after the completed 30-minute bar.
Enter at the next bar open and exit at the following bar open. Use one long
normalized unit. Do not add stop or target orders. The unit is $1 per index
point for arithmetic only; the broker contract multiplier is unknown.

Run one primary 2020-2024 trial. Use the existing approved prior-high feature
proof and `ml4t-backtest==0.1.7` native next-bar engine. Apply 3 bps adverse
price impact plus 0.6 bps commission per fill. Apply the same components at
1x, 2x and 3x. These are assumptions, not observed quotes or validated market
impact. Retain native fills and equity, independent fill/cash reconciliation,
native trade metrics, and `PortfolioAnalysis` daily equity risk metrics.

Falsify if gross total PnL or baseline net expectancy is non-positive. A
positive baseline that fails the 2x or 3x stress is fragile. No trades is
inconclusive. The prior 24-hour attempt and this cash-session attempt both
count in the known design history. The wider historical model-selection record
is incomplete, so no reproducible DSR or pristine holdout claim is available.

The holdout begins at 2025-01-01T00:00:00Z and stays unopened. This protocol
does not approve the strategy, broker execution, or live trading. No live order
or real-money action is permitted.

## Compute budget and freeze

Allow one trial, 3,000 CPU seconds, 4,096 MB memory and 3,600 wall seconds.
Freeze the session spec, contract, calendar evidence, source/data identities,
cost evidence, audit recipe, and run intent before generating signal counts or
performance output. Record all three fixed cost scenarios as one declared
primary trial, not as parameter selection.

## Method references and checks

The official ML4T skills were read from revision
`f0ea01919e0c517cd9b1e014724a520facd8a742`. No matching local skill files were
found during discovery.

| Skill | Why selected | Invariant and verification |
| --- | --- | --- |
| `data/validate-data` | Reuse and validate the frozen bar source. | Keep source identity fixed; fail on missing planned fills. Verify the source fingerprint and readable Parquet. |
| `data/build-bars` | The source is a derived 30-minute series. | Preserve immutable bars and source hashes. Reuse the independent aggregation evidence; do not rebuild bars. |
| `data/calendar-ops` | Session time and early-close rules define eligibility. | Use bounded XNAS schedule, DST and half-day tests, and no future-row query. |
| `features/feature-validation` | Prior-high feature controls the signal. | Keep the approved gateway proof, strict prior-window oracle, and causal availability tests. |
| `concepts/lookahead-bias` | Orders use future opens after a completed signal. | Determine eligibility from schedule and clock only; require actual opens after signals are fixed. |
| `backtest/run-backtest` | The trial requires event-driven fills. | Use installed `ml4t-backtest==0.1.7`, next-bar native orders, and independent reconciliation. |
| `concepts/transaction-costs` | Costs can change the result. | Keep commission and adverse price assumptions explicit at fixed 1x/2x/3x levels. |
| `advanced-ai/agent-state-memory` | Attempts need safe recovery. | Preserve append-only identities and terminal states; verify completed output by native replay. |
| `advanced-ai/agent-tool-contracts` | The managed runner crosses data and execution boundaries. | Enforce strict contracts and identities outside model assertions; test rejection paths. |

The checks establish process behavior. They do not prove broker fills, market
impact, economic persistence, or strategy profitability.
