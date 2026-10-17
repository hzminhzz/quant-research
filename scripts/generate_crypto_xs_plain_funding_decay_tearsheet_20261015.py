"""Generate an ML4T-style HTML tearsheet for the 2024-2025 funding decay validation.

Methodology authority:
- ML4T tearsheet skill: cumulative return, drawdown, rolling Sharpe, monthly
  heatmap, and metrics table.
- ml4t.diagnostic.api.PortfolioAnalysis for summary metrics.
- Crypto daily annualization uses 365 periods/year.
- Economic equity is terminalized at zero at first insolvency.
- Gross is a reporting proxy: observed net equity plus recorded execution costs.
  It is not a separately rerun zero-cost portfolio and is labeled accordingly.
"""
from __future__ import annotations

import base64
import io
import json
import math
from datetime import UTC, datetime, timedelta
from html import escape
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from ml4t.diagnostic.api import PortfolioAnalysis

ROOT = Path(__file__).resolve().parents[1]
SESSION = "crypto_xs_plain_funding_decay_validation_20261015_v1"
SESSION_DIR = ROOT / "run_log" / "research_sessions" / SESSION
VALID = SESSION_DIR / "validation"
FORENSICS = SESSION_DIR / "decay_forensics"
FINAL = SESSION_DIR / "validation_final"
OUT = ROOT / "docs" / "audit" / f"{SESSION}_tearsheet"

