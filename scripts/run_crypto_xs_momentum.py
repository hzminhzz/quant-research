#!/usr/bin/env python3
"""Pre-registered cross-sectional crypto momentum replication on Binance 1h perps."""

from __future__ import annotations

import argparse
import glob
import json
import math
from pathlib import Path
from typing import Dict, Iterable

import numpy as np
import polars as pl
from scipy import stats

from src.experiment import compute_deflated_sharpe


def load_panel(root: Path, end_exclusive: str) -> tuple[pl.DataFrame, dict]:
    files = sorted(glob.glob(str(root / "symbol=*" / "data.parquet")))
    if not files:
        raise FileNotFoundError(f"no parquet partitions under {root}")

    frames = []
    integrity = {}
    cutoff = pl.lit(end_exclusive).str.to_datetime(time_zone="UTC")
    for raw in files:
        path = Path(raw)
        symbol = path.parent.name.split("=", 1)[-1]
        df = (
            pl.scan_parquet(path)
            .filter(pl.col("timestamp") < cutoff)
            .select("timestamp", "open", "high", "low", "close", "volume", "symbol")
            .collect()
            .sort("timestamp")
        )
        if not df.height:
            continue
        dup = int(df["timestamp"].is_duplicated().sum())
        bad_ohlc = df.filter(
            (pl.col("high") < pl.max_horizontal("open", "close", "low"))
            | (pl.col("low") > pl.min_horizontal("open", "close", "high"))
            | (pl.col("volume") < 0)
        ).height
        gaps = (
            df.select(pl.col("timestamp").diff().alias("gap"))
            .drop_nulls()
            .filter(pl.col("gap") != pl.duration(hours=1))
            .height
        )
        integrity[symbol] = {
            "rows": df.height,
            "start": df["timestamp"].min().isoformat(),
            "end": df["timestamp"].max().isoformat(),
            "duplicates": dup,
            "bad_ohlc_rows": int(bad_ohlc),
            "non_1h_gaps": int(gaps),
        }
        if dup or bad_ohlc:
            raise ValueError(f"integrity failure for {symbol}: dup={dup}, bad_ohlc={bad_ohlc}")
        frames.append(df)

    panel = pl.concat(frames, how="vertical").sort(["timestamp", "symbol"])
    return panel, integrity


def wide(panel: pl.DataFrame, value: str) -> pl.DataFrame:
    return (
        panel.select("timestamp", "symbol", value)
        .pivot(values=value, index="timestamp", on="symbol", aggregate_function="first")
        .sort("timestamp")
    )


def row_map(frame: pl.DataFrame) -> tuple[dict, list[str]]:
    symbols = [c for c in frame.columns if c != "timestamp"]
    return {ts: i for i, ts in enumerate(frame["timestamp"].to_list())}, symbols


def metrics(daily: list[dict], ret_key: str) -> dict:
    if not daily:
        return {"n_days": 0}
    vals = np.asarray([x[ret_key] for x in daily], dtype=float)
    if len(vals) < 2:
        return {"n_days": len(vals)}
    mean = float(vals.mean())
    std = float(vals.std(ddof=1))
    sharpe = mean / std * math.sqrt(365.0) if std > 0 else 0.0
    neg = vals[vals < 0]
    neg_std = float(neg.std(ddof=1)) if len(neg) > 1 else 0.0
    sortino = mean / neg_std * math.sqrt(365.0) if neg_std > 0 else 0.0
    equity = np.cumprod(1.0 + vals)
    peaks = np.maximum.accumulate(equity)
    dd = equity / peaks - 1.0
    max_dd = float(dd.min()) if len(dd) else 0.0
    total = float(equity[-1] - 1.0)
    cagr = float(equity[-1] ** (365.0 / len(vals)) - 1.0) if equity[-1] > 0 else -1.0
    pos = vals[vals > 0]
    negv = vals[vals < 0]
    pf = float(pos.sum() / abs(negv.sum())) if len(negv) and negv.sum() != 0 else None
    return {
        "n_days": int(len(vals)),
        "annualized_sharpe": sharpe,
        "sortino": sortino,
        "total_return": total,
        "cagr": cagr,
        "max_drawdown": max_dd,
        "calmar": cagr / abs(max_dd) if max_dd < 0 else 0.0,
        "win_rate": float((vals > 0).mean()),
        "profit_factor": pf,
        "mean_daily_return": mean,
        "daily_volatility": std,
    }


