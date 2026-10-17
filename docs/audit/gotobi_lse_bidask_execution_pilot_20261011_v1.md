# LSE historical bid/ask quote execution readiness — 2026-10-11

## Decision

**NATIVE QUOTE-AWARE BACKTEST MECHANICS VERIFIED.**
**FULL MULTI-YEAR RETROSPECTIVE PILOT: BLOCKED ON LSE EXPORT RATE LIMITS.**
**Trading strategy: NOT_APPROVED.**

This study extends the prior Gotobi 2020-August2026 one-minute OHLCV analysis.
It does not use the sealed September-October2026 final-test history. No
live orders or Git commits were made.

## Directly verified LSE capabilities

- Python SDK: `lse-data 0.14.0`, `LSE.history("USD/JPY", dataset="fx", timeframe="tick")`.
- Historical FX quote tick columns are `ts` (timezone-aware UTC), `symbol`,
  `bid`, and `ask`.
- June 9, 2025 raw export: **170,613** records.
- June 10, 2025 raw export: **192,273** records.
- April 1-8, 2025 export: **1,185,699** records.
- All three source files have stored SHA256 identities and belong to the
  external data repo `/home/quant/dev/quant/ml4t-data/.artifacts/gotobi-tick-probe`.
- A June 2025 monthly export returned exactly **2,500,000** rows but stopped
  on June 18 instead of July 1. This is a silent truncation risk. It is
  specifically excluded from any backtest source.
- Further API exports returned **HTTP 429 Too Many Requests**; the provider
  does not currently supply the remaining frozen pilot intervals.

## Native execution implementation

Files:

- `scripts/run_gotobi_lse_bidask_smoke_20261011.py`
- `tests/test_gotobi_lse_bidask_execution_20261011.py`
- `scripts/run_gotobi_lse_bidask_execution_pilot_20261011_v1.py`
- `config/research_sessions/gotobi_lse_bidask_execution_pilot_20261011_v1.yaml`

LSE records share exact second timestamps. A quote's order within the second
is **unknown**. The execution-bound constructor groups quotes by second,
uses maximum ask for buyer, minimum bid for seller, and rejects unavailable
or stale quotes. The synthetic four-event DataFeed (entry decision,
entry quote, exit decision, exit quote) feeds the installed
`ml4t.backtest.Engine`, in `NEXT_BAR` mode. Prices for the execution
events represent bid/ask quote-side prices rather than OHLC source opens.
Separate source-quote order timing and JPY accounting oracles verify the
result. The engine owns order submissions, fills and the portfolio ledger.

The primary pilot assumption is first quote-second at or after 03:00 JST
or 09:54 JST, with +1 second execution delay and an additional adverse
0.25 pip **per leg**. The historical quoted spread is therefore counted
by ask/bid prices before the extra slippage. This is not a broker-verified
fill probability or latency model.

## Completed engineering smoke (not a statistical evaluation)

Only two Gotobi dates and two ordinary dates from previously observed 2025
quotes were eligible for the exploratory engineering smoke:

| Historical simulation | Trades | Net USD |
|---|---:|---:|
| Gotobi; 1s delay, extra 0.25 pip each leg | 2 | -10.10 |
| Ordinary same-window; 1s delay, extra 0.25 pip each leg | 2 | -136.85 |
| Gotobi; 0s delay, no extra slippage | 2 | -10.10 |
| Gotobi; 5s delay, extra 0.50 pip each leg | 2 | -11.33 |

**These four tiny cohorts have no economic significance.** One of the
ordinary dates is April 3, 2025; two-trade samples are dominated by
specific news and price paths. No causal or stable profitability claim
is possible.

Source-including smoke quality:

- **1,548,585** tick updates examined from the three verified files;
- **513,772** distinct quote-seconds;
- median observed LSE quoted spread **0.7 pip**;
- p95 observed LSE quoted spread **1.8 pips**;
- worst-case within-second quote construction is more conservative than
  choosing a favorable update;
- native JPY final cash and original source quote oracle reconcile within
  floating point tolerance.

## Broader preregistered evaluation

The not-yet-frozen full pilot intentionally selects April 2-14 JST from
2020 through 2026, using exactly two bounded UTC exports per year.
The scope was specified independently of the outcomes of these April
years; however prior 2020-Aug2026 Gotobi history was already inspected,
so **this is not new OOS data**.

The full runner fails closed unless every one of the **14** required
calendar-week exports passes source SHA256, quote schema, row-count,
coverage and timestamp checks.

At the current checkpoint **1/14** weekly exports is verified.
The other 13 are missing due to source quota. The CLI freeze and
statistical backtest intentionally do not run until that gate passes.
A rate-limit-aware bounded tmux worker was started in the
`ml4t-data` repo as `ml4t-gotobi-bidask-export`, with state/log at:

`/home/quant/dev/quant/ml4t-data/.artifacts/gotobi-tick-probe/worker_state.json`
`/home/quant/dev/quant/ml4t-data/.artifacts/gotobi-tick-probe/worker_events.jsonl`

The worker attempts only the fixed April date intervals, backs off
30 minutes on HTTP429, stops on structural errors or a bounded quota
failure, and runs the full native pilot only when all source gates pass.
A running worker is **not a completed study**.

## Remaining uncertainty

- LSE's historical bid/ask quotes are reference quotes, not proven
  executable prices on the user's retail broker.
- Tick timestamps are second-level despite a microsecond Polars dtype;
  many updates share the same second.
- Historical broker commissions, true latency and fill-to-quote
  tracking errors remain unmeasured; the extra slippage scenarios are
  assumed, not empirically broker calibrated.
- Even if the fixed April subset becomes available, a selected 14-day
  window each year cannot establish annual performance for all Gotobi
  sessions. A longer sample or prospective broker quote recording is
  needed before trading approval.

## Reproduce and verify

- Smoke: `uv run python scripts/run_gotobi_lse_bidask_smoke_20261011.py`.
- Broader gate and (only if all sources pass) study:
  `uv run python scripts/run_gotobi_lse_bidask_execution_pilot_20261011_v1.py`.
- Focused regressions: `uv run python -m pytest -q tests/test_gotobi_lse_bidask_execution_20261011.py tests/test_tokyo_fix_prefx_0700_0830_20261011_v1.py`.
- Native smoke ledgers: `run_log/gotobi_lse_bidask_execution_pilot_20261011_v1/engineering_smoke/runs/*`.
- Source quote SHA256 and fill-oracle results:
  `run_log/gotobi_lse_bidask_execution_pilot_20261011_v1/engineering_smoke/smoke_result.json`.
- Export-readiness gate: `run_log/gotobi_lse_bidask_execution_pilot_20261011_v1/full/export_readiness.json`.

The full project's unrelated dirty files were preserved and no commit/push occurred.
