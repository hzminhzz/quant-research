# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "altair>=5.0.0",
#     "marimo>=0.24.0",
#     "ml4t-backtest",
#     "ml4t-diagnostic",
#     "ml4t-engineer",
#     "numpy>=1.26.0",
#     "polars>=1.20.0",
# ]
# ///

import marimo

__generated_with = "0.24.0"
app = marimo.App(width="medium", auto_download=["html"])


@app.cell(hide_code=True)
def setup():
    from datetime import datetime
    import json
    from pathlib import Path

    import altair as alt
    import marimo as mo
    from ml4t.diagnostic.evaluation.stats import (
        deflated_sharpe_ratio_from_statistics,
    )
    import ml4t.diagnostic.metrics as diag_metrics
    import numpy as np
    import polars as pl

    alt.data_transformers.enable("default")

    return (
        Path,
        alt,
        datetime,
        deflated_sharpe_ratio_from_statistics,
        diag_metrics,
        json,
        mo,
        np,
        pl,
    )


@app.cell
def header_markdown(mo):
    _header = mo.md(
        r"""
# ⚡ Opening Candle Breakout (Day-Trading ORB) Research Lab
*Intraday Systematic Alpha Engine with Triple Barrier Exits & Institutional Cost Modeling*

---
### 🎯 The Strategy Thesis
1. **Price Discovery Anchor**: The market opening auction concentrates the highest volume of the day. The **Opening Range (OR)** candle (15m, 30m, or 1h) establishes the initial supply/demand balance:
   $$\text{Range}_{OR} = High_{OR} - Low_{OR}$$
2. **Breakout Trigger**: When subsequent price closes outside the opening candle range, aggressive institutional order flow is attempting to drive directional expansion.
3. **Pure Day-Trading Guarantee (Triple Barrier Exit)**:
   - **Stop Loss (SL)**: Set at the opposite extreme of the opening candle ($Low_{OR}$ for Long) or at the midpoint ($\frac{High_{OR} + Low_{OR}}{2}$).
   - **Take Profit (TP)**: Choose between **Breakeven Step + Session Runner** (ratchet stop to breakeven at $+1.0\times$ Range), fixed range multiples ($1.5\times, 2.0\times$), or unconstrained session close hold.
   - **Time Barrier (Mandatory EOD)**: All open trades close unconditionally at session close. **Zero overnight gap risk**.
"""
    )
    return (_header,)


@app.cell
def config_ui(mo):
    asset_select = mo.ui.dropdown(
        options=[
            "Germany 40 (DE30/EUR)",
            "Nikkei 225 (JP225/USD)",
            "S&P 500 (SPX500/USD)",
        ],
        value="Germany 40 (DE30/EUR)",
        label="Target Index",
    )

    or_duration_select = mo.ui.dropdown(
        options=[
            "15 Minutes (1 bar)",
            "30 Minutes (2 bars)",
            "60 Minutes (4 bars)",
        ],
        value="30 Minutes (2 bars)",
        label="Opening Candle Duration",
    )

    tp_mode_select = mo.ui.dropdown(
        options=[
            "Breakeven Step + Session Runner",
            "Fixed 1.5x Range Target",
            "Fixed 2.0x Range Target",
            "Pure Session Close (No TP Ceiling)",
        ],
        value="Breakeven Step + Session Runner",
        label="Take-Profit (TP) Architecture",
    )

    sl_mode_select = mo.ui.dropdown(
        options=[
            "Full Opening Range Opposite",
            "Midpoint of Opening Range",
        ],
        value="Full Opening Range Opposite",
        label="Stop-Loss (SL) Anchor",
    )

    side_select = mo.ui.dropdown(
        options=["Long Only", "Long and Short"],
        value="Long Only",
        label="Trading Direction",
    )

    period_select = mo.ui.dropdown(
        options=[
            "Out-of-Sample (2023–2026)",
            "In-Sample (2019–2022)",
            "Full History (2019–2026)",
        ],
        value="Out-of-Sample (2023–2026)",
        label="Evaluation Window",
    )

    trend_filter_toggle = mo.ui.checkbox(
        value=True,
        label="Condition on 15m EMA-200 Trend Filter",
    )

    min_range_slider = mo.ui.slider(
        start=0.0,
        stop=0.60,
        step=0.05,
        value=0.20,
        label="Min OR Range (% of price)",
    )

    comm_slider = mo.ui.slider(
        start=0.0, stop=5.0, step=0.5, value=2.0, label="Commission (bps/leg)"
    )
    slip_slider = mo.ui.slider(
        start=0.0, stop=3.0, step=0.5, value=1.0, label="Slippage (bps/leg)"
    )

    controls_panel = mo.vstack([
        mo.md("### ⚙️ Day-Trading Strategy Configuration & Friction Model"),
        mo.hstack([asset_select, or_duration_select, period_select], justify="start", gap=2),
        mo.hstack([tp_mode_select, sl_mode_select, side_select], justify="start", gap=2),
        mo.hstack([trend_filter_toggle, min_range_slider], justify="start", gap=2),
        mo.hstack([comm_slider, slip_slider], justify="start", gap=2),
    ])

    return (
        asset_select,
        comm_slider,
        controls_panel,
        min_range_slider,
        or_duration_select,
        period_select,
        side_select,
        sl_mode_select,
        slip_slider,
        tp_mode_select,
        trend_filter_toggle,
    )