INITIAL_CASH = 100_000.0
PERIODS_PER_YEAR = 365


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def as_naive_dt(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def first_nonpositive_state(path: Path) -> tuple[datetime, float]:
    state = pl.read_parquet(path).sort("timestamp")
    bad = state.filter(pl.col("equity") <= 0)
    if bad.is_empty():
        raise RuntimeError(f"no insolvency in {path}")
    row = bad.row(0, named=True)
    return as_naive_dt(row["timestamp"]), float(row["equity"])


def terminalize_daily(path: Path, cutoff: datetime) -> pl.DataFrame:
    state = pl.read_parquet(path).sort("timestamp")
    prior = state.filter(pl.col("timestamp") < cutoff)
    if prior.is_empty():
        raise RuntimeError("no pre-insolvency state")
    daily = (
        prior.with_columns(pl.col("timestamp").dt.date().alias("date"))
        .group_by("date")
        .agg(pl.col("equity").last().alias("equity"))
        .sort("date")
    )
    terminal_date = cutoff.date()
    daily = daily.filter(pl.col("date") < terminal_date)
    terminal = pl.DataFrame({"date": [terminal_date], "equity": [0.0]})
    return pl.concat([daily, terminal]).sort("date")


def daily_returns(equity: pl.DataFrame) -> pl.DataFrame:
    return equity.with_columns(
        (pl.col("equity") / pl.col("equity").shift(1) - 1.0)
        .fill_null(0.0)
        .alias("return")
    )


def cost_proxy_equity(
    observed_state_path: Path,
    trades_path: Path,
    cutoff: datetime,
) -> tuple[pl.DataFrame, dict]:
    state = pl.read_parquet(observed_state_path).sort("timestamp")
    before = state.filter(pl.col("timestamp") < cutoff)
    daily = (
        before.with_columns(pl.col("timestamp").dt.date().alias("date"))
        .group_by("date")
        .agg(pl.col("equity").last().alias("net_equity"))
        .sort("date")
    )
    trades = pl.read_parquet(trades_path)
    realized = trades.filter(
        pl.col("exit_time").is_not_null() & (pl.col("exit_time") <= cutoff)
    ).with_columns(
        (pl.col("fees") + pl.col("total_slippage_cost")).alias("execution_cost"),
        pl.col("exit_time").dt.date().alias("date"),
    )
    daily_costs = (
        realized.group_by("date")
        .agg(pl.col("execution_cost").sum().alias("daily_cost"))
        .sort("date")
    )
    proxy = (
        daily.join(daily_costs, on="date", how="left")
        .with_columns(pl.col("daily_cost").fill_null(0.0))
        .with_columns(pl.col("daily_cost").cum_sum().alias("cumulative_cost"))
        .with_columns(
            (pl.col("net_equity") + pl.col("cumulative_cost")).alias("equity")
        )
        .select("date", "equity", "cumulative_cost")
    )
    actual_at_cutoff = (
        state.filter(pl.col("timestamp") == cutoff)
        .select("equity")
        .item()
    )
    costs_to_cutoff = float(realized["execution_cost"].sum())
    gross_terminal = max(float(actual_at_cutoff) + costs_to_cutoff, 0.0)
    terminal = pl.DataFrame(
        {
            "date": [cutoff.date()],
            "equity": [gross_terminal],
            "cumulative_cost": [costs_to_cutoff],
        }
    )
    proxy = pl.concat(
        [proxy.filter(pl.col("date") < cutoff.date()), terminal]
    ).sort("date")
    return proxy, {
        "execution_cost_usdt": costs_to_cutoff,
        "net_equity_at_cutoff": float(actual_at_cutoff),
        "gross_proxy_equity_at_cutoff": gross_terminal,
    }


def portfolio_metrics(frame: pl.DataFrame) -> dict:
    ret = daily_returns(frame)
    analysis = PortfolioAnalysis(
        returns=ret["return"].to_numpy(),
        dates=ret["date"],
        periods_per_year=PERIODS_PER_YEAR,
        risk_free=0.0,
    )
    metrics = analysis.compute_summary_stats()
    out = {}
    for key, value in metrics.__dict__.items():
        if value is None:
            out[key] = None
        elif isinstance(value, (int, float, np.number)):
            out[key] = float(value)
        else:
            out[key] = str(value)
    return out


def rolling_sharpe(frame: pl.DataFrame, window: int = 63) -> pl.DataFrame:
    ret = daily_returns(frame)
    return (
        ret.with_columns(
            pl.col("return").rolling_mean(window, min_samples=window).alias("mu"),
            pl.col("return").rolling_std(window, min_samples=window).alias("sd"),
        )
        .with_columns(
            (pl.col("mu") / pl.col("sd") * math.sqrt(PERIODS_PER_YEAR))
            .alias("rolling_sharpe")
        )
        .select("date", "rolling_sharpe")
    )


def drawdown(frame: pl.DataFrame) -> pl.DataFrame:
    return (
        frame.with_columns(pl.col("equity").cum_max().alias("peak"))
        .with_columns(
            pl.when(pl.col("peak") > 0)
            .then(pl.col("equity") / pl.col("peak") - 1.0)
            .otherwise(0.0)
            .alias("drawdown")
        )
        .select("date", "drawdown")
    )


def monthly_returns(frame: pl.DataFrame) -> pl.DataFrame:
    ret = daily_returns(frame)
    return (
        ret.with_columns(
            pl.col("date").dt.year().alias("year"),
            pl.col("date").dt.month().alias("month"),
        )
        .group_by("year", "month")
        .agg(((1.0 + pl.col("return")).product() - 1.0).alias("return"))
        .sort("year", "month")
    )


def fig_uri(fig) -> str:
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight")
    plt.close(fig)
    payload = base64.b64encode(buf.getvalue().encode("utf-8")).decode("ascii")
    return "data:image/svg+xml;base64," + payload


def plot_equity(
    base: pl.DataFrame,
    gross: pl.DataFrame,
    double: pl.DataFrame,
    nofund: pl.DataFrame,
    cutoff: datetime,
) -> str:
    fig, ax = plt.subplots(figsize=(11, 4.4))
    for frame, label, lw, ls in [
        (base, "Base costs + funding (net)", 2.0, "-"),
        (gross, "Gross execution-cost addback proxy", 1.5, "--"),
        (double, "2x costs + funding (net)", 1.4, "-"),
        (nofund, "Base costs, no funding", 1.4, "-"),
    ]:
        ax.plot(
            frame["date"].to_list(),
            frame["equity"].to_list(),
            label=label,
            linewidth=lw,
            linestyle=ls,
        )
    ax.axhline(INITIAL_CASH, linewidth=1.0, linestyle=":", label="Cash benchmark")
    ax.axvline(cutoff.date(), linewidth=1.0, linestyle="--")
    ax.annotate(
        "First insolvency\n2025-09-08",
        xy=(cutoff.date(), 0),
        xytext=(cutoff.date() - timedelta(days=190), 35_000),
        arrowprops={"arrowstyle": "->"},
        fontsize=9,
    )
    ax.set_title("Portfolio Equity — Economic Path Stops at First Insolvency")
    ax.set_ylabel("Equity (USDT)")
    ax.grid(alpha=0.2)
    ax.legend(loc="best", fontsize=8)
    return fig_uri(fig)


def plot_drawdowns(
    base: pl.DataFrame,
    double: pl.DataFrame,
    nofund: pl.DataFrame,
) -> str:
    fig, ax = plt.subplots(figsize=(11, 3.8))
    for frame, label in [
        (base, "Base + funding"),
        (double, "2x costs + funding"),
        (nofund, "No funding"),
    ]:
        dd = drawdown(frame)
        ax.plot(
            dd["date"].to_list(),
            (dd["drawdown"] * 100).to_list(),
            label=label,
            linewidth=1.4,
        )
    ax.axhline(-100, linewidth=1.0, linestyle=":")
    ax.set_title("Drawdown")
    ax.set_ylabel("Drawdown (%)")
    ax.grid(alpha=0.2)
    ax.legend(loc="lower left", fontsize=8)
    return fig_uri(fig)


def plot_rolling(
    base: pl.DataFrame,
    double: pl.DataFrame,
    nofund: pl.DataFrame,
) -> str:
    fig, ax = plt.subplots(figsize=(11, 3.8))
    for frame, label in [
        (base, "Base + funding"),
        (double, "2x costs + funding"),
        (nofund, "No funding"),
    ]:
        rolling = rolling_sharpe(frame)
        ax.plot(
            rolling["date"].to_list(),
            rolling["rolling_sharpe"].to_list(),
            label=label,
            linewidth=1.3,
        )
    ax.axhline(0, linewidth=0.8)
    ax.set_title("Rolling Sharpe — 63 Calendar Days, Annualized at 365")
    ax.set_ylabel("Sharpe")
    ax.grid(alpha=0.2)
    ax.legend(loc="best", fontsize=8)
    return fig_uri(fig)


def plot_monthly_heatmap(base: pl.DataFrame) -> str:
    monthly = monthly_returns(base)
    years = sorted(monthly["year"].unique().to_list())
    matrix = np.full((len(years), 12), np.nan)
    for row in monthly.iter_rows(named=True):
        matrix[years.index(row["year"]), int(row["month"]) - 1] = float(row["return"]) * 100
    fig, ax = plt.subplots(figsize=(11, 2.8))
    image = ax.imshow(matrix, aspect="auto", vmin=-100, vmax=100, cmap="RdYlGn")
    ax.set_yticks(range(len(years)), labels=[str(y) for y in years])
    ax.set_xticks(
        range(12),
        labels=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"],
    )
    for i in range(len(years)):
        for j in range(12):
            if np.isfinite(matrix[i, j]):
                ax.text(
                    j,
                    i,
                    f"{matrix[i,j]:.1f}%",
                    ha="center",
                    va="center",
                    fontsize=8,
                )
    ax.set_title("Monthly Net Returns — Base Funding-Aware Portfolio")
    fig.colorbar(image, ax=ax, fraction=0.025, pad=0.02, label="%")
    return fig_uri(fig)


def plot_ic_decay(terminal: dict) -> str:
    ic = terminal["ic"]
    annual = {int(x["year"]): float(x["mean_ic"]) for x in ic["annual"]}
    values = [
        float(ic["reference_2022_2023_mean_ic"]),
        annual.get(2024, np.nan),
        annual.get(2025, np.nan),
    ]
    fig, ax = plt.subplots(figsize=(7.2, 3.5))
    x = np.arange(3)
    bars = ax.bar(x, values)
    ax.set_xticks(x, ["2022–23 ref", "2024", "2025"])
    ax.axhline(0.02, linewidth=1, linestyle="--", label="0.02 diagnostic level")
    ax.axhline(0, linewidth=0.8)
    ax.set_title("48h Cross-Sectional Price Rank IC")
    ax.set_ylabel("Mean Spearman IC")
    for bar, value in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width()/2,
            value,
            f"{value:.4f}",
            ha="center",
            va="bottom",
            fontsize=9,
        )
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.2)
    return fig_uri(fig)


