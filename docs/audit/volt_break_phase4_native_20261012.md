# VOLT BREAK — Phase 4 native ML4T backtest (2026-10-12)

**Outcome:** HISTORICAL BACKTEST COMPLETED. **Research decision: NOT_APPROVED / negative robustness**.

## Method / source

- Session: `volt_break_nq_20261012`. Predeclared historical rules in
  `config/research_sessions/volt_break_nq_phase4_20261012.yaml`. Versioned
  lifecycle remediation and conservative entry-minute convention in
  `config/research_sessions/volt_break_nq_phase4_native_adapter_20261012.yaml`.
- Engine: installed `ml4t-backtest 0.1.7`, native Engine/Broker cash, margin,
  order matching, fills, trade ledger and commission/slippage models.
- Minimal adapter `scripts/volt_break_native_adapter_20261012.py` calls native
  Broker position-risk evaluation immediately **after** native NEXT_BAR
  market entry fill on the same 1-minute row. On a first-bar stop/target touch,
  the native Broker fills an exit and records it in its ledger.
  This solves the earlier unprotected-entry-minute issue, subject to the
  1-minute OHLC path assumption. No custom/manual fill or cash simulation.
- Long only, maximum 3 actual entries per day. At fully observed 30-minute
  close (09:59, 10:29, ..., 13:59 one-minute row), if close is above both the
  fixed midnight CT noise barrier and anchored VWAP, submit next-open market
  order. One illustrative NQ-equivalent contract at $20 per point.
- Noise barrier = 00:00 CT source open + 0.30 x average of preceding 15
  completed Globex-like daily true ranges. Two **pre-registered prior-day
  coverage rules**, >=1300 one-minute observations or >=1000, are separately
  reported. The 1000-minute case was registered after an earlier Phase 3
  data-coverage finding, not selected for better performance.
- Provider-unit cumulative (H+L+C)/3 proxy VWAP from 00:00 CT through known
  30-minute signal close. No macro filter.
- Risk: custom fixed-point stop-first native PositionRule, +40 index points
  target / -75 index points stop. Exact observed high/low sequence of the
  source minute is **not** known. Stop-first when both touch is an explicit
  conservative simulation convention. Gaps use source-open prices.
- Hard market exit submitted after 14:29 data, filled by native engine at
  14:30 OPEN. The 14:30 data-feed event uses **only its observed OPEN** for
  O/H/L/C, to prevent exposure to price movement after mandatory exit.
- Data: immutable canonical `index_minute_NQ` Dukascopy
  `USATECH.IDX/USD` BID index CFD, minute OHLCV, 2018-2025 partitions
  (2018 warmup), never the actual dated NQ futures contract. Source hash
  manifest match **96/96**. All 2026 market outcomes untouched.
- Phase 2 full 00:00-14:30 CT source coverage mask: 1,576 days across
  2019-2025, of which 156 (strict) and 491 (relaxed) have causal ATR
  eligibility after prior-session qualification. This is a retrospective
  development sample, not unseen OOS.
- Capital and cost assumptions: hypothetical $1,000,000 account, one contract,
  $25,000 initial / $20,000 maintenance margin. Cost trial zero, illustrative
  $2.50 per fill + 0.25 adverse points/fill, and double $5 per fill +0.50 points.
  These are *assumptions*, not actual CME/CFD transaction-cost calibration.

## Full native backtest results

| Prior-session ATR coverage | Cost | Native completed trades | Win rate | P&L USD | Expectancy USD/trade | Profit factor |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| strict >=1300 | zero | 112 | 62.5% | +2,972.16 | +26.54 | 1.064 |
| strict >=1300 | illustrative | 110 | 60.9% | +155.84 | +1.42 | 1.003 |
| strict >=1300 | 2x | 110 | 60.9% | -1,079.16 | -9.81 | 0.977 |
| relaxed >=1000 | zero | 389 | 60.4% | -5,507.38 | -14.16 | 0.966 |
| relaxed >=1000 | illustrative | 387 | 59.9% | -11,907.46 | -30.77 | 0.928 |
| relaxed >=1000 | 2x | 384 | 59.6% | -17,821.84 | -46.41 | 0.894 |

The cost simulations may change trade counts because entry and exit fill
prices alter absolute barriers, time spent in the market, and reentry timing.
Native trade P&L includes all configured fees and fills.

### Daily equity risk: all 1,576 qualified historical CT days

These ratios include zero-return dates when a particular ATR variant was
ineligible. This is **not** the higher and misleading annualization computed
over only 156 or 491 actively eligible days.