@app.cell
def display_controls(controls_panel):
    controls_panel
    return


@app.cell
def run_orb_backtest(
    Path,
    asset_select,
    comm_slider,
    datetime,
    deflated_sharpe_ratio_from_statistics,
    diag_metrics,
    min_range_slider,
    np,
    or_duration_select,
    period_select,
    pl,
    side_select,
    sl_mode_select,
    slip_slider,
    tp_mode_select,
    trend_filter_toggle,
):
    # Determine symbol and session open hour
    if "DE30" in asset_select.value:
        _sym = "DE30_EUR"
        _open_hour = 7
    elif "JP225" in asset_select.value:
        _sym = "JP225_USD"
        _open_hour = 0
    else:
        _sym = "SPX500_USD"
        _open_hour = 14

    _primary_p = Path(f"data/processed/{_sym}_15m_2019_2026.parquet")
    _fallback_p = Path(f"/tmp/lse_15m_cache/{_sym}_15m_2019_2026.parquet")
    _file_p = _primary_p if _primary_p.exists() else _fallback_p

    _df_raw = pl.read_parquet(_file_p).sort("timestamp")

    # Date filtering
    if period_select.value == "Out-of-Sample (2023–2026)":
        _df = _df_raw.filter(
            (pl.col("timestamp") >= datetime(2023, 1, 1))
            & (pl.col("timestamp") < datetime(2026, 1, 1))
        )
    elif period_select.value == "In-Sample (2019–2022)":
        _df = _df_raw.filter(
            (pl.col("timestamp") >= datetime(2019, 1, 1))
            & (pl.col("timestamp") < datetime(2023, 1, 1))
        )
    else:
        _df = _df_raw

    # OR parameters
    _or_bars = 1 if "15" in or_duration_select.value else (2 if "30" in or_duration_select.value else 4)
    _sl_mode = "mid" if "Midpoint" in sl_mode_select.value else "full"
    _allow_short = side_select.value == "Long and Short"
    _use_trend = trend_filter_toggle.value
    _min_rng_pct = float(min_range_slider.value)
    _friction = 2.0 * (float(comm_slider.value) + float(slip_slider.value)) / 10_000.0

    # Indicator precomputation
    _df = _df.with_columns([
        pl.col("timestamp").dt.date().alias("date"),
        pl.col("timestamp").dt.hour().alias("hour"),
        pl.col("close").ewm_mean(span=200).alias("ema_200"),
    ])

    _dates = _df["date"].unique().sort().to_list()
    _daily_pnl = {d: 0.0 for d in _dates}
    _trades = []

    for _d in _dates:
        _day_df = _df.filter(pl.col("date") == _d)
        _session_df = _day_df.filter(pl.col("hour") >= _open_hour)
        if len(_session_df) < _or_bars + 4:
            continue

        _or_df = _session_df.slice(0, _or_bars)
        _or_high = _or_df["high"].max()
        _or_low = _or_df["low"].min()
        _or_close = _or_df["close"].last()
        _or_range = _or_high - _or_low
        _ema200 = _or_df["ema_200"].last()

        if _or_range is None or _or_close is None or _or_range <= 0:
            continue
        if (_or_range / _or_close) * 100.0 < _min_rng_pct:
            continue

        _rest_df = _session_df.slice(_or_bars)
        _in_trade = False
        _side = 0
        _entry_p = 0.0
        _entry_bar_idx = 0
        _sl_p = 0.0
        _tp_p = 0.0
        _max_bars = min(len(_rest_df), 28)

        for _i in range(_max_bars):
            _bar = _rest_df[_i]
            _c = _bar["close"][0]
            _h = _bar["high"][0]
            _l = _bar["low"][0]
            _ts = _bar["timestamp"][0]

            if not _in_trade:
                # Only enter within first 4 bars (1 hour) after OR completes
                if _i < 4:
                    _long_sig = _c > _or_high
                    if _use_trend and _ema200 is not None:
                        _long_sig = _long_sig and (_c > _ema200)

                    _short_sig = (_c < _or_low) and _allow_short
                    if _use_trend and _ema200 is not None:
                        _short_sig = _short_sig and (_c < _ema200)

                    if _long_sig:
                        _in_trade = True
                        _side = 1
                        _entry_p = _c
                        _entry_bar_idx = _i
                        _sl_p = _or_low if _sl_mode == "full" else (_or_high + _or_low) / 2.0
                        if "1.5x" in tp_mode_select.value:
                            _tp_p = _entry_p + 1.5 * _or_range
                        elif "2.0x" in tp_mode_select.value:
                            _tp_p = _entry_p + 2.0 * _or_range
                        else:
                            _tp_p = 999999.0
                    elif _short_sig:
                        _in_trade = True
                        _side = -1
                        _entry_p = _c
                        _entry_bar_idx = _i
                        _sl_p = _or_high if _sl_mode == "full" else (_or_high + _or_low) / 2.0
                        if "1.5x" in tp_mode_select.value:
                            _tp_p = _entry_p - 1.5 * _or_range
                        elif "2.0x" in tp_mode_select.value:
                            _tp_p = _entry_p - 2.0 * _or_range
                        else:
                            _tp_p = -999999.0
            else:
                # Active position management
                if _side == 1:
                    if "Breakeven" in tp_mode_select.value and _h >= _entry_p + 1.0 * _or_range:
                        _sl_p = max(_sl_p, _entry_p)

                    _hit_tp = _h >= _tp_p
                    _hit_sl = _l <= _sl_p

                    if _hit_tp and _hit_sl:
                        _ret = (_sl_p - _entry_p) / _entry_p - _friction
                        _trades.append({"Date": str(_d), "Side": "BUY", "Entry": _entry_p, "Exit": _sl_p, "NetRet%": _ret * 100.0, "HoldBars": _i - _entry_bar_idx, "ExitReason": "SL (Conflict)"})
                        _daily_pnl[_d] += _ret
                        break
                    elif _hit_tp:
                        _ret = (_tp_p - _entry_p) / _entry_p - _friction
                        _trades.append({"Date": str(_d), "Side": "BUY", "Entry": _entry_p, "Exit": _tp_p, "NetRet%": _ret * 100.0, "HoldBars": _i - _entry_bar_idx, "ExitReason": "Take Profit"})
                        _daily_pnl[_d] += _ret
                        break
                    elif _hit_sl:
                        _ret = (_sl_p - _entry_p) / _entry_p - _friction
                        _trades.append({"Date": str(_d), "Side": "BUY", "Entry": _entry_p, "Exit": _sl_p, "NetRet%": _ret * 100.0, "HoldBars": _i - _entry_bar_idx, "ExitReason": "Stop Loss"})
                        _daily_pnl[_d] += _ret
                        break
                    elif _i == _max_bars - 1:
                        _ret = (_c - _entry_p) / _entry_p - _friction
                        _trades.append({"Date": str(_d), "Side": "BUY", "Entry": _entry_p, "Exit": _c, "NetRet%": _ret * 100.0, "HoldBars": _i - _entry_bar_idx, "ExitReason": "Session Close"})
                        _daily_pnl[_d] += _ret
                        break
                elif _side == -1:
                    if "Breakeven" in tp_mode_select.value and _l <= _entry_p - 1.0 * _or_range:
                        _sl_p = min(_sl_p, _entry_p)

                    _hit_tp = _l <= _tp_p
                    _hit_sl = _h >= _sl_p

                    if _hit_tp and _hit_sl:
                        _ret = (_entry_p - _sl_p) / _entry_p - _friction
                        _trades.append({"Date": str(_d), "Side": "SELL", "Entry": _entry_p, "Exit": _sl_p, "NetRet%": _ret * 100.0, "HoldBars": _i - _entry_bar_idx, "ExitReason": "SL (Conflict)"})
                        _daily_pnl[_d] += _ret
                        break
                    elif _hit_tp:
                        _ret = (_entry_p - _tp_p) / _entry_p - _friction
                        _trades.append({"Date": str(_d), "Side": "SELL", "Entry": _entry_p, "Exit": _tp_p, "NetRet%": _ret * 100.0, "HoldBars": _i - _entry_bar_idx, "ExitReason": "Take Profit"})
                        _daily_pnl[_d] += _ret
                        break
                    elif _hit_sl:
                        _ret = (_entry_p - _sl_p) / _entry_p - _friction
                        _trades.append({"Date": str(_d), "Side": "SELL", "Entry": _entry_p, "Exit": _sl_p, "NetRet%": _ret * 100.0, "HoldBars": _i - _entry_bar_idx, "ExitReason": "Stop Loss"})
                        _daily_pnl[_d] += _ret
                        break
                    elif _i == _max_bars - 1:
                        _ret = (_entry_p - _c) / _entry_p - _friction
                        _trades.append({"Date": str(_d), "Side": "SELL", "Entry": _entry_p, "Exit": _c, "NetRet%": _ret * 100.0, "HoldBars": _i - _entry_bar_idx, "ExitReason": "Session Close"})
                        _daily_pnl[_d] += _ret
                        break

    # Calculate equity curve
    _dates_list = sorted(_daily_pnl.keys())
    _rets_arr = np.array([_daily_pnl[d] for d in _dates_list])
    _cum_equity = 100_000.0 * np.cumprod(1.0 + _rets_arr)

    # Max Drawdown
    _peaks = np.maximum.accumulate(_cum_equity)
    _dd_arr = (_cum_equity - _peaks) / _peaks
    _max_dd_pct = float(np.min(_dd_arr)) * -100.0

    _total_trades = len(_trades)
    _win_trades = sum(1 for t in _trades if t["NetRet%"] > 0)
    _win_rate = (_win_trades / _total_trades * 100.0) if _total_trades > 0 else 0.0
    _tot_ret_pct = float((_cum_equity[-1] / 100_000.0 - 1.0) * 100.0)

    # Sharpe & CI
    _n_samples = len(_rets_arr)
    if _n_samples > 10 and np.std(_rets_arr) > 1e-8:
        _sr_ci = diag_metrics.sharpe_ratio_with_ci(_rets_arr, periods_per_year=252, random_state=42)
        _sortino = diag_metrics.sortino_ratio(_rets_arr, periods_per_year=252)
        _dsr = deflated_sharpe_ratio_from_statistics(
            observed_sharpe=float(_sr_ci["sharpe"]),
            n_samples=_n_samples,
            n_trials=50,
            variance_trials=0.20,
        )
        _sharpe = float(_sr_ci["sharpe"])
        _ci_lo = float(_sr_ci["lower_ci"])
        _ci_hi = float(_sr_ci["upper_ci"])
        _sortino_val = float(_sortino)
        _dsr_prob = float(_dsr.probability) * 100.0
        _dsr_haircut = float(_dsr.deflated_sharpe)
    else:
        _sharpe, _ci_lo, _ci_hi, _sortino_val, _dsr_prob, _dsr_haircut = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0

    _avg_trade_bps = (np.mean([t["NetRet%"] for t in _trades]) * 100.0) if _trades else 0.0

    daily_chart_df = pl.DataFrame({
        "Date": [str(d) for d in _dates_list],
        "Equity": _cum_equity,
    })

    sim_summary = {
        "sharpe": _sharpe,
        "ci": [_ci_lo, _ci_hi],
        "dsr_prob": _dsr_prob,
        "dsr_haircut": _dsr_haircut,
        "sortino": _sortino_val,
        "total_return_pct": _tot_ret_pct,
        "max_drawdown_pct": _max_dd_pct,
        "win_rate_pct": _win_rate,
        "num_trades": _total_trades,
        "avg_trade_bps": _avg_trade_bps,
        "trades": _trades,
    }

    return daily_chart_df, sim_summary


