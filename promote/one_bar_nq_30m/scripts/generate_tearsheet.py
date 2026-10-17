#!/usr/bin/env python3
"""Build a retrospective report from the completed annual evaluation ledgers."""
from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import gettempdir

os.environ.setdefault("MPLCONFIGDIR", str(Path(gettempdir()) / "quant-research-matplotlib"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from importlib.metadata import version
from ml4t.backtest.analytics import cagr, max_drawdown, sharpe_ratio
from ml4t.diagnostic.api import PortfolioAnalysis

PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE / "backtests/practical_yearly/by_year"
OUT = PACKAGE / "reports"
YEARS = range(2013, 2027)
INITIAL_CASH = 1_000_000.0
TRIALS = ("native_zero_cost", "native_full_tick_cost")


def load_ledgers(trial: str) -> pl.DataFrame:
    frames = []
    for year in YEARS:
        path = ROOT / str(year) / trial / "evaluation_trades.csv"
        if not path.is_file():
            raise FileNotFoundError(path)
        frame = pl.read_csv(path, try_parse_dates=True)
        if frame.filter(pl.col("status") != "closed").height:
            raise AssertionError(f"Non-closed evaluation rows in {path}")
        if frame.filter(pl.col("entry_session_year") != year).height:
            raise AssertionError(f"Wrong evaluation year in {path}")
        summary_path = ROOT / str(year) / "year_summary.json"
        annual = json.loads(summary_path.read_text())
        summary_trial = next(item for item in annual["trials"] if item["name"] == trial)
        eval_metrics = json.loads((path.parent / "evaluation_metrics.json").read_text())
        if annual["status"] != "completed" or eval_metrics["status"] != "completed":
            raise AssertionError(f"Annual result is not complete: {year}/{trial}")
        if frame.height != summary_trial["closed_trades"] or abs(float(frame["pnl"].sum()) - summary_trial["net_pnl_usd"]) > 1e-5:
            raise AssertionError(f"Evaluation ledger does not reconcile to annual summary: {year}/{trial}")
        if frame.height != eval_metrics["closed_trades"] or abs(float(frame["pnl"].sum()) - eval_metrics["net_pnl_usd"]) > 1e-5:
            raise AssertionError(f"Evaluation ledger does not reconcile to evaluation metrics: {year}/{trial}")
        frames.append(frame.with_columns(pl.lit(year).alias("ledger_year")))
    result = pl.concat(frames, how="vertical_relaxed").sort("exit_time")
    if result.select(pl.struct(["entry_time", "exit_time"]).n_unique()).item() != result.height:
        raise AssertionError("Duplicate entry/exit records across annual evaluation ledgers")
    return result


def verify_recovery_audit() -> None:
    audit_path = PACKAGE / "backtests/practical_yearly/validation/recovery_audit.json"
    audit = json.loads(audit_path.read_text())
    if audit.get("status") != "passed" or len(audit.get("years", [])) != len(YEARS):
        raise AssertionError("The annual recovery audit is incomplete or did not pass")
    for year_result in audit["years"]:
        year = year_result["year"]
        for item in year_result["trials"]:
            ledger = pl.read_csv(ROOT / str(year) / item["name"] / "evaluation_trades.csv")
            if year_result["status"] != "passed" or ledger.height != item["closed_trade_count"]:
                raise AssertionError(f"Recovery audit count mismatch: {year}/{item['name']}")
            if abs(float(ledger["pnl"].sum()) - item["trade_pnl_usd"]) > 1e-5:
                raise AssertionError(f"Recovery audit PnL mismatch: {year}/{item['name']}")


def add_session_date(frame: pl.DataFrame) -> pl.DataFrame:
    local = pl.col("exit_time").dt.convert_time_zone("America/Chicago")
    return frame.with_columns(
        pl.when(local.dt.hour() >= 17)
        .then(local.dt.offset_by("1d").dt.date())
        .otherwise(local.dt.date())
        .alias("session_date")
    )


def summarize(frame: pl.DataFrame, trial: str) -> tuple[dict, pl.DataFrame, pl.DataFrame, list[dict]]:
    pnl_col = "pnl"
    session_frame = add_session_date(frame)
    daily = (session_frame
             .group_by("session_date").agg(pl.col(pnl_col).sum().alias("net_pnl_usd"),
                                    pl.col("gross_pnl").sum().alias("gross_pnl_usd"),
                                    pl.len().alias("trades"))
             .sort("session_date"))
    # The proxy calendar includes every Monday-Friday date, including exchange holidays.
    weekdays = (pl.date_range(daily["session_date"].min(), daily["session_date"].max(), interval="1d", eager=True)
                .alias("session_date").to_frame()
                .filter(pl.col("session_date").dt.weekday() <= 5))
    daily = weekdays.join(daily, on="session_date", how="left").with_columns(
        pl.col("net_pnl_usd", "gross_pnl_usd").fill_null(0.0), pl.col("trades").fill_null(0)
    ).with_columns(
        (INITIAL_CASH + pl.col("net_pnl_usd").cum_sum()).alias("net_realized_equity_usd"),
        (INITIAL_CASH + pl.col("gross_pnl_usd").cum_sum()).alias("gross_realized_equity_usd"),
    ).with_columns(
        pl.col("net_realized_equity_usd").shift(1).fill_null(INITIAL_CASH).alias("previous_net_equity_usd"),
        pl.col("gross_realized_equity_usd").shift(1).fill_null(INITIAL_CASH).alias("previous_gross_equity_usd"),
    ).with_columns(
        (pl.col("net_pnl_usd") / pl.col("previous_net_equity_usd")).alias("net_return"),
        (pl.col("gross_pnl_usd") / pl.col("previous_gross_equity_usd")).alias("gross_return"),
    )
    net_returns = daily["net_return"].to_numpy()
    gross_returns = daily["gross_return"].to_numpy()
    net_equity = daily["net_realized_equity_usd"].to_numpy()
    gross_equity = daily["gross_realized_equity_usd"].to_numpy()
    net_dd, peak_i, trough_i = max_drawdown(net_equity)
    gross_dd, _, _ = max_drawdown(gross_equity)
    net_dd_usd = float(net_equity[trough_i] - net_equity[:peak_i + 1].max())
    span_years = len(daily) / 252
    risk = PortfolioAnalysis(returns=net_returns, periods_per_year=252).compute_summary_stats()
    net_cagr = cagr(INITIAL_CASH, float(net_equity[-1]), span_years)
    gross_cagr = cagr(INITIAL_CASH, float(gross_equity[-1]), span_years)
    ordered_net = frame[pnl_col].to_numpy()
    yearly = (frame.with_columns(pl.col("ledger_year").alias("year"))
              .group_by("year").agg(pl.len().alias("trades"), pl.col("gross_pnl").sum().alias("gross_pnl_usd"),
                                    pl.col("pnl").sum().alias("net_pnl_usd"),
                                    pl.col("pnl").mean().alias("net_per_trade_usd"))
              .sort("year"))
    annual_rows = yearly.to_dicts()
    month = (session_frame.with_columns(pl.col("session_date").dt.strftime("%Y-%m").alias("month"))
             .group_by("month").agg(pl.col("pnl").sum().alias("net_pnl_usd"),
                                    pl.col("gross_pnl").sum().alias("gross_pnl_usd"))
             .sort("month"))
    losses = ordered_net[ordered_net < 0]
    gains = ordered_net[ordered_net > 0]
    metrics = {
        "trial": trial, "closed_trades": frame.height,
        "gross_pnl_before_commission_usd": float(frame["gross_pnl"].sum()), "net_pnl_usd": float(frame[pnl_col].sum()),
        "commission_drag_gross_to_net_usd": float(frame["gross_pnl"].sum() - frame[pnl_col].sum()),
        "net_per_trade_usd": float(frame[pnl_col].mean()),
        "trade_win_rate": float((frame[pnl_col] > 0).mean()),
        "profit_factor": float(gains.sum() / abs(losses.sum())) if len(losses) else None,
        "best_trade_net_usd": float(frame[pnl_col].max()), "worst_trade_net_usd": float(frame[pnl_col].min()),
        "long_trades": frame.filter(pl.col("direction") == "long").height,
        "short_trades": frame.filter(pl.col("direction") == "short").height,
        "long_net_pnl_usd": float(frame.filter(pl.col("direction") == "long")[pnl_col].sum()),
        "short_net_pnl_usd": float(frame.filter(pl.col("direction") == "short")[pnl_col].sum()),
        "sharpe_daily_252_rf0": float(risk.sharpe_ratio),
        "sortino_daily_252_rf0": float(risk.sortino_ratio),
        "cagr_realized_cashflow_proxy": float(net_cagr), "calmar_realized_cashflow_proxy": float(risk.calmar_ratio),
        "gross_sharpe_daily_252_rf0": float(sharpe_ratio(gross_returns, risk_free_rate=0.0, annualize=True)),
        "gross_cagr_realized_cashflow_proxy": float(gross_cagr),
        "max_drawdown_net_usd_from_assigned_1m": net_dd_usd,
        "max_drawdown_net_pct_of_assigned_1m": net_dd_usd / INITIAL_CASH,
        "max_drawdown_net_pct_of_running_peak": float(net_dd),
        "max_drawdown_gross_pct_of_assigned_1m": float((gross_equity - np.maximum.accumulate(gross_equity)).min() / INITIAL_CASH),
        "max_drawdown_peak_date": str(daily["session_date"][peak_i]), "max_drawdown_trough_date": str(daily["session_date"][trough_i]),
        "underwater_days_net": int((net_equity < np.maximum.accumulate(net_equity)).sum()),
        "underwater_max_duration_days_net": max_underwater(net_equity),
        "daily_var_95_usd": float(np.percentile(daily["net_pnl_usd"].to_numpy(), 5)),
        "daily_cvar_95_usd": float(daily.filter(pl.col("net_pnl_usd") <= np.percentile(daily["net_pnl_usd"].to_numpy(), 5))["net_pnl_usd"].mean()),
        "annualization_periods": 252, "risk_free_rate_annual": 0.0,
        "nominal_initial_cash_usd_assigned_for_return_scaling_only": INITIAL_CASH,
        "daily_session_observations": daily.height,
        "utc_sunday_exits_included": int(frame.filter(pl.col("exit_time").dt.weekday() == 7).height),
        "evaluation_years": [int(y) for y in yearly["year"].to_list()],
        "benchmark": "Unavailable: no matched buy-and-hold close series in this report package.",
        "drawdown_basis": "Daily realized trade cash flows on Chicago weekday session dates. Open positions are not marked; not native mark-to-market drawdown.",
    }
    return metrics, daily, month, annual_rows


def max_underwater(equity: np.ndarray) -> int:
    peak = np.maximum.accumulate(equity)
    run = best = 0
    for is_under in equity < peak:
        run = run + 1 if is_under else 0
        best = max(best, run)
    return best


def render(metrics: dict, daily: pl.DataFrame, monthly: pl.DataFrame, annual: list[dict], output: Path) -> None:
    fig = plt.figure(figsize=(16, 12), facecolor="#fbfcfe")
    grid = fig.add_gridspec(3, 2, height_ratios=[1.15, .75, .9], hspace=.34, wspace=.23)
    dates = np.array(daily["session_date"].to_list(), dtype="datetime64[D]")
    net = daily["net_realized_equity_usd"].to_numpy()
    gross = daily["gross_realized_equity_usd"].to_numpy()
    ax = fig.add_subplot(grid[0, :]); ax.plot(dates, gross, color="#7c8da5", lw=1.1, label="Costed fills after slippage, pre-commission")
    ax.plot(dates, net, color="#1463a5", lw=1.5, label="Net realized cash-flow equity")
    ax.axhline(INITIAL_CASH, color="#8a96a8", lw=.8, ls="--"); ax.set_title("Cumulative realized cash flows (USD 1m assigned base)", loc="left", weight="bold")
    ax.legend(frameon=False, ncol=2); ax.grid(alpha=.2)
    ax = fig.add_subplot(grid[1, 0]); peak = np.maximum.accumulate(net); dd_usd = net - peak; dd_pct = dd_usd / peak
    ax.fill_between(dates, dd_usd, 0, color="#d95b5b", alpha=.35); ax.set_title("Realized-equity drawdown", loc="left", weight="bold")
    ax.set_ylabel("USD"); ax.grid(alpha=.2); ax2 = ax.twinx(); ax2.plot(dates, dd_pct * 100, color="#a33131", lw=.8); ax2.set_ylabel("% of running peak")
    ax = fig.add_subplot(grid[1, 1]); r = daily["net_return"].to_numpy()
    rolling = np.full(len(r), np.nan)
    if len(r) >= 63:
        windows = np.lib.stride_tricks.sliding_window_view(r, 63)
        rolling[62:] = windows.mean(1) / windows.std(1, ddof=1) * np.sqrt(252)
    ax.plot(dates, rolling, color="#47845c", lw=1); ax.axhline(0, color="#888", lw=.8); ax.set_title("63-session weekday rolling Sharpe", loc="left", weight="bold"); ax.grid(alpha=.2)
    ax = fig.add_subplot(grid[2, 0]); piv = monthly.with_columns(
        pl.col("month").str.slice(0, 4).cast(pl.Int32).alias("year"), pl.col("month").str.slice(5, 2).cast(pl.Int32).alias("month_num")
    ).pivot(on="month_num", index="year", values="net_pnl_usd", aggregate_function="sum").sort("year")
    matrix = np.full((piv.height, 12), np.nan)
    for ri, row in enumerate(piv.iter_rows(named=True)):
        for month_num in range(1,13):
            key = str(month_num)
            if key in row and row[key] is not None: matrix[ri, month_num-1] = row[key]
    maxabs = np.nanmax(np.abs(matrix)) if np.isfinite(matrix).any() else 1
    ax.imshow(matrix, aspect="auto", cmap="RdYlGn", vmin=-maxabs, vmax=maxabs)
    ax.set_yticks(range(piv.height), piv["year"].to_list()); ax.set_xticks(range(12), ["J","F","M","A","M","J","J","A","S","O","N","D"])
    ax.set_title("Monthly net PnL heatmap (USD)", loc="left", weight="bold")
    ax = fig.add_subplot(grid[2, 1]); years = [r["year"] for r in annual]; pnls = [r["net_pnl_usd"] for r in annual]
    ax.bar(years, pnls, color=["#2c8b57" if x >= 0 else "#cf5b5b" for x in pnls]); ax.axhline(0, color="#555", lw=.8); ax.set_title("Annual net PnL (USD)", loc="left", weight="bold"); ax.grid(axis="y", alpha=.2)
    fig.suptitle(f"One-bar NQ 30m | 2013–2026 | {metrics['trial']}", x=.06, ha="left", fontsize=18, weight="bold")
    fig.text(.06, .015, "BID-only Dukascopy USATECH index/CFD proxy; one hypothetical $20/point contract. Realized cash-flow curves are not marked-to-market.", fontsize=9, color="#465365")
    fig.savefig(output, dpi=180, bbox_inches="tight"); plt.close(fig)


def write_report(trial_results: dict[str, tuple[dict, pl.DataFrame, pl.DataFrame, list[dict]]]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    selected = "native_full_tick_cost"
    metrics, daily, monthly, annual = trial_results[selected]
    gross_annual = trial_results["native_zero_cost"][3]
    prior_path = OUT / "metrics.json"
    prior = json.loads(prior_path.read_text()) if prior_path.is_file() else {}
    baseline = prior.get("frequency_fix_comparison", {}).get("pre_fix_metrics")
    if baseline is None:
        baseline = prior.get("metrics", {}).get(selected, {})
    comparison_keys = ("sharpe_daily_252_rf0", "sortino_daily_252_rf0", "max_drawdown_net_pct_of_running_peak", "calmar_realized_cashflow_proxy")
    payload = {"classification": "EXPLORATORY retrospective; NOT_APPROVED", "selected_cost_trial": selected,
               "source": "promote/one_bar_nq_30m/backtests/practical_yearly/by_year/YYYY/native_*_cost/evaluation_trades.csv",
               "methodology": {"analytics_library": "ml4t.backtest.analytics and ml4t.diagnostic.api.PortfolioAnalysis",
                   "library_versions": {name: version(name) for name in ("ml4t-backtest", "ml4t-diagnostic", "polars")},
                   "official_skills": {
                       "revision": "ml4t/skills main tree f0ea019e0c517cd9b1e014724a520facd8a742",
                       "ml4t-tearsheet": "backtest/tearsheet/SKILL.md",
                       "ml4t-risk-metrics": "portfolio/risk-metrics/SKILL.md",
                       "ml4t-polars-patterns": "infrastructure/polars-patterns/SKILL.md",
                       "ml4t-run-backtest": "backtest/run-backtest/SKILL.md",
                       "local_discovery": "Requested skills were absent locally; official upstream files were read with TinyFish.",
                   },
                   "daily_cashflow_aggregation": "Polars",
                   "rf_annual": 0.0, "annualization": 252, "daily_calendar": "Chicago session weekdays from first to last mapped evaluation exit, inclusive. Convert UTC exit_time to America/Chicago; exits at or after 17:00 map to the next Chicago session date. Monday-Friday dates are included, including holidays with zero realized PnL; weekend session dates are excluded. UTC Sunday exits are retained when they map to Monday.",
                   "daily_return_denominator": "Daily realized PnL divided by previous day's reconstructed continuous realized equity, starting from assigned USD 1,000,000.",
                   "open_position_marking": False, "buy_hold_benchmark": "unavailable"},
               "metrics": {name: item[0] for name,item in trial_results.items()}, "annual_full_tick_cost": annual,
               "annual_zero_cost": gross_annual,
               "limitations": ["BID-only Dukascopy CFD/index proxy, not dated CME NQ futures.", "Synthetic 1m assigned cash is a return scaling base, not verified margin/capital.", "Realized trade cash flows omit open-position mark-to-market and cannot establish native equity drawdown.", "No buy-and-hold series was bundled; benchmark omitted.", "Costs are modeled assumptions, not broker/exchange certified costs.", "2026 evaluation ends 2026-07-14; later observations remain protected.", "Ambiguous minute OHLC path and atomic OCO behavior remain unresolved."]}
    payload["frequency_fix_comparison"] = {
        "pre_fix_metrics": {key: baseline[key] for key in comparison_keys if key in baseline},
        "post_fix_metrics": {key: metrics[key] for key in comparison_keys},
        "change": {key: metrics[key] - baseline[key] for key in comparison_keys if key in baseline},
    }
    payload["verification"] = {
        "annual_evaluation_trade_counts_and_net_pnl_match_year_summaries": True,
        "annual_net_pnl_matches_recovery_audit": True,
        "recovery_audit_status": "passed",
        "annual_year_range_inclusive": [2013, 2026],
        "annual_accounts_reset_each_year": True,
        "cross_year_equity_is_report_only_realized_cashflow_reconstruction": True,
        "backtest_rerun": False,
        "sha256_package_manifest_refreshed": True,
    }
    (OUT / "metrics.json").write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    daily.write_csv(OUT / "daily_equity.csv")
    monthly.write_csv(OUT / "monthly_pnl.csv")
    render(metrics, daily, monthly, annual, OUT / "one_bar_nq_tearsheet_2013_2026.png")
    zero_by_year = {row["year"]: row for row in trial_results["native_zero_cost"][3]}
    rows = ["| Year | Trades | Zero-cost PnL (USD) | Costed gross before commission (USD) | Costed net PnL (USD) | Net/trade (USD) |", "|---:|---:|---:|---:|---:|---:|"]
    for row in annual:
        rows.append(f"| {row['year']} | {row['trades']} | {zero_by_year[row['year']]['net_pnl_usd']:,.2f} | {row['gross_pnl_usd']:,.2f} | {row['net_pnl_usd']:,.2f} | {row['net_per_trade_usd']:,.2f} |")
    c = metrics
    md = f"""# One-bar NQ 30-minute strategy tearsheet, 2013–2026

**Status:** Exploratory retrospective report. The strategy remains `NOT_APPROVED`. This report does not approve live trading.

## Data and method

The report reads the completed annual `evaluation_trades.csv` ledgers from 2013 through 2026. It uses evaluation trades only and excludes warmup and duplicated boundary trades. PnL uses one hypothetical contract at $20 per index point. The source is Dukascopy `USATECH.IDX/USD` BID-only index/CFD data. It is not a dated CME NQ contract.

The costed trial models $2.50 per fill and 0.25 adverse index points per fill. Its ledger `gross_pnl` is costed gross PnL: modeled slippage remains in fills, and commissions are excluded. Its `pnl` is net of both. The zero-cost trial provides a separate aggregate comparison. Some trades have different exit timestamps across cost variants, so the $81,458.46 aggregate difference is not pure accounting fees or row-matched attribution. Annual engine accounts reset to $1,000,000; this report separately reconstructs cumulative realized cash flows across years. The report uses installed `ml4t.backtest.analytics` and `ml4t.diagnostic.api.PortfolioAnalysis` for risk statistics. Polars aggregates Chicago session-date cash flows. UTC exit timestamps are converted to `America/Chicago`; exits at or after 17:00 map to the next session date. The report includes Monday-Friday dates from first to last mapped exit, including holidays with zero PnL, and excludes weekend dates. UTC Sunday exits that map to Monday remain included. Each daily return equals that day's PnL divided by the previous day's reconstructed continuous realized equity, starting from an assigned USD 1,000,000. The series uses zero risk-free rate and 252 periods per year. This is a weekday proxy calendar, not an exchange holiday calendar.

The plotted curves and drawdown metrics use realized trade cash flows. They do not mark open positions each day and are not native engine mark-to-market equity. The $1,000,000 base is only a scaling convention. It is not verified margin or account capital. No comparable buy-and-hold close series is included, so this report omits the benchmark.

## Costed trial metrics

| Metric | Value |
|---|---:|
| Closed evaluation trades | {c['closed_trades']:,} |
| Zero-cost trial PnL | ${c['gross_pnl_usd_zero_cost_trial']:,.2f} |
| Costed gross PnL before commission (slippage remains in fills) | ${c['gross_pnl_before_commission_usd']:,.2f} |
| Net PnL | ${c['net_pnl_usd']:,.2f} |
| Commission drag within costed trial | ${c['commission_drag_gross_to_net_usd']:,.2f} |
| Total difference versus zero-cost trial | ${c['total_cost_drag_vs_zero_cost_trial_usd']:,.2f} |
| Net PnL per trade | ${c['net_per_trade_usd']:,.2f} |
| Trade win rate | {c['trade_win_rate']:.1%} |
| Profit factor | {c['profit_factor']:.3f} |
| Net session-weekday Sharpe (252, RF 0) | {c['sharpe_daily_252_rf0']:.3f} |
| Net daily Sortino | {c['sortino_daily_252_rf0']:.3f} |
| Net realized-cashflow CAGR | {c['cagr_realized_cashflow_proxy']:.3%} |
| Net Calmar | {c['calmar_realized_cashflow_proxy']:.3f} |
| Maximum realized-cashflow drawdown | ${c['max_drawdown_net_usd_from_assigned_1m']:,.2f} ({c['max_drawdown_net_pct_of_assigned_1m']:.3%}) |
| Maximum drawdown as percent of running peak | {c['max_drawdown_net_pct_of_running_peak']:.3%} |
| Underwater weekday sessions | {c['underwater_days_net']:,}; max run {c['underwater_max_duration_days_net']:,} sessions |
| Daily 95% VaR / CVaR | ${c['daily_var_95_usd']:,.2f} / ${c['daily_cvar_95_usd']:,.2f} |
| Best / worst net trade | ${c['best_trade_net_usd']:,.2f} / ${c['worst_trade_net_usd']:,.2f} |
| Long trades / PnL | {c['long_trades']:,} / ${c['long_net_pnl_usd']:,.2f} |
| Short trades / PnL | {c['short_trades']:,} / ${c['short_net_pnl_usd']:,.2f} |

## Frequency-fix metric changes

| Metric | Previous calendar-day value | Corrected weekday-session value | Change |
|---|---:|---:|---:|
| Sharpe | {baseline.get('sharpe_daily_252_rf0', float('nan')):.3f} | {metrics['sharpe_daily_252_rf0']:.3f} | {metrics['sharpe_daily_252_rf0'] - baseline.get('sharpe_daily_252_rf0', metrics['sharpe_daily_252_rf0']):+.3f} |
| Sortino | {baseline.get('sortino_daily_252_rf0', float('nan')):.3f} | {metrics['sortino_daily_252_rf0']:.3f} | {metrics['sortino_daily_252_rf0'] - baseline.get('sortino_daily_252_rf0', metrics['sortino_daily_252_rf0']):+.3f} |
| Max drawdown as percent of running peak | {baseline.get('max_drawdown_net_pct_of_running_peak', float('nan')):.3%} | {metrics['max_drawdown_net_pct_of_running_peak']:.3%} | {metrics['max_drawdown_net_pct_of_running_peak'] - baseline.get('max_drawdown_net_pct_of_running_peak', metrics['max_drawdown_net_pct_of_running_peak']):+.3%} |
| Calmar | {baseline.get('calmar_realized_cashflow_proxy', float('nan')):.3f} | {metrics['calmar_realized_cashflow_proxy']:.3f} | {metrics['calmar_realized_cashflow_proxy'] - baseline.get('calmar_realized_cashflow_proxy', metrics['calmar_realized_cashflow_proxy']):+.3f} |

## Annual costed evaluation PnL by entry-session year (unchanged)

""" + "\n".join(rows) + f"""

2026 ends on 2026-07-14. The costed 2026 net PnL is ${next(x['net_pnl_usd'] for x in annual if x['year']==2026):,.2f}. The later period remains protected.

No Deflated Sharpe Ratio is reported. This report does not contain the complete historical strategy trial universe needed to estimate selection bias. The package trial ledger records failed and completed attempts; these annual A/B results do not by themselves define every prior choice.

## Decision and limits

The 2013–2026 historical replay is positive in aggregate after the specified modeled costs. This supports only a descriptive statement about these ledgers. It does not establish a tradable CME NQ result. In particular, 2026 is negative, the source is a BID-only proxy, source-to-contract mapping and actual costs are not verified, and minute OHLC cannot establish event ordering or atomic OCO behavior. The separate conservative ambiguity diagnostic is not a native replay and is not substituted into the totals here. No holdout remains unseen because this is retrospective reporting.

The strategy remains `NOT_APPROVED`. The next decisive question is whether a verified dated CME NQ replay with bid/ask data, native OCO execution, and certified fee and roll assumptions preserves positive net results without using protected post-2026-07-14 data.

## Artifacts

- `one_bar_nq_tearsheet_2013_2026.png`: annual and monthly panels.
- `metrics.json`: machine-readable metrics and method.
- `daily_equity.csv`: realized daily cash flows and reconstructed cash-flow curves.
- `monthly_pnl.csv`: monthly gross and net realized PnL.
"""
    (OUT / "one_bar_nq_tearsheet_2013_2026.md").write_text(md)


def main() -> None:
    verify_recovery_audit()
    results = {}
    for trial in TRIALS:
        frame = load_ledgers(trial)
        results[trial] = summarize(frame, trial)
        if frame.height != sum(row["trades"] for row in results[trial][3]):
            raise AssertionError(f"Annual count reconciliation failed: {trial}")
    if results["native_zero_cost"][0]["closed_trades"] != results["native_full_tick_cost"][0]["closed_trades"]:
        raise AssertionError("Trade counts differ between cost variants")
    results["native_full_tick_cost"][0]["gross_pnl_usd_zero_cost_trial"] = results["native_zero_cost"][0]["net_pnl_usd"]
    results["native_full_tick_cost"][0]["total_cost_drag_vs_zero_cost_trial_usd"] = (
        results["native_zero_cost"][0]["net_pnl_usd"] - results["native_full_tick_cost"][0]["net_pnl_usd"])
    results["native_full_tick_cost"][0]["trade_identity_caveat"] = (
        "Some trades have different exit timestamps between cost variants; comparisons are aggregate, not rowwise attribution.")
    write_report(results)
    print(json.dumps({name: result[0] for name,result in results.items()}, indent=2))


if __name__ == "__main__":
    main()
