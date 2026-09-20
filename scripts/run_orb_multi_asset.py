"""Multi-Asset Two-Sided (Long + Short) Opening Candle Breakout Engine.

Universe:
1. Germany 40 (DE30/EUR): 07:00 & 13:00 UTC
2. Nikkei 225 (JP225/USD): 00:00 UTC
3. USD/JPY (USD/JPY): Japan Session (00:00 UTC) & US Session (13:00 UTC)
4. BTC/USD (BTC/USD): US Session (13:00 UTC)

Features:
- Two-Sided Breakouts: Long (close > 1H High) + Short (close < 1H Low)
- 1.2x 1-Hour ATR Volatility Filter (prevents chop day triggers)
- Trend filter: EMA 200
- Macro filter: SPX 15m VWAP (Long requires SPX > VWAP; Short requires SPX < VWAP)
- Fixed 1% Static Risk per trade (-1.00R stop-loss, +1.8R to +2.0R win)
- Period: 2022-01-01 to 2026-07-31
"""

import json
from pathlib import Path
from typing import Any, Dict, List
import numpy as np
import polars as pl
import talib
from ml4t.diagnostic.evaluation.stats import deflated_sharpe_ratio_from_statistics


def prepare_spx_vwap() -> pl.DataFrame:
    df_spx = pl.read_parquet("data/processed/SPX500_USD_15m_2017_2026.parquet").sort("timestamp")
    df_spx = df_spx.with_columns([
        pl.col("timestamp").dt.date().alias("date"),
        ((pl.col("high") + pl.col("low") + pl.col("close")) / 3.0).alias("tp"),
        pl.when(pl.col("volume") > 0).then(pl.col("volume")).otherwise(1.0).alias("eff_vol"),
    ]).with_columns([
        (pl.col("tp") * pl.col("eff_vol")).alias("pv")
    ]).with_columns([
        (pl.col("pv").cum_sum().over("date") / pl.col("eff_vol").cum_sum().over("date")).alias("spx_vwap")
    ])
    return df_spx.select(["timestamp", pl.col("close").alias("spx_close"), "spx_vwap"])