@app.cell
def kpi_cards(asset_select, mo, sim_summary):
    _sr = sim_summary["sharpe"]
    _ci = sim_summary["ci"]
    _dsr_haircut = sim_summary["dsr_haircut"]
    _dsr_prob = sim_summary["dsr_prob"]
    _sortino = sim_summary["sortino"]
    _ret = sim_summary["total_return_pct"]
    _dd = sim_summary["max_drawdown_pct"]
    _wr = sim_summary["win_rate_pct"]
    _n = sim_summary["num_trades"]
    _avg_bps = sim_summary["avg_trade_bps"]

    kpi_view = mo.vstack([
        mo.md(f"### 📊 Strategy Performance Overview: **{asset_select.value}**"),
        mo.hstack([
            mo.stat(
                label="Annualized Sharpe (95% CI)",
                value=f"{_sr:.2f}",
                caption=f"[{_ci[0]:.2f}, {_ci[1]:.2f}]",
            ),
            mo.stat(
                label="DSR Haircut Sharpe",
                value=f"{_dsr_haircut:.2f}",
                caption=f"DSR Conf: {_dsr_prob:.1f}%",
            ),
            mo.stat(
                label="Sortino Ratio",
                value=f"{_sortino:.2f}",
                caption="Downside penalized",
            ),
            mo.stat(
                label="Cumulative Net Return",
                value=f"{_ret:+.2f}%",
                caption="Net of 6 bps friction",
            ),
        ]),
        mo.hstack([
            mo.stat(
                label="Max Drawdown",
                value=f"{_dd:.2f}%",
                caption="Peak-to-trough",
            ),
            mo.stat(
                label="Win Rate",
                value=f"{_wr:.1f}%",
                caption=f"{sum(1 for t in sim_summary['trades'] if t['NetRet%'] > 0)} / {_n} wins",
            ),
            mo.stat(
                label="Total Executions",
                value=f"{_n}",
                caption="Zero overnight holds",
            ),
            mo.stat(
                label="Avg Net Trade",
                value=f"{_avg_bps:+.1f} bps",
                caption="Post-commission edge",
            ),
        ]),
    ])
    return (kpi_view,)