def plot_funding_mechanism(terminal: dict) -> str:
    ratios = terminal["decay_ratios"]
    names = [
        "Funding spread",
        "Funding persistence",
        "Realized carry",
        "Pre-insolvency\nnative funding yield",
        "Price Rank IC",
    ]
    values = [
        float(ratios["funding_opportunity_spread_ratio_to_2022_2023"]),
        float(ratios["funding_persistence_ratio_to_2022_2023"]),
        float(ratios["unit_notional_realized_carry_ratio_to_2022_2023"]),
        float(ratios["pre_insolvency_native_funding_yield_ratio_to_2022_2023"]),
        float(ratios["price_rank_ic_ratio_to_2022_2023"]),
    ]
    fig, ax = plt.subplots(figsize=(8.4, 3.8))
    x = np.arange(len(names))
    bars = ax.bar(x, values)
    ax.axhline(1.0, linewidth=1, linestyle="--", label="2022–23 reference")
    ax.axhline(0.5, linewidth=1, linestyle=":", label="50% retention")
    ax.set_xticks(x, names, rotation=15, ha="right")
    ax.set_ylabel("Ratio to 2022–23 reference")
    ax.set_title("What Decayed? Funding Carry vs Price Predictiveness")
    for bar, value in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width()/2,
            value,
            f"{value:.2f}x",
            ha="center",
            va="bottom",
            fontsize=8,
        )
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.2)
    return fig_uri(fig)