def aggregate_daily(hourly: list[dict], cost_bps: float, oos_start: np.datetime64) -> list[dict]:
    by_day: Dict[object, list[float]] = {}
    gross_by_day: Dict[object, list[float]] = {}
    cost_by_day: Dict[object, float] = {}
    for x in hourly:
        ts = x["timestamp"]
        if np.datetime64(ts.replace(tzinfo=None)) < oos_start:
            continue
        day = ts.date()
        net = x["gross_return"] - x["turnover_units"] * cost_bps / 10000.0
        by_day.setdefault(day, []).append(net)
        gross_by_day.setdefault(day, []).append(x["gross_return"])
        cost_by_day[day] = cost_by_day.get(day, 0.0) + x["turnover_units"] * cost_bps / 10000.0
    out = []
    for day in sorted(by_day):
        out.append({
            "date": day,
            "net_return": float(np.prod(1.0 + np.asarray(by_day[day])) - 1.0),
            "gross_return": float(np.prod(1.0 + np.asarray(gross_by_day[day])) - 1.0),
            "cost_drag": float(cost_by_day[day]),
        })
    return out


def run_variant(
    panel: pl.DataFrame,
    formation_hours: int,
    end_exclusive: str,
    oos_start: str,
    exclude: Iterable[str] = (),
    top_n_liquid: int = 15,
    min_history_hours: int = 720,
) -> dict:
    excluded = set(exclude)
    close_w = wide(panel, "close")
    open_w = wide(panel, "open")
    notion_panel = panel.with_columns((pl.col("close") * pl.col("volume")).alias("notional"))
    notional_w = wide(notion_panel, "notional")

    idx, symbols = row_map(close_w)
    symbols = [s for s in symbols if s not in excluded]
    ts_list = close_w["timestamp"].to_list()
    close_np = {s: close_w[s].to_numpy() for s in symbols}
    open_np = {s: open_w[s].to_numpy() for s in symbols}
    notional_np = {s: notional_w[s].to_numpy() for s in symbols}
    first_valid = {
        s: next((i for i, v in enumerate(close_np[s]) if np.isfinite(v)), len(ts_list))
        for s in symbols
    }

    end_dt = np.datetime64(end_exclusive.replace("Z", ""))
    rebalances = []
    for i, ts in enumerate(ts_list):
        if ts.weekday() == 0 and ts.hour == 0 and ts.minute == 0:
            if i - formation_hours >= 0 and i + 1 < len(ts_list) and i + 169 < len(ts_list):
                if np.datetime64(ts.replace(tzinfo=None)) < end_dt:
                    rebalances.append((i, ts))

    hourly = []
    weekly = []
    prev_w = {s: 0.0 for s in symbols}
    asset_contrib: Dict[str, float] = {s: 0.0 for s in symbols}
    ic_values = []
    q_spreads = []
    eligible_counts = []
    traded_counts = []

    for i, ts in rebalances:
        exit_i = i + 169
        if exit_i >= len(ts_list):
            continue
        exit_ts = ts_list[exit_i]
        if np.datetime64(exit_ts.replace(tzinfo=None)) >= end_dt:
            continue

        candidates = []
        for s in symbols:
            if first_valid[s] > i - min_history_hours:
                continue
            c_now = close_np[s][i]
            c_then = close_np[s][i - formation_hours]
            o_entry = open_np[s][i + 1]
            o_exit = open_np[s][exit_i]
            if not all(np.isfinite(v) and v > 0 for v in (c_now, c_then, o_entry, o_exit)):
                continue
            liq_slice = notional_np[s][i - 167 : i + 1]
            if len(liq_slice) != 168 or np.isfinite(liq_slice).sum() < 168:
                continue
            avg_notional = float(np.mean(liq_slice))
            mom = float(c_now / c_then - 1.0)
            hold_ret = float(o_exit / o_entry - 1.0)
            candidates.append((s, avg_notional, mom, hold_ret))

        candidates.sort(key=lambda x: x[1], reverse=True)
        candidates = candidates[:top_n_liquid]
        eligible_counts.append(len(candidates))
        if len(candidates) < 8:
            continue

        moms = np.asarray([x[2] for x in candidates], dtype=float)
        fwd = np.asarray([x[3] for x in candidates], dtype=float)
        ic = stats.spearmanr(moms, fwd).statistic
        if np.isfinite(ic):
            ic_values.append(float(ic))

        ranked = sorted(candidates, key=lambda x: x[2])
        n_leg = max(1, int(math.ceil(len(ranked) * 0.25)))
        shorts = ranked[:n_leg]
        longs = ranked[-n_leg:]
        q_spreads.append(float(np.mean([x[3] for x in longs]) - np.mean([x[3] for x in shorts])))

        new_w = {s: 0.0 for s in symbols}
        for s, _, _, _ in longs:
            new_w[s] = 0.5 / n_leg
        for s, _, _, _ in shorts:
            new_w[s] = -0.5 / n_leg
        traded_counts.append(sum(1 for v in new_w.values() if v != 0.0))

        turnover = float(sum(abs(new_w[s] - prev_w.get(s, 0.0)) for s in symbols))

        # Entry cost is charged on first held hour; positions are then fixed until next weekly entry.
        for h in range(i + 1, exit_i):
            gross = 0.0
            for s, w in new_w.items():
                if w == 0.0:
                    continue
                p0 = open_np[s][h]
                p1 = open_np[s][h + 1]
                if not (np.isfinite(p0) and np.isfinite(p1) and p0 > 0):
                    continue
                r = float(p1 / p0 - 1.0)
                gross += w * r
                asset_contrib[s] += w * r
            hourly.append({
                "timestamp": ts_list[h],
                "gross_return": gross,
                "turnover_units": turnover if h == i + 1 else 0.0,
            })

        weekly.append({
            "signal_timestamp": ts,
            "eligible": len(candidates),
            "n_leg": n_leg,
            "turnover_units": turnover,
            "rank_ic": float(ic) if np.isfinite(ic) else None,
            "quantile_spread": q_spreads[-1],
            "longs": [x[0] for x in longs],
            "shorts": [x[0] for x in shorts],
        })
        prev_w = new_w

    cost_results = {}
    for mult in (1.0, 2.0, 3.0):
        daily = aggregate_daily(hourly, 3.0 * mult, np.datetime64(oos_start.replace("Z", "")))
        cost_results[str(mult)] = {
            "net": metrics(daily, "net_return"),
            "gross": metrics(daily, "gross_return"),
            "cost_drag_sum": float(sum(x["cost_drag"] for x in daily)),
        }
        years = {}
        for year in (2022, 2023, 2024, 2025):
            part = [x for x in daily if x["date"].year == year]
            years[str(year)] = metrics(part, "net_return")
        cost_results[str(mult)]["by_year"] = years

    contrib_sorted = sorted(asset_contrib.items(), key=lambda kv: kv[1], reverse=True)
    return {
        "formation_hours": formation_hours,
        "excluded_symbols": sorted(excluded),
        "weekly_rebalances": len(weekly),
        "eligible_count_min": min(eligible_counts) if eligible_counts else 0,
        "eligible_count_median": float(np.median(eligible_counts)) if eligible_counts else 0.0,
        "traded_count_median": float(np.median(traded_counts)) if traded_counts else 0.0,
        "mean_rank_ic": float(np.mean(ic_values)) if ic_values else None,
        "ic_ir": float(np.mean(ic_values) / np.std(ic_values, ddof=1)) if len(ic_values) > 1 and np.std(ic_values, ddof=1) > 0 else None,
        "ic_positive_fraction": float(np.mean(np.asarray(ic_values) > 0)) if ic_values else None,
        "mean_top_bottom_spread": float(np.mean(q_spreads)) if q_spreads else None,
        "costs": cost_results,
        "asset_contribution_gross": contrib_sorted,
        "weekly_preview": weekly[:5],
    }


