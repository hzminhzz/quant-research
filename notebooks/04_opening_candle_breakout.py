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
# ⚡ Multi-Timeframe Opening Candle Breakout Lab
*High-Resolution Breakout Execution: **1H Opening Range with 5m Entry** & **15m Opening Range with 1m Entry***

---
### 🎯 The Multi-Timeframe Execution Thesis
1. **The Delayed Entry Problem**: Waiting for a full 15m or 1h candle to close *after* breaking the opening level buys near the top of the thrust, causing severe slippage and unfavorable risk/reward ($R:R$).
2. **Multi-Timeframe Micro-Execution**:
   - **Mode A (1H OR $\rightarrow$ 5m Close Entry)**: The first 1-Hour candle establishes the anchor levels ($High_{1H}, Low_{1H}$). Subsequent **5-minute candles** are evaluated; the instant a 5m bar closes outside the 1H range, we enter immediately!
   - **Mode B (15m OR $\rightarrow$ 1m Close Entry)**: The first 15-Minute candle establishes the anchor levels ($High_{15m}, Low_{15m}$). Subsequent **1-minute candles** trigger the entry on close!
3. **Institutional Day-Trading Guardrails**:
   - **Stop Loss (SL)**: Opposite extreme of the opening candle ($Low_{OR}$) or midpoint.
   - **Take Profit (TP)**: **Breakeven Step + Session Runner** (moves SL to breakeven once price reaches $+1.0\times$ Range, then rides unconstrained till EOD).
   - **Mandatory EOD Time Exit**: 100% flat at session close (zero overnight gap risk).
