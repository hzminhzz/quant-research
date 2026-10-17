# One-bar execution remediation specification

Status: `EXPLORATORY`; approval: `NOT_APPROVED`.

The frozen rule remains 50 complete prior 30-minute bars, 30-minute decisions, long and short stop entries, a next 30-minute opening market exit, a $1,000 protective stop, no more than two fills per Chicago session day, and one indicative contract at $20 per point. The account remains $1,000,000 initial cash with leverage and short selling enabled, a $25,000 initial margin, and a $20,000 maintenance margin per contract. No parameter selection is allowed.

The frozen cost scenarios are zero cost and adverse slippage of 0.25 index points plus a $2.50 fee on each fill. The full-history cost scenarios were not run because the native OCO limitation blocks a valid simulation.

The input is the local ML4T Data `index_minute_NQ` store. It is a Dukascopy USATECH.IDX/USD BID index CFD proxy. It is not CME NQ. The evaluation boundary is 2013-01-01 through 2026-07-14 inclusive. Later observations are protected and were not read.

The execution falsifiers are: stop gaps fill at the worse of open and trigger; missing source opens do not create fills; both opposing stops cannot create a fictitious hedge; ledger costs reconcile without charging slippage twice; and every 30-minute signal uses 50 complete prior bars only.

## Frozen methods

| Skill | Path | Invariant used | Check |
|---|---|---|---|
| `ml4t-run-backtest` | `.agents/skills/ml4t-run-backtest/SKILL.md` | Execute orders through native event-driven `Engine` | Native synthetic fill fixtures |
| `ml4t-lookahead-bias` | `.agents/skills/ml4t-lookahead-bias/SKILL.md` | Signals use completed past bars only | Partial-bin decision and fill-path test |
| `ml4t-calendar-ops` | `.agents/skills/ml4t-calendar-ops/SKILL.md` | Use UTC instants and Chicago session dates | Repeated-hour DST test |
| `ml4t-polars-patterns` | `.agents/skills/ml4t-polars-patterns/SKILL.md` | Keep transformations in Polars | Synthetic feed test |
| `ml4t-validate-data` | `.agents/skills/ml4t-validate-data/SKILL.md` | Validate rows and preserve missing observations | Source audit; no synthetic missing prices |
| `ml4t-cost-model` | `.agents/skills/ml4t-cost-model/SKILL.md` | Separate commission and fill-price slippage | No full cost replay because exact OCO is blocked |
| `ml4t-continuous-futures` | `.agents/skills/ml4t-continuous-futures/SKILL.md` | Do not claim CFD proxy is a tradable futures series | Instrument identity recorded |

The installed package is `ml4t-backtest 0.1.7`. Its `FillEngine.check_stop_fill` uses the bar open when the open crosses the stop, and uses the trigger otherwise. Its public `Broker.submit_order` has no OCO group argument. The bounded test verifies the gap behavior through `Engine`; it does not modify the installed package.

## Exact execution status

Native stop-gap semantics are verified for long and short entries and protective exits. Atomic OCO is unavailable. Same-minute opposing stop crossings and same-minute entry/protective-stop sequencing therefore remain unresolved. No full-history replay is valid while those events can create false exposure. The mission's full-history trial is blocked. No post-hoc PnL adjustment substitutes for a replay.

No Dukascopy ASK or tick source is present in the local canonical store. No ASK was synthesized. The $2.50 fee and 0.25-point adverse fill stress remains an unrun full-history trial because of the OCO blocker.