@app.cell
def display_kpis(kpi_view):
    kpi_view
    return


@app.cell
def equity_chart(alt, asset_select, daily_chart_df, mo):
    _df_plot = daily_chart_df.to_pandas()

    _chart = (
        alt.Chart(_df_plot)
        .mark_line(color="#e67e22", strokeWidth=2)
        .encode(
            x=alt.X("Date:T", title="Trading Day"),
            y=alt.Y("Equity:Q", title="Portfolio Equity ($)", scale=alt.Scale(zero=False)),
            tooltip=[
                alt.Tooltip("Date:T", title="Date"),
                alt.Tooltip("Equity:Q", format="$,.2f", title="Equity"),
            ],
        )
        .properties(
            width="container",
            height=320,
            title=f"Intraday ORB Daily Equity Curve: {asset_select.value}",
        )
    )

    chart_view = mo.vstack([
        mo.md("### 📈 Cumulative Portfolio Equity Curve (EOD Marks)"),
        _chart,
    ])
    return (chart_view,)


@app.cell
def display_chart(chart_view):
    chart_view
    return


@app.cell
def trades_breakdown(mo, sim_summary):
    _trades = sim_summary["trades"]
    _tp_hits = sum(1 for t in _trades if t["ExitReason"] == "Take Profit")
    _sl_hits = sum(1 for t in _trades if "SL" in t["ExitReason"])
    _eod_hits = sum(1 for t in _trades if t["ExitReason"] == "Session Close")

    _table = mo.ui.table(_trades[-25:] if len(_trades) > 25 else _trades)

    trades_view = mo.vstack([
        mo.md("---"),
        mo.md("### 🔍 Exit Reason Breakdown & Recent Trade Audit"),
        mo.hstack([
            mo.stat(label="Take-Profit Exits", value=f"{_tp_hits}"),
            mo.stat(label="Stop-Loss Exits", value=f"{_sl_hits}"),
            mo.stat(label="Session Close Exits (EOD)", value=f"{_eod_hits}"),
        ]),
        mo.md("*Recent Trades Ledger (Last 25 executions)*"),
        _table,
    ])
    return (trades_view,)


@app.cell
def display_trades(trades_view):
    trades_view
    return


@app.cell
def audit_notes(mo):
    _audit = mo.md(
        r"""
---
### 🛡️ ML4T Institutional Day-Trading Guardrails
1. **The Friction Hurdle**: With 2 bps commission + 1 bps slippage per execution leg (**6 bps roundtrip**), an intraday strategy making 100 trades bleeds **6.0% of total capital** to transaction churn alone. Any viable ORB setup must achieve an average gross win $> +40\text{ bps}$.
2. **The Liquidity Sweep Hazard**: Breakouts of the first 15m candle frequently trigger retail stop runs that promptly mean-revert. Conditioning entries on **Opening Range Contraction** ($\text{Range} \ge 0.20\%$) and **Macro Trend Alignment** ($Close > EMA_{200}$) drastically cuts false-breakout churn.
3. **The Power of the Breakeven Step**: Ratcheting the stop to breakeven once price reaches $+1.0\times$ Range protects accumulated open profit while preserving upside convexity for full session trend runners.
"""
    )
    return (_audit,)


if __name__ == "__main__":
    app.run()