def run_multi_asset_backtest(
    df: pl.DataFrame,
    asset_name: str,
    session_hours: List[int],
    session_label: str,
    allow_long: bool = True,
    allow_short: bool = True,
    tp_multiple: float = 2.0,
    max_hold_bars: int = 36,
    slippage_bps: float = 2.0,
    commission_bps: float = 0.0,
    risk_pct: float = 1.0,
    initial_capital: float = 100_000.0,
    start_date: str = "2022-01-01",
    end_date: str = "2026-07-31",
) -> Dict[str, Any]:
    friction = 2.0 * (commission_bps + slippage_bps) / 10_000.0  # 4.0 bps RT default
    risk_fraction = risk_pct / 100.0

    # Filter date range
    filtered_df = df.filter(
        (pl.col("timestamp") >= pl.lit(start_date).str.to_datetime())
        & (pl.col("timestamp") <= pl.lit(end_date).str.to_datetime())
    )

    dates = filtered_df["date"].unique().sort().to_list()
    daily_pnl = {d: 0.0 for d in dates}
    all_trades = []

    for d in dates:
        day_df = filtered_df.filter(pl.col("date") == d)

        for s_idx, open_h in enumerate(session_hours):
            session_df = day_df.filter((pl.col("hour") >= open_h) & (pl.col("hour") < open_h + 6))
            if len(session_df) < 12 + 4:
                continue

            or_df = session_df.slice(0, 12)
            or_h = or_df["high"].max()
            or_l = or_df["low"].min()
            or_rng = or_h - or_l
            atr20 = or_df["atr20_bar"].first()
            ema200 = or_df["ema_200"].last()

            if not or_rng or or_rng <= 0:
                continue
            if atr20 and or_rng < 1.2 * atr20:
                continue

            rest_df = session_df.slice(12)
            in_trade = False
            trade_dir = 0  # +1 = Long, -1 = Short
            entry_p = 0.0
            sl_p = 0.0
            tp_p = 0.0
            pos_weight = 0.0
            max_bars = min(len(rest_df), max_hold_bars)

            for i in range(max_bars):
                bar = rest_df[i]
                c = bar["close"][0]
                h = bar["high"][0]
                l = bar["low"][0]
                spx_c = bar["spx_close"][0]
                spx_v = bar["spx_vwap"][0]

                if not in_trade:
                    if i < 12:  # 1-hour entry cutoff
                        # LONG signal condition
                        sig_long = allow_long and (c > or_h) and (ema200 is None or c > ema200)
                        if spx_c is not None and spx_v is not None and spx_c <= spx_v:
                            sig_long = False

                        # SHORT signal condition
                        sig_short = allow_short and (c < or_l) and (ema200 is None or c < ema200)
                        if spx_c is not None and spx_v is not None and spx_c >= spx_v:
                            sig_short = False

                        if sig_long:
                            in_trade = True
                            trade_dir = 1
                            entry_p = c
                            sl_p = or_l
                            tp_p = entry_p + tp_multiple * or_rng
                            d_sl = (entry_p - sl_p) / entry_p + friction
                            pos_weight = (risk_fraction / d_sl) if d_sl > 0 else 1.0
                        elif sig_short:
                            in_trade = True
                            trade_dir = -1
                            entry_p = c
                            sl_p = or_h
                            tp_p = entry_p - tp_multiple * or_rng
                            d_sl = (sl_p - entry_p) / entry_p + friction
                            pos_weight = (risk_fraction / d_sl) if d_sl > 0 else 1.0

                else:
                    # Trade management
                    if trade_dir == 1:
                        # LONG POSITION
                        hit_tp = h >= tp_p
                        hit_sl = l <= sl_p

                        if hit_tp and hit_sl:
                            raw_ret = (sl_p - entry_p) / entry_p - friction
                            pnl_pct = pos_weight * raw_ret
                            pnl_dollar = pnl_pct * initial_capital
                            r_mult = pnl_pct / risk_fraction if risk_fraction > 0 else -1.0
                            all_trades.append({
                                "date": str(d), "year": d.year, "asset": asset_name, "dir": "LONG",
                                "entry": entry_p, "exit": sl_p, "reason": "Stop Loss",
                                "pnl_pct": pnl_pct, "pnl_dollar": pnl_dollar, "r_mult": r_mult
                            })
                            daily_pnl[d] += pnl_pct
                            break
                        elif hit_tp:
                            raw_ret = (tp_p - entry_p) / entry_p - friction
                            pnl_pct = pos_weight * raw_ret
                            pnl_dollar = pnl_pct * initial_capital
                            r_mult = pnl_pct / risk_fraction if risk_fraction > 0 else 2.0
                            all_trades.append({
                                "date": str(d), "year": d.year, "asset": asset_name, "dir": "LONG",
                                "entry": entry_p, "exit": tp_p, "reason": "Take Profit",
                                "pnl_pct": pnl_pct, "pnl_dollar": pnl_dollar, "r_mult": r_mult
                            })
                            daily_pnl[d] += pnl_pct
                            break
                        elif hit_sl:
                            raw_ret = (sl_p - entry_p) / entry_p - friction
                            pnl_pct = pos_weight * raw_ret
                            pnl_dollar = pnl_pct * initial_capital
                            r_mult = pnl_pct / risk_fraction if risk_fraction > 0 else -1.0
                            all_trades.append({
                                "date": str(d), "year": d.year, "asset": asset_name, "dir": "LONG",
                                "entry": entry_p, "exit": sl_p, "reason": "Stop Loss",
                                "pnl_pct": pnl_pct, "pnl_dollar": pnl_dollar, "r_mult": r_mult
                            })
                            daily_pnl[d] += pnl_pct
                            break
                        elif i == max_bars - 1:
                            raw_ret = (c - entry_p) / entry_p - friction
                            pnl_pct = pos_weight * raw_ret
                            pnl_dollar = pnl_pct * initial_capital
                            r_mult = pnl_pct / risk_fraction if risk_fraction > 0 else 0.0
                            all_trades.append({
                                "date": str(d), "year": d.year, "asset": asset_name, "dir": "LONG",
                                "entry": entry_p, "exit": c, "reason": "Session Close",
                                "pnl_pct": pnl_pct, "pnl_dollar": pnl_dollar, "r_mult": r_mult
                            })
                            daily_pnl[d] += pnl_pct
                            break

                    elif trade_dir == -1:
                        # SHORT POSITION
                        hit_tp = l <= tp_p
                        hit_sl = h >= sl_p

                        if hit_tp and hit_sl:
                            raw_ret = (entry_p - sl_p) / entry_p - friction
                            pnl_pct = pos_weight * raw_ret
                            pnl_dollar = pnl_pct * initial_capital
                            r_mult = pnl_pct / risk_fraction if risk_fraction > 0 else -1.0
                            all_trades.append({
                                "date": str(d), "year": d.year, "asset": asset_name, "dir": "SHORT",
                                "entry": entry_p, "exit": sl_p, "reason": "Stop Loss",
                                "pnl_pct": pnl_pct, "pnl_dollar": pnl_dollar, "r_mult": r_mult
                            })
                            daily_pnl[d] += pnl_pct
                            break
                        elif hit_tp:
                            raw_ret = (entry_p - tp_p) / entry_p - friction
                            pnl_pct = pos_weight * raw_ret
                            pnl_dollar = pnl_pct * initial_capital
                            r_mult = pnl_pct / risk_fraction if risk_fraction > 0 else 2.0
                            all_trades.append({
                                "date": str(d), "year": d.year, "asset": asset_name, "dir": "SHORT",
                                "entry": entry_p, "exit": tp_p, "reason": "Take Profit",
                                "pnl_pct": pnl_pct, "pnl_dollar": pnl_dollar, "r_mult": r_mult
                            })
                            daily_pnl[d] += pnl_pct
                            break
                        elif hit_sl:
                            raw_ret = (entry_p - sl_p) / entry_p - friction
                            pnl_pct = pos_weight * raw_ret
                            pnl_dollar = pnl_pct * initial_capital
                            r_mult = pnl_pct / risk_fraction if risk_fraction > 0 else -1.0
                            all_trades.append({
                                "date": str(d), "year": d.year, "asset": asset_name, "dir": "SHORT",
                                "entry": entry_p, "exit": sl_p, "reason": "Stop Loss",
                                "pnl_pct": pnl_pct, "pnl_dollar": pnl_dollar, "r_mult": r_mult
                            })
                            daily_pnl[d] += pnl_pct
                            break
                        elif i == max_bars - 1:
                            raw_ret = (entry_p - c) / entry_p - friction
                            pnl_pct = pos_weight * raw_ret
                            pnl_dollar = pnl_pct * initial_capital
                            r_mult = pnl_pct / risk_fraction if risk_fraction > 0 else 0.0
                            all_trades.append({
                                "date": str(d), "year": d.year, "asset": asset_name, "dir": "SHORT",
                                "entry": entry_p, "exit": c, "reason": "Session Close",
                                "pnl_pct": pnl_pct, "pnl_dollar": pnl_dollar, "r_mult": r_mult
                            })
                            daily_pnl[d] += pnl_pct
                            break

    rets_arr = np.array([daily_pnl[d] for d in dates])
    cum_equity = np.cumprod(1.0 + rets_arr)
    running_max = np.maximum.accumulate(cum_equity)
    drawdowns = (cum_equity - running_max) / running_max
    max_dd = float(np.abs(drawdowns.min())) if len(drawdowns) > 0 else 0.0

    wins = [t for t in all_trades if t["pnl_dollar"] > 0]
    losses = [t for t in all_trades if t["pnl_dollar"] <= 0]
    gross_profit = sum(t["pnl_dollar"] for t in wins)
    gross_loss = abs(sum(t["pnl_dollar"] for t in losses))
    net_profit_dollar = gross_profit - gross_loss
    net_profit_pct = (cum_equity[-1] - 1.0) * 100.0 if len(cum_equity) > 0 else 0.0
    win_rate = len(wins) / len(all_trades) if all_trades else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 99.0

    mean_ret = float(np.mean(rets_arr)) if len(rets_arr) > 0 else 0.0
    std_ret = float(np.std(rets_arr)) if len(rets_arr) > 0 else 0.0
    sharpe = (mean_ret / std_ret * np.sqrt(252)) if std_ret > 0 else 0.0

    return {
        "asset": asset_name,
        "session": session_label,
        "total_trades": len(all_trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate * 100.0, 1),
        "net_profit_dollar": round(net_profit_dollar, 2),
        "net_profit_pct": round(net_profit_pct, 2),
        "profit_factor": round(profit_factor, 2),
        "max_drawdown_pct": round(max_dd * 100.0, 2),
        "sharpe": round(sharpe, 2),
        "daily_pnl": daily_pnl,
        "trades": all_trades,
    }