def plot_myx(signal_path: Path, prices_path: Path, cutoff: datetime) -> str:
    signal = pl.read_parquet(signal_path).filter(
        (pl.col("symbol") == "MYXUSDT")
        & (pl.col("decision_ts") >= datetime(2025, 7, 1, tzinfo=UTC))
        & (pl.col("decision_ts") <= datetime(2025, 10, 31, tzinfo=UTC))
    )
    prices = pl.read_parquet(prices_path).filter(
        (pl.col("symbol") == "MYXUSDT")
        & (pl.col("timestamp") >= datetime(2025, 7, 1, tzinfo=UTC))
        & (pl.col("timestamp") <= datetime(2025, 10, 31, 23, tzinfo=UTC))
    ).sort("timestamp")
    fig, ax = plt.subplots(figsize=(11, 4.0))
    ax.plot(
        prices["timestamp"].to_list(),
        prices["close"].to_list(),
        linewidth=1.3,
        label="MYXUSDT close",
    )
    if signal.height:
        decision_prices = []
        for ts in signal["decision_ts"].to_list():
            prior = prices.filter(pl.col("timestamp") <= ts).tail(1)
            decision_prices.append(float(prior["close"][0]) if prior.height else np.nan)
        ax.scatter(
            signal["decision_ts"].to_list(),
            decision_prices,
            s=14,
            label="MYX signal decision",
        )
    ax.axvline(cutoff.replace(tzinfo=UTC), linewidth=1.1, linestyle="--", label="Account insolvency")
    ax.axhline(18.65, linewidth=0.8, linestyle=":", label="Validation high ≈ 18.65")
    ax.set_title("MYXUSDT Tail Event")
    ax.set_ylabel("Price (USDT)")
    ax.grid(alpha=0.2)
    ax.legend(fontsize=8)
    return fig_uri(fig)


def fmt_pct(value: float | None, digits: int = 1) -> str:
    if value is None or not math.isfinite(value):
        return "—"
    return f"{value*100:.{digits}f}%"


def fmt_num(value: float | None, digits: int = 2) -> str:
    if value is None or not math.isfinite(value):
        return "—"
    return f"{value:.{digits}f}"