def load_previous_sharpes(registry: Path) -> list[float]:
    vals = []
    if not registry.exists():
        return vals
    for line in registry.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        val = rec.get("primary_oos_net_sharpe")
        if isinstance(val, (int, float)) and np.isfinite(val):
            vals.append(float(val))
    return vals


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--data-root", type=Path, required=True)
    p.add_argument("--end-exclusive", default="2025-10-01T00:00:00Z")
    p.add_argument("--oos-start", default="2022-01-01T00:00:00Z")
    p.add_argument("--registry", type=Path, default=Path("run_log/crypto_research/registry.jsonl"))
    p.add_argument("--compact", action="store_true")
    args = p.parse_args()

    panel, integrity = load_panel(args.data_root, args.end_exclusive)
    formations = [120, 168, 240]
    variants = {str(h): run_variant(panel, h, args.end_exclusive, args.oos_start) for h in formations}
    canonical = variants["168"]
    strongest = canonical["asset_contribution_gross"][0][0] if canonical["asset_contribution_gross"] else None
    exclude_btc_eth = run_variant(panel, 168, args.end_exclusive, args.oos_start, exclude={"BTCUSDT", "ETHUSDT"})
    remove_strongest = run_variant(panel, 168, args.end_exclusive, args.oos_start, exclude={strongest} if strongest else set())

    current_sharpes = [variants[str(h)]["costs"]["1.0"]["net"]["annualized_sharpe"] for h in formations]
    current_sharpes += [
        exclude_btc_eth["costs"]["1.0"]["net"]["annualized_sharpe"],
        remove_strongest["costs"]["1.0"]["net"]["annualized_sharpe"],
    ]
    previous = load_previous_sharpes(args.registry)
    all_sharpes = previous + current_sharpes
    canonical_sr = canonical["costs"]["1.0"]["net"]["annualized_sharpe"]
    n_days = canonical["costs"]["1.0"]["net"]["n_days"]
    dsr = compute_deflated_sharpe(canonical_sr, all_sharpes, n_obs_days=n_days)

    payload = {
        "schema_version": 1,
        "run_id": "20260928-xs-momentum-1w",
        "strategy": "1-week cross-sectional momentum",
        "data_root": str(args.data_root),
        "market": "Binance USDT-margined perpetual futures",
        "exploration_end_exclusive": args.end_exclusive,
        "oos_start": args.oos_start,
        "symbols_loaded": sorted(panel["symbol"].unique().to_list()),
        "symbol_count": panel["symbol"].n_unique(),
        "integrity": integrity,
        "canonical_formation_hours": 168,
        "variants": variants,
        "robustness": {
            "exclude_btc_eth": exclude_btc_eth,
            "remove_strongest_asset": {"removed": strongest, "result": remove_strongest},
        },
        "multiple_testing": {
            "previous_strategy_sharpes": previous,
            "current_variant_sharpes": current_sharpes,
            "cumulative_strategy_trials_used_for_dsr": len(all_sharpes),
            "dsr": dsr,
            "pbo": {"status": "N/A", "reason": "Five pre-registered rule/robustness variants are insufficient for a meaningful CPCV winner-selection PBO estimate."},
        },
    }
    if args.compact:
        c = payload["variants"]["168"]
        compact = {
            "run_id": payload["run_id"],
            "symbol_count": payload["symbol_count"],
            "mean_rank_ic": c["mean_rank_ic"],
            "ic_ir": c["ic_ir"],
            "mean_top_bottom_spread": c["mean_top_bottom_spread"],
            "base": c["costs"]["1.0"]["net"],
            "two_x": c["costs"]["2.0"]["net"],
            "three_x": c["costs"]["3.0"]["net"],
            "by_year": {y: v["annualized_sharpe"] for y, v in c["costs"]["1.0"]["by_year"].items()},
            "h120_sharpe": payload["variants"]["120"]["costs"]["1.0"]["net"]["annualized_sharpe"],
            "h240_sharpe": payload["variants"]["240"]["costs"]["1.0"]["net"]["annualized_sharpe"],
            "exclude_btc_eth_sharpe": payload["robustness"]["exclude_btc_eth"]["costs"]["1.0"]["net"]["annualized_sharpe"],
            "remove_strongest_asset": payload["robustness"]["remove_strongest_asset"]["removed"],
            "remove_strongest_sharpe": payload["robustness"]["remove_strongest_asset"]["result"]["costs"]["1.0"]["net"]["annualized_sharpe"],
            "multiple_testing": payload["multiple_testing"],
        }
        print(json.dumps(compact, indent=2, sort_keys=True, default=str))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