| ATR coverage | Cost | Full-calendar Sharpe | Calmar | Max DD of $1M account |
| --- | --- | ---: | ---: | ---: |
| strict | zero | +0.115 | +0.052 | -0.91% |
| strict | illustrative | +0.008 | +0.002 | -1.02% |
| strict | 2x | -0.039 | -0.016 | -1.09% |
| relaxed | zero | -0.106 | -0.036 | -2.47% |
| relaxed | illustrative | -0.234 | -0.073 | -2.63% |
| relaxed | 2x | -0.353 | -0.100 | -2.86% |

The Sharpe and Calmar values represent returns on a **$1m account**
that trades only one contract. They do not measure margin-only returns.
No leverage scaling or stop adjustment was introduced.

### Year consistency (illustrative cost)

- Strict cohort has positive P&L in 2019, 2023, and 2025
  (**3 of 7 years**).
- Relaxed cohort has positive P&L in 2021 and 2025
  (**2 of 7 years**). It lost approximately $9.3k in 2022 and $6.6k
  in 2024, while making approximately $8.9k in 2021.
- The relaxed cohort is negative with **zero** costs. Win rate is about 60%,
  lower than the 65.2% approximate break-even for a pure +40/-75 target/stop
  payoff without time exits. Hard-time exits make that simple break-even
  calculation only illustrative.

## Independent verification

- `tests/test_volt_break_native_adapter_20261012.py` and
  `tests/test_volt_break_phase4_execution_20261012.py`: **16 passed**.
  Includes synthetic entry-minute protected stop-first exit, same-minute
  conflicting price touches, native fill reconciliation, gap exit behavior,
  timing, original independent bracket failure regression, fixed points.
- Reproduced source identity check: **96/96 SHA256 matching** partitions.
- Independent auditor:
  `scripts/audit_volt_break_phase4_native_20261012.py`.
  It rebuilt signal eligibility from the 2018-2025 canonical partitions
  and matched every native BUY fill to a completed source 30m bar ending
  one minute before the entry boundary.
- All six native trade CSV ledgers reconciled to final Engine equity to
  under 0.0001 USD. All entries were on 30m CT boundaries between 10:00
  and 14:00, and there were at most 3 filled entries per CT date.
- Each position ended on its opening CT calendar day, and every exit
  occurred by 14:30 CT. No residual open positions or 2026 market outcomes.
- Each native buy had one native sell. The adapter registered and evaluated
  entry-bar risk on each newly opened position. The relaxed cohort had one
  trade with same-entry-minute protective exit; the strict cohort had none.
- Signal *submission attempts* exceed actual fills by a small number.
  The study only counts native accepted and executed orders in performance.
  The exact reason each extra signal submission did not become an Engine
  fill has not been separately reconstructed. No rejected orders were
  reported by native `result.metrics`. This is a residual execution
  diagnostic to resolve before any later production replication.
- Zero recorded both-touch exits at the trade's exit minute in these
  six runs, but the source data cannot establish intraminute true order
  even for events where both levels are crossed.

## Trial accounting and reproducibility

All six variant x cost trials are saved under:
`run_log/research_sessions/volt_break_nq_20261012/phase4_native/{variant}/{cost}/`.
Each contains `trades.csv`, `fills.csv`, `daily_equity.csv`,
`yearly.csv`, and `summary.json`.

- Consolidated native audit:
  `run_log/research_sessions/volt_break_nq_20261012/phase4_native/phase4_independent_audit_20261012.json`
- Final extended trial ledger:
  `run_log/research_sessions/volt_break_nq_20261012/phase4_native/phase4_trial_ledger_final_20261012.json`
- Runner: `scripts/run_volt_break_phase4_native_20261012.py`
- Native entry-bar adapter: `scripts/volt_break_native_adapter_20261012.py`
- Auditing script: `scripts/audit_volt_break_phase4_native_20261012.py`
- Git branch `main` at HEAD `c095faab89835c49f4cd6fd66d1a9ed922709039`.
  Unrelated prior dirty work was untouched. No Git commit/push or live orders.

## Decision

**Phase 4 reproducible native backtest: VERIFIED under declared synthetic
execution and BID CFD-proxy assumptions.** Research adoption:
**NOT APPROVED**. The strict variant's +$155.84 net on 110 trades over
2019–2025 is within execution-model uncertainty, and doubles costs to a
loss. The larger but lower-quality ATR-coverage variant loses money with
zero cost, and further under costs.

This is not a faithful reproduction of actual CME NQ execution:
no dated futures/rolls, no exchange VWAP, source BID only (ASK unavailable),
no tick-level intraminute path, exact original ATR definition unconfirmed.
The historical 2019–2025 sample is already observed. The protected 2026
holdout remains sealed. More parameter optimization on this sample
would constitute a new exploratory search, not independent validation.
