# Gotobi research companion v1.0.3: exact-method LSE replication bridge

**Status: COMPLETED / EXPLORATORY / NOT_APPROVED.**

We reproduced the original companion's date and bar arithmetic on the
available 2020-2025 canonical LSE one-minute OHLCV, not its original
HistData fixed-UTC-5 bid candles over 2006-2025. The latter source
and 2006-2019 interval cannot be claimed reproduced by this run.

## Original author source

Original companion v1.0.3 `METHODOLOGY.md`:
- Nominal 5/10/15/20/25/final CALENDAR date; roll each back to last Japan bank day.
- Enter USDJPY long at 03:00 JST OPEN.
- Exit 09:55 JST minute-bar CLOSE; not the 09:54/09:55 OPEN.
- Require only the entry bar and the chosen exit bar, not all 416 intermediate bars.
- Cost ladder 0, 0.4, 1.0, 1.5 hypothetical pips.
- Source profit factors and event-annualized Sharpe are not continuous-account metrics.

## Fixed bridge: 2020-2025 LSE reference feed

| Rule change | Completed | Gross pips/trade | Net pips/trade @ 1pip |
|---|---:|---:|---:|
| B0_previous_calendar_strict_0954open | 290 | +2.268 | +1.268 |
| B1_paper_calendar_strict_0954open | 294 | +2.576 | +1.576 |
| B2_paper_calendar_boundary_0954open | 370 | +3.492 | +2.492 |
| B3_paper_calendar_boundary_0955open | 370 | +3.828 | +2.828 |
| B4_paper_calendar_boundary_0955close | 370 | +2.171 | +1.171 |
| B5_paper_calendar_boundary_0959close | 370 | +1.448 | +0.448 |

## Matched-date bridge (not a causal decomposition)

| Change | Shared dates | New cohort | Matched gross delta | Cohort gross delta |
|---|---:|---:|---:|---:|
| B0_previous_calendar_strict_0954open -> B1_paper_calendar_strict_0954open | 272 | 22 | +0.000 | +0.307 |
| B1_paper_calendar_strict_0954open -> B2_paper_calendar_boundary_0954open | 294 | 76 | +0.000 | +0.917 |
| B2_paper_calendar_boundary_0954open -> B3_paper_calendar_boundary_0955open | 370 | 0 | +0.336 | +0.336 |
| B3_paper_calendar_boundary_0955open -> B4_paper_calendar_boundary_0955close | 370 | 0 | -1.658 | -1.658 |
| B4_paper_calendar_boundary_0955close -> B5_paper_calendar_boundary_0959close | 370 | 0 | -0.723 | -0.723 |

## Author exact rule, paper-style statistics on LSE

- Author scheduled events: **429**.
- Complete exact-price windows: **370**; incomplete: 59.
- Gross mean **+2.171 pips**.
- Mean after 1pip hypothetical round trip: **+1.171 pips**.
- Event-annualized Sharpe (author convention) **0.432**.
- Published HistData 2006-2025: 1,175 events and +4.54 gross pips, which is a distinct provider/period.

## Comparison with ordinary mornings and weak years

- Same-clock ordinary business days, exact close: mean gross -0.442 pips, n=827.
- Controlled Gotobi premium HAC5: {'status': 'ESTIMATED', 'n': 1197, 'coef': 0.0002963050070595706, 'ci95': [-9.071174230871411e-06, 0.0006016811883500126], 'p': 0.057192926681753006, 'holm2_p': 0.11438585336350601}.
- Gotobi absolute net-return HAC5: {'status': 'ESTIMATED', 'n': 370, 'coef': 0.00012000388568110934, 'ci95': [-9.862114044109517e-05, 0.00033862891180331384], 'p': 0.28112785510360294, 'holm2_p': 0.28112785510360294}.
- Retrospective 2024-25: n=123, gross -1.809 pips, net -2.809 pips/trade.

| Year | Trades | Mean gross pips | Mean net pips |
|---|---:|---:|---:|
| 2020 | 62 | +4.290 | +3.290 |
| 2021 | 61 | +4.884 | +3.884 |
| 2022 | 62 | +8.158 | +7.158 |
| 2023 | 62 | -0.710 | -1.710 |
| 2024 | 62 | -3.134 | -4.134 |
| 2025 | 61 | -0.462 | -1.462 |

## Separate native ML4T market execution

- Native 03:00 OPEN to 09:56 OPEN, 1pip hypothetical cost: n=370 and PnL USD +451.30.
- Native account Sharpe (flat-inclusive) +0.464, not the author's event-annualized statistic.
- Native/source fill error < 9.7e-15 JPY, JPY account reconciliation < 7e-09.
- The exact paper 09:55 close is a bar-field price, **not verified executable at that close**.
- Canonical LSE OHLCV is not the paper's HistData bid feed. Real broker quotes/cost remain unknown.
- The 2020-2025 LSE period was already inspected in earlier Gotobi programs; NOT new unseen OOS.
- No Sept-Oct2026 protected data were read, no commit/push, no live order.

## Reproduction

- Frozen declaration: `config/research_sessions/gotobi_exact_paper_bridge_20261011_v1.yaml`.
- Source manifest: `run_log/gotobi_exact_paper_bridge_20261011_v1/T0_source_gate/result.json`.
- Exact paper event ledger: `run_log/gotobi_exact_paper_bridge_20261011_v1/author_paper_exact_trades.parquet`.
- Native executed orders/trades: `run_log/gotobi_exact_paper_bridge_20261011_v1/native/`.
- Trial evidence: `run_log/gotobi_exact_paper_bridge_20261011_v1/T*/result.json`.

**Decision: research discrepancy audited; no trading strategy qualified.**