def fmt_usd(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "—"
    sign = "-" if value < 0 else ""
    return f"{sign}{chr(36)}{abs(value):,.0f}"


def metric_row(label: str, values: list[str]) -> str:
    cells = "".join(f"<td>{escape(value)}</td>" for value in values)
    return f"<tr><th>{escape(label)}</th>{cells}</tr>"


def main() -> None:
    terminal = load_json(FINAL / "terminal_decision.json")
    verify = load_json(FINAL / "independent_verification.json")
    checks = verify.get("checks", {})
    if terminal["decision"] != "REJECT" or not checks or not all(checks.values()):
        raise RuntimeError("final validation evidence not verified")

    base_state = FORENSICS / "corrected_native_base_portfolio_state.parquet"
    double_state = FORENSICS / "corrected_native_double_cost_portfolio_state.parquet"
    nofund_state = VALID / "validation_native_no_funding" / "portfolio_state.parquet"
    base_trades = FORENSICS / "corrected_native_base_trades.parquet"

    cutoff, _ = first_nonpositive_state(base_state)
    double_cutoff, _ = first_nonpositive_state(double_state)
    nofund_cutoff, _ = first_nonpositive_state(nofund_state)
    if not (cutoff == double_cutoff == nofund_cutoff):
        raise AssertionError("insolvency timestamp differs across required arms")

    base = terminalize_daily(base_state, cutoff)
    double = terminalize_daily(double_state, cutoff)
    nofund = terminalize_daily(nofund_state, cutoff)
    gross, cost_info = cost_proxy_equity(base_state, base_trades, cutoff)

    base_m = portfolio_metrics(base)
    gross_m = portfolio_metrics(gross)
    double_m = portfolio_metrics(double)
    nofund_m = portfolio_metrics(nofund)

    trades = pl.read_parquet(base_trades)
    realized = trades.filter(
        pl.col("exit_time").is_not_null() & (pl.col("exit_time") <= cutoff)
    )
    gross_trade_pnl = float(realized["gross_pnl"].sum())
    net_trade_pnl = float(realized["pnl"].sum())
    commission_cost = float(realized["fees"].sum())
    slippage_cost = float(realized["total_slippage_cost"].sum())
    execution_cost = commission_cost + slippage_cost
    if not math.isclose(
        gross_trade_pnl - net_trade_pnl,
        commission_cost,
        rel_tol=1e-8,
        abs_tol=1e-6,
    ):
        raise AssertionError("trade-level commission reconciliation failed")

    imgs = {
        "equity": plot_equity(base, gross, double, nofund, cutoff),
        "drawdown": plot_drawdowns(base, double, nofund),
        "rolling": plot_rolling(base, double, nofund),
        "monthly": plot_monthly_heatmap(base),
        "ic": plot_ic_decay(terminal),
        "funding": plot_funding_mechanism(terminal),
        "myx": plot_myx(
            ROOT / "data" / "processed" / SESSION / "signal_panel_preoutcome.parquet",
            ROOT / "data" / "processed" / SESSION / "prices_2025.parquet",
            cutoff,
        ),
    }

    rows = ""
    for label, key, kind in [
        ("Total return", "total_return", "pct"),
        ("Annualized return", "annual_return", "pct"),
        ("Annualized volatility", "annual_volatility", "pct"),
        ("Sharpe", "sharpe_ratio", "num"),
        ("Sortino", "sortino_ratio", "num"),
        ("Max drawdown", "max_drawdown", "pct"),
        ("Calmar", "calmar_ratio", "num"),
        ("Daily win rate", "win_rate", "pct"),
        ("Daily profit factor", "profit_factor", "num"),
        ("CVaR 95%", "cvar_95", "pct"),
    ]:
        values = []
        for metrics in (gross_m, base_m, double_m, nofund_m):
            value = metrics.get(key)
            values.append(fmt_pct(value) if kind == "pct" else fmt_num(value))
        rows += metric_row(label, values)

    ic = terminal["ic"]
    annual_ic = {int(x["year"]): float(x["mean_ic"]) for x in ic["annual"]}
    ratios = terminal["decay_ratios"]
    pre = terminal["pre_insolvency_native_funding"]
    funding_before = terminal["causal_path"]["funding_before_insolvency_usdt"]
    funding_after = terminal["causal_path"]["funding_after_insolvency_usdt"]
    myx_after = terminal["causal_path"]["myx_funding_after_insolvency_usdt"]

    metrics_payload = {
        "session": SESSION,
        "method": {
            "skill": "ml4t tearsheet",
            "native_metrics": "ml4t.diagnostic.api.PortfolioAnalysis",
            "periods_per_year": PERIODS_PER_YEAR,
            "economic_terminalization": (
                "equity set to zero at first nonpositive account equity"
            ),
            "benchmark": "cash / 0% return",
            "gross_definition": (
                "Reporting proxy only: observed net equity plus cumulative recorded "
                "commission and slippage. Not a separate zero-cost backtest."
            ),
        },
        "cutoff": cutoff.isoformat(),
        "metrics": {
            "gross_proxy": gross_m,
            "base_net": base_m,
            "double_cost_net": double_m,
            "no_funding_net": nofund_m,
        },
        "cost_attribution": {
            **cost_info,
            "realized_trade_gross_pnl_after_fill_slippage_before_commission_usdt": gross_trade_pnl,
            "realized_trade_net_pnl_usdt": net_trade_pnl,
            "reconciled_commission_usdt": commission_cost,
            "reported_slippage_cost_usdt": slippage_cost,
            "zero_friction_addback_proxy_usdt": execution_cost,
        },
        "mechanism": {
            "ic_2024": annual_ic[2024],
            "ic_2025": annual_ic[2025],
            "combined_ic": float(ic["mean_ic"]),
            "funding_spread_ratio": float(
                ratios["funding_opportunity_spread_ratio_to_2022_2023"]
            ),
            "funding_persistence_ratio": float(
                ratios["funding_persistence_ratio_to_2022_2023"]
            ),
            "realized_carry_ratio": float(
                ratios["unit_notional_realized_carry_ratio_to_2022_2023"]
            ),
            "pre_insolvency_native_funding_yield": float(
                pre["annualized_funding_yield_on_average_gross"]
            ),
            "pre_insolvency_native_funding_yield_ratio": float(
                ratios["pre_insolvency_native_funding_yield_ratio_to_2022_2023"]
            ),
        },
    }

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ML4T Tearsheet — Plain Cross-Sectional Binance Funding — 2024–2025 Decay Validation</title>
<style>
:root {{
  --bg:#f5f7fa; --card:#ffffff; --ink:#17202a; --muted:#5f6b78;
  --line:#dbe2ea; --good:#116329; --bad:#a61b1b; --warn:#8a5b00; --accent:#244a7c;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif; background:var(--bg); color:var(--ink); }}
.wrap {{ max-width:1180px; margin:0 auto; padding:28px; }}
.header {{ background:linear-gradient(135deg,#14263d,#244a7c); color:white; padding:28px 30px; border-radius:14px; }}
.header h1 {{ margin:0 0 8px; font-size:28px; }}
.header p {{ margin:4px 0; color:#dce7f5; }}
.badges {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:16px; }}
.badge {{ padding:6px 10px; border-radius:999px; font-size:12px; font-weight:700; background:#eef2f7; color:#203040; }}
.badge.bad {{ background:#ffe1e1; color:#8c1717; }}
.badge.good {{ background:#dcf5e3; color:#175c2b; }}
.badge.warn {{ background:#fff0cb; color:#725000; }}
.grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin:16px 0; }}
.kpi {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; }}
.kpi .label {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.05em; }}
.kpi .value {{ font-size:24px; font-weight:750; margin-top:5px; }}
.kpi .sub {{ color:var(--muted); font-size:12px; margin-top:5px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:18px; margin:14px 0; }}
.card h2 {{ margin:0 0 12px; font-size:18px; }}
.card h3 {{ margin:14px 0 8px; font-size:14px; }}
.chart {{ width:100%; display:block; border-radius:8px; }}
.two {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th,td {{ border-bottom:1px solid var(--line); padding:9px 8px; text-align:right; }}
th:first-child,td:first-child {{ text-align:left; }}
thead th {{ background:#f7f9fc; font-weight:700; }}
.callout {{ border-left:4px solid var(--accent); background:#f3f7fc; padding:14px 16px; margin:12px 0; }}
.callout.bad {{ border-color:var(--bad); background:#fff4f4; }}
.callout.good {{ border-color:var(--good); background:#f2fbf4; }}
.small {{ color:var(--muted); font-size:12px; line-height:1.5; }}
.footer {{ color:var(--muted); font-size:12px; padding:10px 2px 30px; }}
@media (max-width:900px) {{ .grid {{ grid-template-columns:1fr 1fr; }} .two {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<div class="wrap">
  <section class="header">
    <h1>ML4T Strategy Tearsheet</h1>
    <p><strong>Plain Cross-Sectional Binance Funding</strong> · Untouched 2024–2025 decay validation</p>
    <p>Dollar-neutral 5-long / 5-short · 48h rebalance · Binance USD-M perpetuals · native ML4T event-driven execution</p>
    <div class="badges">
      <span class="badge bad">REJECT — unchanged portfolio</span>
      <span class="badge good">Funding carry alive</span>
      <span class="badge warn">Price IC decayed in 2025</span>
      <span class="badge bad">Single-name squeeze fatal</span>
      <span class="badge good">2026 holdout sealed</span>
    </div>
  </section>

  <div class="grid">
    <div class="kpi"><div class="label">First insolvency</div><div class="value">08 Sep 2025</div><div class="sub">19:00 UTC · all three core arms cross ≤ 0 equity</div></div>
    <div class="kpi"><div class="label">2025 Price Rank IC</div><div class="value">{annual_ic[2025]:.4f}</div><div class="sub">2024: {annual_ic[2024]:.4f} · 2022–23 ref: 0.0240</div></div>
    <div class="kpi"><div class="label">Funding spread retention</div><div class="value">{float(ratios["funding_opportunity_spread_ratio_to_2022_2023"]):.2f}×</div><div class="sub">Funding opportunity expanded, not compressed</div></div>
    <div class="kpi"><div class="label">Pre-insolvency funding yield</div><div class="value">{float(pre["annualized_funding_yield_on_average_gross"])*100:.1f}%</div><div class="sub">{float(ratios["pre_insolvency_native_funding_yield_ratio_to_2022_2023"])*100:.1f}% of 2022–23 reference</div></div>
  </div>

  <section class="card">
    <h2>Performance summary</h2>
    <div class="callout bad"><strong>Economic convention:</strong> once account equity first reaches zero or below, the tearsheet stops the path and sets terminal equity to zero. Post-bankruptcy simulated positions are excluded from performance statistics.</div>
    <table>
      <thead><tr><th>Metric</th><th>Gross proxy*</th><th>Base net + funding</th><th>2× costs + funding</th><th>Base net, no funding</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    <p class="small">* Gross proxy = observed net equity plus recorded commission and slippage addback. It is an attribution proxy, not a separately rerun zero-cost strategy. ML4T <code>PortfolioAnalysis</code> computes the summary statistics with 365 periods/year.</p>
  </section>

  <section class="card"><h2>Equity curve</h2><img class="chart" src="{imgs["equity"]}" alt="Equity curves"></section>
  <section class="card"><h2>Drawdown</h2><img class="chart" src="{imgs["drawdown"]}" alt="Drawdown curves"></section>
  <section class="card"><h2>Rolling risk-adjusted performance</h2><img class="chart" src="{imgs["rolling"]}" alt="Rolling Sharpe"></section>
  <section class="card"><h2>Monthly return heatmap</h2><img class="chart" src="{imgs["monthly"]}" alt="Monthly return heatmap"></section>

  <section class="two">
    <div class="card"><h2>Price-edge decay</h2><img class="chart" src="{imgs["ic"]}" alt="IC decay"></div>
    <div class="card"><h2>Funding mechanism retention</h2><img class="chart" src="{imgs["funding"]}" alt="Funding mechanism ratios"></div>
  </section>

  <section class="card">
    <h2>Mechanism diagnosis</h2>
    <div class="callout good"><strong>Funding carry did not disappear.</strong> Funding persistence is {float(ratios["funding_persistence_ratio_to_2022_2023"]):.2f}× the 2022–23 reference. Unit-notional realized carry is {float(ratios["unit_notional_realized_carry_ratio_to_2022_2023"]):.2f}×. Funding spread is {float(ratios["funding_opportunity_spread_ratio_to_2022_2023"]):.2f}×.</div>
    <div class="callout"><strong>Price predictiveness did decay.</strong> Mean 48h Rank IC falls from 0.0223 in 2024 to 0.0033 in 2025. The combined 2024–25 IC is {float(ic["mean_ic"]):.4f} with HAC t-stat {float(ic["hac_t_stat"]):.2f}.</div>
    <div class="callout bad"><strong>Portfolio construction is not survivable unchanged.</strong> The equal-notional short book can become dominated by one squeeze before the next 48h rebalance can reverse the signal.</div>
  </section>

  <section class="card">
    <h2>MYXUSDT failure event</h2>
    <img class="chart" src="{imgs["myx"]}" alt="MYXUSDT tail event">
    <div class="two">
      <div>
        <h3>At first insolvency</h3>
        <table>
          <tbody>
            <tr><th>MYX mark</th><td>≈ $11.03</td></tr>
            <tr><th>Residual short</th><td>≈ −3,239 MYX</td></tr>
            <tr><th>MYX notional</th><td>≈ $35.7k</td></tr>
            <tr><th>Account equity</th><td>≈ −$1,986</td></tr>
            <tr><th>Validation high</th><td>≈ $18.65</td></tr>
          </tbody>
        </table>
      </div>
      <div>
        <h3>Funding path</h3>
        <table>
          <tbody>
            <tr><th>Funding before insolvency</th><td>{fmt_usd(funding_before)}</td></tr>
            <tr><th>Funding after insolvency</th><td>{fmt_usd(funding_after)}</td></tr>
            <tr><th>MYX after insolvency</th><td>{fmt_usd(myx_after)}</td></tr>
            <tr><th>Execution cost to insolvency</th><td>{fmt_usd(execution_cost)}</td></tr>
          </tbody>
        </table>
      </div>
    </div>
    <p class="small">The first intended/actual side mismatch occurs after insolvency. Post-insolvency stale-short funding losses are therefore a consequence of bankruptcy, not the cause of the initial failure.</p>
  </section>

  <section class="card">
    <h2>Research decision</h2>
    <p><strong>Formal frozen outcome:</strong> REJECT / STRUCTURAL_DECAY for the unchanged strategy.</p>
    <p><strong>Mechanism-level conclusion:</strong> funding carry remains economically strong; the 48h price-reversion component largely disappears in 2025; uncapped single-name short exposure creates fatal tail risk.</p>
    <p><strong>Next research question:</strong> preserve the funding signal and test a preregistered risk-sizing layer. Do not use 2024–2025 as untouched validation again. Keep 2026 sealed until the new sizing/risk contract is frozen.</p>
  </section>

  <section class="card">
    <h2>Method and evidence</h2>
    <ul class="small">
      <li>ML4T tearsheet guidance applied: cumulative equity, drawdown, rolling Sharpe, monthly heatmap, metrics table, net/gross comparison, and benchmark.</li>
      <li>Summary metrics: <code>ml4t.diagnostic.api.PortfolioAnalysis</code>.</li>
      <li>Benchmark: cash / 0% return, appropriate for the dollar-neutral research null.</li>
      <li>Native interactive ML4T Plotly tearsheet was unavailable because the optional Plotly package is not installed. Visual panels use Matplotlib; ML4T computes the summary metrics.</li>
      <li>Source terminal artifact: <code>run_log/research_sessions/{SESSION}/validation_final/terminal_decision.json</code>.</li>
      <li>Independent verification: <code>run_log/research_sessions/{SESSION}/validation_final/independent_verification.json</code>.</li>
      <li>2026 observations remain sealed.</li>
    </ul>
  </section>

  <div class="footer">Generated from frozen and independently verified research artifacts. This tearsheet reports research evidence; it does not approve live trading.</div>
</div>
</body>
</html>
"""

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "tearsheet_chat.html").write_text(html, encoding="utf-8")
    (OUT / "tearsheet_chat_metrics.json").write_text(
        json.dumps(metrics_payload, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "html": str((OUT / "tearsheet_chat.html").relative_to(ROOT)),
                "metrics": str((OUT / "tearsheet_chat_metrics.json").relative_to(ROOT)),
                "decision": terminal["decision"],
                "cutoff": cutoff.isoformat(),
                "base_total_return": base_m["total_return"],
                "base_max_drawdown": base_m["max_drawdown"],
                "gross_proxy_total_return": gross_m["total_return"],
                "execution_cost_to_cutoff": execution_cost,
                "ic_2025": annual_ic[2025],
                "funding_spread_ratio": ratios[
                    "funding_opportunity_spread_ratio_to_2022_2023"
                ],
                "verified": all(checks.values()),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