"""
    )
    return (_header,)


@app.cell
def config_ui(mo):
    asset_select = mo.ui.dropdown(
        options=[
            "Germany 40 (DE30/EUR)",
            "Nikkei 225 (JP225/USD)",
        ],
        value="Germany 40 (DE30/EUR)",
        label="Target Index",
    )

    exec_mode_select = mo.ui.dropdown(
        options=[
            "1-Hour Opening Candle → 5-Minute Breakout Entry",
            "15-Minute Opening Candle → 1-Minute Breakout Entry",
            "15-Minute Opening Candle → 15-Minute Breakout Entry (Baseline)",
        ],
        value="1-Hour Opening Candle → 5-Minute Breakout Entry",
        label="Multi-Timeframe Execution Architecture",
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

    trend_filter_toggle = mo.ui.checkbox(
        value=True,
        label="Condition on 200 EMA Macro Trend Filter",
    )

    min_range_slider = mo.ui.slider(
        start=0.0,
        stop=0.50,
        step=0.05,
        value=0.15,
        label="Min OR Range (% of price)",
    )

    comm_slider = mo.ui.slider(
        start=0.0, stop=5.0, step=0.5, value=2.0, label="Commission (bps/leg)"
    )
    slip_slider = mo.ui.slider(
        start=0.0, stop=3.0, step=0.5, value=1.0, label="Slippage (bps/leg)"
    )

    controls_panel = mo.vstack([
        mo.md("### ⚙️ Multi-Timeframe Execution & Risk Configuration"),
        mo.hstack([asset_select, exec_mode_select], justify="start", gap=2),
        mo.hstack([tp_mode_select, sl_mode_select, side_select], justify="start", gap=2),
        mo.hstack([trend_filter_toggle, min_range_slider], justify="start", gap=2),
        mo.hstack([comm_slider, slip_slider], justify="start", gap=2),
    ])

    return (
        asset_select,
        comm_slider,
        controls_panel,
        exec_mode_select,
        min_range_slider,
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
    deflated_sharpe_ratio_from_statistics,
    diag_metrics,
    exec_mode_select,
    min_range_slider,
    np,
    pl,
    side_select,
    sl_mode_select,
    slip_slider,
    tp_mode_select,
    trend_filter_toggle,
):
    def _simulate_orb():
        _sym = "DE30_EUR" if "DE30" in asset_select.value else "JP225_USD"
        _open_hour = 7 if "DE30" in asset_select.value else 0

        # Multi-timeframe configuration
        if "5-Minute" in exec_mode_select.value:
            _file_p = Path(f"data/processed/{_sym}_5m_2023_2026.parquet")
            _or_bars = 12  # 12 bars of 5m = 60 mins (1H Opening Candle)
            _entry_cutoff_bars = 12  # allow entry within 1 hour after OR
            _max_eval_bars = 72  # 6 hours
            _tf_label = "5m"
        elif "1-Minute" in exec_mode_select.value:
            _file_p = Path(f"data/processed/{_sym}_1m_2024_2026.parquet")
            _or_bars = 15  # 15 bars of 1m = 15 mins Opening Candle
            _entry_cutoff_bars = 30  # allow entry within 30 mins after OR
            _max_eval_bars = 360  # 6 hours
            _tf_label = "1m"
        else:
            _file_p = Path(f"data/processed/{_sym}_15m_2019_2026.parquet")
            _or_bars = 1  # 1 bar of 15m = 15 mins Opening Candle
            _entry_cutoff_bars = 4  # allow entry within 1 hour after OR
            _max_eval_bars = 24  # 6 hours
            _tf_label = "15m"

        if not _file_p.exists():
            return pl.DataFrame({"Date": [], "Equity": []}), {
                "sharpe": 0.0,
                "ci": [0.0, 0.0],
                "dsr_prob": 0.0,
                "dsr_haircut": 0.0,
                "sortino": 0.0,
                "total_return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "win_rate_pct": 0.0,
                "num_trades": 0,
                "avg_trade_bps": 0.0,
                "trades": [],
                "tf": _tf_label,
            }

        _df = pl.read_parquet(_file_p).sort("timestamp")
        _sl_mode = "mid" if "Midpoint" in sl_mode_select.value else "full"
        _allow_short = side_select.value == "Long and Short"
        _use_trend = trend_filter_toggle.value
        _min_rng_pct = float(min_range_slider.value)
        _friction = 2.0 * (float(comm_slider.value) + float(slip_slider.value)) / 10_000.0

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
            _max_bars = min(len(_rest_df), _max_eval_bars)

            for _i in range(_max_bars):
                _bar = _rest_df[_i]
                _c = _bar["close"][0]
                _h = _bar["high"][0]
                _l = _bar["low"][0]

                if not _in_trade:
                    if _i < _entry_cutoff_bars:
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

        _dates_list = sorted(_daily_pnl.keys())
        _rets_arr = np.array([_daily_pnl[d] for d in _dates_list])
        _cum_equity = 100_000.0 * np.cumprod(1.0 + _rets_arr)

        _peaks = np.maximum.accumulate(_cum_equity)
        _dd_arr = (_cum_equity - _peaks) / _peaks
        _max_dd_pct = float(np.min(_dd_arr)) * -100.0 if len(_dd_arr) > 0 else 0.0

        _total_trades = len(_trades)
        _win_trades = sum(1 for t in _trades if t["NetRet%"] > 0)
        _win_rate = (_win_trades / _total_trades * 100.0) if _total_trades > 0 else 0.0
        _tot_ret_pct = float((_cum_equity[-1] / 100_000.0 - 1.0) * 100.0) if len(_cum_equity) > 0 else 0.0

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

        _chart_df = pl.DataFrame({
            "Date": [str(d) for d in _dates_list],
            "Equity": _cum_equity,
        })

        _summary = {
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
            "tf": _tf_label,
        }
        return _chart_df, _summary

    daily_chart_df, sim_summary = _simulate_orb()
    return daily_chart_df, sim_summary


@app.cell
def kpi_cards(asset_select, exec_mode_select, mo, sim_summary):
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
        mo.md(f"### 📊 Micro-Execution Performance: **{asset_select.value}**"),
        mo.md(f"*{exec_mode_select.value} (Bars evaluated on {sim_summary.get('tf', '15m')} resolution)*"),
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
def equity_chart(alt, asset_select, daily_chart_df, exec_mode_select, mo):
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
            title=f"Intraday ORB Equity Curve: {asset_select.value} ({exec_mode_select.value})",
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
        mo.md("### 🔍 Exit Reason Breakdown & High-Resolution Trade Audit"),
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
### 🛡️ Multi-Timeframe Execution Advantages
1. **Entering at the Breakout Close**: By evaluating 1m candles (for 15m OR) or 5m candles (for 1H OR), entries occur within seconds/minutes of the level breach rather than 15–30 minutes later after momentum has already dissipated.
2. **Shorter Adverse Excursion**: Because the entry is closer to $High_{OR}$ / $Low_{OR}$, the distance to the stop-loss is substantially smaller in absolute price points, allowing higher risk-adjusted capital efficiency.
3. **Breakeven Ratchet Speed**: Because the stop moves to breakeven when price expands by $+1.0\times Range$, micro-candle entries register the $+1.0\times$ expansion much earlier in the session, dramatically reducing intra-session drawdown.
"""
    )
    return (_audit,)


if __name__ == "__main__":
    app.run()
