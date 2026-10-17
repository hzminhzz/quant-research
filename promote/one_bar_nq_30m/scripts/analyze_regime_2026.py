#!/usr/bin/env python3
"""Describe the frozen 2026 one-bar result from copied ledgers and source bars."""
from __future__ import annotations

import hashlib
import json
import math
from importlib.metadata import version
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib.pyplot as plt
import polars as pl
from scipy.stats import ks_2samp
from ml4t.diagnostic.evaluation.drift import compute_psi

PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parents[1]
REPORT = PACKAGE / "reports/regime_2026"
LEDGERS = PACKAGE / "backtests/practical_yearly/by_year"
SOURCE = Path("/home/quant/dev/quant/ml4t-data/.data/store/index_minute_NQ")
SOURCE_MANIFEST = ROOT / "run_log/one_bar_dukascopy_2013_2026_20261011/source_manifest.json"
CUTOFF = datetime(2026, 7, 14, 23, 59, 59, tzinfo=timezone.utc)
CHI = ZoneInfo("America/Chicago")
MULTIPLIER = 20.0


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_csv(path: Path) -> pl.DataFrame:
    frame = pl.read_csv(path, try_parse_dates=False, infer_schema_length=10000)
    expressions = []
    for name in ("entry_time", "exit_time", "timestamp", "feature_available_at"):
        if name in frame.columns and frame.schema[name] == pl.String:
            expressions.append(pl.col(name).str.to_datetime(time_zone="UTC", strict=False).alias(name))
    return frame.with_columns(expressions) if expressions else frame


def load_trades(year: int, trial: str) -> pl.DataFrame:
    path = LEDGERS / str(year) / trial / "evaluation_trades.csv"
    if not path.is_file():
        raise FileNotFoundError(path)
    frame = read_csv(path).filter(pl.col("status") == "closed")
    native = read_csv(path.parent / "trades.csv").with_row_index("native_trade_index")
    paired_fills = pair_native_exit_fills(read_csv(path.parent / "fills.csv"), native)
    if frame.select(pl.struct("entry_time", "exit_time", "direction").n_unique()).item() != frame.height:
        raise ValueError(f"Duplicate evaluation trade keys in {path}")
    frame = frame.join(paired_fills, on=["entry_time", "exit_time", "direction"], how="left", validate="1:1")
    if frame["exit_fill_order_type"].null_count():
        raise ValueError(f"Native fills did not reconcile to every evaluation trade in {path}")
    if year != 2026:
        local_date = pl.col("entry_time").dt.convert_time_zone("America/Chicago").dt.date()
        frame = frame.filter(local_date.is_between(date(year, 1, 1), date(year, 7, 14), closed="both"))
    return frame.with_columns(pl.lit(year).alias("ledger_year"))


def pair_native_exit_fills(fills: pl.DataFrame, native: pl.DataFrame) -> pl.DataFrame:
    """Pair alternating native entry/exit fill rows and reconcile to native trades."""
    fills = fills.with_row_index("fill_row")
    if fills.height % 2:
        raise ValueError("Native fill ledger must contain exactly two fills per trade")
    entries = fills.filter(pl.col("fill_row") % 2 == 0).select(
        (pl.col("fill_row") // 2).alias("native_trade_index"),
        pl.col("timestamp").alias("entry_time"), pl.col("side").alias("entry_side"))
    exits = fills.filter(pl.col("fill_row") % 2 == 1).select(
        (pl.col("fill_row") // 2).alias("native_trade_index"),
        pl.col("timestamp").alias("exit_time"), pl.col("order_type").alias("exit_fill_order_type"))
    if exits.filter(~pl.col("exit_fill_order_type").is_in(["stop", "market"])).height:
        raise ValueError("Unexpected native exit order type")
    if entries.height != native.height:
        raise ValueError("Native trade and fill row counts do not reconcile")
    paired = (entries.join(exits, on="native_trade_index", validate="1:1")
              .join(native.select("native_trade_index", "entry_time", "exit_time", "direction"),
                    on="native_trade_index", suffix="_native", validate="1:1"))
    if paired.filter((pl.col("entry_time") != pl.col("entry_time_native"))
                     | (pl.col("exit_time") != pl.col("exit_time_native"))).height:
        raise ValueError("Native fill timestamps differ from native trades.csv")
    expected_side = pl.when(pl.col("direction") == "long").then(pl.lit("buy")).otherwise(pl.lit("sell"))
    if paired.filter(pl.col("entry_side") != expected_side).height:
        raise ValueError("Native entry fill side differs from trade direction")
    return paired.select("entry_time_native", "exit_time_native", "direction", "exit_fill_order_type") \
        .rename({"entry_time_native": "entry_time", "exit_time_native": "exit_time"})


def release_complete_30m_bars(bars: pl.DataFrame) -> pl.DataFrame:
    return bars.with_columns((pl.col("bar_start") + pl.duration(minutes=30)).alias("feature_available_at"))


def join_available_features(trades: pl.DataFrame, bars: pl.DataFrame, columns: list[str]) -> pl.DataFrame:
    return trades.sort("entry_time").join_asof(
        bars.select("feature_available_at", *columns).sort("feature_available_at"),
        left_on="entry_time", right_on="feature_available_at", strategy="backward")


def chicago_rth_expression(timestamp: str = "entry_local") -> pl.Expr:
    minute = pl.col(timestamp).dt.hour().cast(pl.Int32) * 60 + pl.col(timestamp).dt.minute().cast(pl.Int32)
    return pl.when((minute >= 510) & (minute < 900)).then(pl.lit("RTH")).otherwise(pl.lit("overnight"))


def build_complete_bar_features(source: pl.DataFrame) -> pl.DataFrame:
    bars = (source.group_by("session_date", "bar_no").agg(
        pl.col("timestamp").min().alias("bar_start"),
        pl.col("open").first().alias("open"), pl.col("high").max().alias("high"),
        pl.col("low").min().alias("low"), pl.col("close").last().alias("close"),
        pl.col("volume").sum().alias("volume"), pl.len().alias("n"),
        pl.col("timestamp").n_unique().alias("unique_n"),
    ).filter((pl.col("n") == 30) & (pl.col("unique_n") == 30)).sort("bar_start"))
    from ml4t.engineer import compute_features
    bars = compute_features(bars, [{"name": "atr", "output": "atr20", "params": {"period": 20}}],
                            timestamp_col="bar_start", assume_sorted=True)
    bars = bars.with_columns(
        (pl.col("high") - pl.col("low")).abs().alias("bar_range"),
        ((pl.col("close") - pl.col("close").shift(20)).abs()
         / pl.col("close").diff().abs().rolling_sum(window_size=20, min_samples=20)).alias("efficiency_20"),
        pl.col("high").rolling_max(window_size=50, min_samples=50).alias("channel_high_50"),
        pl.col("low").rolling_min(window_size=50, min_samples=50).alias("channel_low_50"),
    ).with_columns(
        (pl.col("channel_high_50") - pl.col("channel_low_50")).alias("channel_width_50"),
        (pl.col("atr20") / pl.col("close") * 10000).alias("atr20_bps"),
        (pl.col("bar_range") / pl.col("atr20")).alias("prior_range_atr20"),
        pl.col("atr20").shift(1).rolling_quantile(quantile=1 / 3, window_size=252, min_samples=252).alias("atr_past252_q33"),
        pl.col("atr20").shift(1).rolling_quantile(quantile=2 / 3, window_size=252, min_samples=252).alias("atr_past252_q67"),
    ).with_columns(
        (pl.col("channel_width_50") / pl.col("close") * 10000).alias("channel_width_50_bps"),
        pl.when(pl.col("atr20") <= pl.col("atr_past252_q33")).then(pl.lit("low"))
        .when(pl.col("atr20") <= pl.col("atr_past252_q67")).then(pl.lit("mid"))
        .otherwise(pl.lit("high")).alias("atr_past252_regime"),
    )
    return release_complete_30m_bars(bars)


def validate_cutoff(frame: pl.DataFrame) -> None:
    """Reject any ledger row that reaches beyond the frozen observation boundary."""
    if frame.height and (frame["entry_time"].max() > CUTOFF or frame["exit_time"].max() > CUTOFF):
        raise ValueError("Trade ledger exceeds the 2026-07-14 UTC cutoff")


def load_source_bars() -> tuple[pl.DataFrame, pl.DataFrame, dict]:
    files = sorted(p for p in SOURCE.glob("year=*/month=*/data.parquet")
                   if 2017 <= int(p.parent.parent.name.split("=")[1]) <= 2026
                   and (int(p.parent.parent.name.split("=")[1]) < 2026
                        or int(p.parent.name.split("=")[1]) <= 7))
    if not files or not SOURCE_MANIFEST.is_file():
        raise FileNotFoundError("Canonical source partitions or source manifest are missing")
    manifest_sha = sha256(SOURCE_MANIFEST)
    if manifest_sha != "fd810bef0a390a77972d22d1cb0100e6d17f46dec437bed5abf865f39e579e75":
        raise ValueError("Canonical source manifest hash differs from the frozen strategy identity")
    source_records = {row["path"]: row["sha256"] for row in json.loads(SOURCE_MANIFEST.read_text())}
    mismatches = [p for p in files if source_records.get(p.relative_to(SOURCE).as_posix()) != sha256(p)]
    if mismatches:
        raise ValueError(f"Canonical source partition hash mismatch: {mismatches[:3]}")
    end_naive = datetime(2026, 7, 14, 23, 59, 59)
    raw = (pl.scan_parquet([str(p) for p in files])
           .filter(pl.col("timestamp").is_between(datetime(2017, 1, 1), end_naive, closed="both"))
           .select("timestamp", "open", "high", "low", "close", "volume")
           .sort("timestamp").collect()
           .with_columns(pl.col("timestamp").dt.replace_time_zone("UTC")))
    local = pl.col("timestamp").dt.convert_time_zone("America/Chicago")
    minute_of_day = local.dt.hour().cast(pl.Int32) * 60 + local.dt.minute().cast(pl.Int32)
    raw = raw.with_columns(
        local.alias("local"),
        pl.when(minute_of_day >= 1020).then(local.dt.date())
        .otherwise(local.dt.date().dt.offset_by("-1d")).alias("session_date"),
    )
    dates = raw["session_date"].unique().sort().to_list()
    starts = pl.DataFrame({
        "session_date": dates,
        "session_start_utc": [datetime.combine(d, time(17), CHI).astimezone(timezone.utc) for d in dates],
    })
    source = raw.join(starts, on="session_date", how="left").with_columns(
        ((pl.col("timestamp") - pl.col("session_start_utc")).dt.total_minutes() // 30).alias("bar_no"))
    bars = build_complete_bar_features(source)
    # This auxiliary daily series describes the same proxy. It is not a macro cause or a strategy input.
    daily = (raw.with_columns(local.dt.date().alias("chicago_date"))
             .group_by("chicago_date").agg(pl.col("close").last().alias("close"))
             .sort("chicago_date").with_columns(
                 pl.col("close").pct_change().alias("daily_return"),
                 (pl.col("close").pct_change().rolling_std(window_size=20, min_samples=20)
                  * math.sqrt(252) * 100).alias("realized_vol_20d_pct"),
                 (pl.col("close") / pl.col("close").shift(20) - 1).mul(100).alias("trend_20d_pct"),
             ).filter(pl.col("chicago_date").is_between(date(2018, 1, 1), date(2026, 7, 14), closed="both")))
    provenance = {"canonical_source_root": str(SOURCE), "source_manifest": str(SOURCE_MANIFEST.relative_to(ROOT)),
                  "source_manifest_sha256": manifest_sha, "partitions_scanned": len(files),
                  "partitions_hash_verified": len(files), "all_scanned_partition_hashes_match": True,
                  "source_start_inclusive_utc": "2017-01-01T00:00:00Z",
                  "source_end_inclusive_utc": "2026-07-14T23:59:59Z",
                  "minute_rows_loaded": raw.height, "complete_30m_bars": bars.height,
                  "daily_proxy_observations": daily.height,
                  "library_versions": {"polars": version("polars"), "ml4t-engineer": version("ml4t-engineer"),
                                       "ml4t-diagnostic": version("ml4t-diagnostic")},
                  "bars": "30 unique source minutes; Chicago 17:00 anchored; incomplete bars excluded",
                  "input_type": "Dukascopy USATECH.IDX/USD BID-only index/CFD proxy; not CME NQ"}
    raw_next = raw.with_columns(
        pl.col("timestamp").shift(-1).alias("next_timestamp"),
        pl.col("open").shift(-1).alias("next_open"),
    ).select("timestamp", "open", "close", "next_timestamp", "next_open")
    raw_path = raw.filter(pl.col("timestamp").dt.date().is_between(date(2026, 1, 1), date(2026, 7, 14), closed="both"))
    return bars, daily, provenance, raw_next, raw_path


def add_features(trades: pl.DataFrame, bars: pl.DataFrame, raw_next: pl.DataFrame,
                 raw_path: pl.DataFrame) -> pl.DataFrame:
    result = (join_available_features(trades, bars, ["atr20", "atr20_bps", "efficiency_20",
                    "prior_range_atr20", "channel_width_50", "channel_width_50_bps",
                    "channel_high_50", "channel_low_50", "atr_past252_q33", "atr_past252_q67",
                    "atr_past252_regime"])
        .with_columns(pl.col("entry_time").dt.convert_time_zone("America/Chicago").alias("entry_local"),
                      pl.col("exit_time").dt.convert_time_zone("America/Chicago").alias("exit_local"))
        .with_columns(
            chicago_rth_expression().alias("session"),
            pl.when(pl.col("exit_fill_order_type") == "stop")
            .then(pl.lit("STOP")).otherwise(pl.lit("MARKET")).alias("exit_class"),
            pl.col("entry_time").dt.convert_time_zone("America/Chicago").dt.month().alias("entry_month"),
            pl.col("entry_time").dt.convert_time_zone("America/Chicago").dt.date().alias("entry_date_chicago"),
            pl.col("exit_time").dt.convert_time_zone("America/Chicago").dt.date().alias("exit_date_chicago"),
        ))
    if result.filter(pl.col("feature_available_at").is_null() | (pl.col("feature_available_at") > pl.col("entry_time"))).height:
        raise ValueError("A pre-entry feature is missing or released after its trade entry")
    raw_next = raw_next.sort("timestamp")
    result = result.join_asof(raw_next, left_on="entry_time", right_on="timestamp", strategy="backward")
    result = result.with_row_index("trade_id").with_columns(
        pl.when(pl.col("direction") == "long").then(pl.col("entry_price") - pl.col("channel_high_50"))
        .otherwise(pl.col("channel_low_50") - pl.col("entry_price")).alias("breakout_distance_points"),
        pl.when(pl.col("direction") == "long").then(pl.lit(1.0)).otherwise(pl.lit(-1.0)).alias("trade_sign"),
    ).with_columns(
        (pl.col("breakout_distance_points") / pl.col("atr20")).alias("breakout_distance_atr20"),
        ((pl.col("entry_price") - pl.col("open")) * pl.col("trade_sign")).alias("entry_minute_open_gap_points"),
        ((pl.col("next_open") - pl.col("entry_price")) * pl.col("trade_sign")).alias("next_observed_open_move_points"),
        (pl.col("mfe") * pl.col("entry_price")).alias("ledger_mfe_points"),
        (pl.col("mae") * pl.col("entry_price")).alias("ledger_mae_points"),
    ).with_columns(
        (pl.col("entry_minute_open_gap_points") / pl.col("atr20")).alias("entry_minute_open_gap_atr20"),
        (pl.col("next_observed_open_move_points") / pl.col("atr20")).alias("next_observed_open_move_atr20"),
        (pl.col("ledger_mfe_points") / pl.col("atr20")).alias("ledger_mfe_atr20"),
        (pl.col("ledger_mae_points") / pl.col("atr20")).alias("ledger_mae_atr20"),
        (pl.col("ledger_mae_points") <= -50).alias("nominal_50pt_stop_excursion"),
    )
    intervals = result.select("trade_id", "entry_time", "exit_time", "entry_price", "direction")
    path = raw_path.select("timestamp", "high", "low").join_where(
        intervals, pl.col("timestamp") >= pl.col("entry_time"), pl.col("timestamp") <= pl.col("exit_time"))
    stop_level = pl.when(pl.col("direction") == "long").then(pl.col("entry_price") - 50.0).otherwise(pl.col("entry_price") + 50.0)
    path = path.with_columns(
        pl.when(pl.col("direction") == "long").then(pl.col("low") <= stop_level)
        .otherwise(pl.col("high") >= stop_level).alias("nominal_stop_touched"))
    stop_hits = (path.group_by("trade_id").agg(
        pl.col("nominal_stop_touched").any().alias("nominal_stop_touched_in_trade_path"),
        pl.col("timestamp").filter(pl.col("nominal_stop_touched")).min().alias("first_nominal_stop_touch_time"),
        pl.len().alias("minute_bars_in_trade_path_inclusive")))
    return result.join(stop_hits, on="trade_id", how="left").with_columns(
        pl.col("nominal_stop_touched_in_trade_path").fill_null(False))


def agg(frame: pl.DataFrame, by: str | list[str]) -> pl.DataFrame:
    return frame.group_by(by).agg(
        pl.len().alias("trades"), pl.col("pnl").sum().alias("net_pnl_usd"),
        pl.col("gross_pnl").sum().alias("costed_gross_before_commission_usd"),
        (pl.col("pnl") > 0).mean().alias("win_rate"),
        pl.col("pnl").filter(pl.col("pnl") > 0).sum().alias("wins_usd"),
        pl.col("pnl").filter(pl.col("pnl") < 0).sum().alias("losses_usd"),
        pl.col("bars_held").mean().alias("mean_bars_held"),
        pl.col("bars_held").median().alias("median_bars_held"),
    ).with_columns(
        pl.when(pl.col("losses_usd") < 0).then(pl.col("wins_usd") / -pl.col("losses_usd"))
        .otherwise(None).alias("profit_factor"))


def summarise(frame: pl.DataFrame, by: str | list[str]) -> list[dict]:
    return agg(frame, by).sort(by).to_dicts()


def quantile_cutpoints(reference: pl.DataFrame, field: str) -> tuple[float, float]:
    values = reference[field].drop_nulls()
    return float(values.quantile(1 / 3)), float(values.quantile(2 / 3))


def daily_drawdown(frame: pl.DataFrame) -> dict:
    daily = (frame.group_by("exit_date_chicago").agg(pl.col("pnl").sum().alias("pnl"))
             .sort("exit_date_chicago").with_columns(pl.col("pnl").cum_sum().alias("equity"),
                 pl.col("pnl").cum_sum().cum_max().alias("peak"))
             .with_columns((pl.col("equity") - pl.col("peak")).alias("drawdown")))
    row = daily.sort("drawdown").head(1).to_dicts()
    return {"sessions": daily.height, "max_drawdown_usd_from_running_cashflow_peak": row[0] if row else None}


def top_concentration(frame: pl.DataFrame) -> dict:
    rows = frame.sort("pnl").select("pnl").to_series().to_list()
    best = sorted(rows, reverse=True)
    worst = sorted(rows)
    return {f"best_{n}_sum_usd": sum(best[:n]) for n in (1, 3, 5, 10)} | {
        f"worst_{n}_sum_usd": sum(worst[:n]) for n in (1, 3, 5, 10)}


def event_months(frame: pl.DataFrame) -> list[dict]:
    return summarise(frame, "entry_month")


def write_chart(monthly: pl.DataFrame, regimes: pl.DataFrame, daily: pl.DataFrame, path: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(14, 9), constrained_layout=True)
    x = monthly["month"].to_list()
    width = 0.19
    axes[0, 0].bar([i - 1.5 * width for i in x], monthly["costed_net_usd"], width, label="Full-tick total net")
    axes[0, 0].bar([i - .5 * width for i in x], monthly["zero_cost_net_usd"], width, label="Zero-cost total net")
    axes[0, 0].bar([i + .5 * width for i in x], monthly["stop_net_usd"], width, label="Native STOP exit net")
    axes[0, 0].bar([i + 1.5 * width for i in x], monthly["market_net_usd"], width, label="Native MARKET exit net")
    axes[0, 0].axhline(0, color="black", lw=.7)
    axes[0, 0].set(title="2026 monthly total and native exit PnL (USD)", xlabel="Entry month", ylabel="USD")
    axes[0, 0].legend(fontsize=8)

    ax_count = axes[0, 1]
    ax_count.bar(x, monthly["trades"], width * 1.4, label="Trades", color="#457b9d")
    ax_count.set(title="Monthly outcomes and STOP frequency", xlabel="Entry month", ylabel="Trades")
    ax_pct = ax_count.twinx()
    ax_pct.bar([i + width for i in x], [v * 100 for v in monthly["stop_share_pct"]], width,
               label="2026 STOP exits (%)", color="#f4a261")
    ax_pct.plot(x, [v * 100 for v in monthly["reference_stop_share_pct"]], "r.--",
                label="2018–25 same-month STOP share")
    ax_pct.plot(x, [v * 100 for v in monthly["win_rate"]], "ko-", label="Win rate (%)")
    ax_pct.set_ylabel("Percent")
    handles, labels = ax_count.get_legend_handles_labels()
    pct_handles, pct_labels = ax_pct.get_legend_handles_labels()
    ax_count.legend(handles + pct_handles, labels + pct_labels, fontsize=8, loc="upper left")

    d = daily.to_pandas()
    ax = axes[1, 0]
    ax.plot(d["chicago_date"], d["trend_20d_pct"], color="#264653", label="20-session proxy return (%)")
    ax.set(title="Underlying proxy trend and realized volatility", ylabel="20-session return (%)")
    ax2 = ax.twinx()
    ax2.plot(d["chicago_date"], d["realized_vol_20d_pct"], color="#e76f51", alpha=.8, label="20-session realized vol (%)")
    ax2.set_ylabel("Annualized realized volatility (%)")
    ax.legend(loc="upper left", fontsize=8)
    ax2.legend(loc="upper right", fontsize=8)

    if regimes.height:
        labels = regimes["regime"].to_list()
        values = regimes["net_pnl_usd"].to_list()
        bars = axes[1, 1].bar(labels, values, color=["#457b9d", "#f4a261", "#e76f51"][:len(labels)])
        axes[1, 1].axhline(0, color="black", lw=.7)
        axes[1, 1].set(title="2026 net PnL by 2018–25 ATR tercile", xlabel="Prior-bar ATR reference tercile", ylabel="USD")
        for bar, count in zip(bars, regimes["trades"].to_list(), strict=True):
            axes[1, 1].text(bar.get_x() + bar.get_width()/2, bar.get_height(), f"n={count}", ha="center", va="bottom", fontsize=8)
    fig.suptitle("One-bar breakout 2026 regime diagnostics (through July 14)", fontsize=14)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def refresh_package_manifest() -> None:
    path = PACKAGE / "provenance/manifest.json"
    manifest = json.loads(path.read_text())
    files = manifest["files"]
    owned = [PACKAGE / "README.md", PACKAGE / "scripts/analyze_regime_2026.py",
             PACKAGE / "tests/test_regime_2026.py", *REPORT.glob("*")]
    for item in owned:
        if item.is_file() and item != path:
            relative = item.relative_to(PACKAGE).as_posix()
            files[relative] = {"sha256": sha256(item), "source": None}
    manifest["file_count_excluding_manifest"] = len(files)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def main() -> None:
    manifest = json.loads((REPORT / "analysis_manifest.json").read_text())
    assert manifest["outcome_boundary_utc_inclusive"] == "2026-07-14T23:59:59Z"
    costed_parts = [load_trades(year, "native_full_tick_cost") for year in range(2018, 2027)]
    zero_2026 = load_trades(2026, "native_zero_cost")
    costed = pl.concat(costed_parts, how="diagonal_relaxed")
    y2026 = costed.filter(pl.col("ledger_year") == 2026)
    validate_cutoff(y2026)
    zero_2026 = zero_2026.filter(pl.col("entry_time").is_not_null())
    validate_cutoff(zero_2026)
    expected = manifest["required_reconciliations"]
    if y2026.height != expected["trade_count"] or not math.isclose(y2026["pnl"].sum(), expected["full_tick_net_pnl_usd"], abs_tol=0.01):
        raise ValueError("2026 full-tick ledger does not reconcile to the frozen mission totals")
    if not math.isclose(zero_2026["pnl"].sum(), expected["zero_cost_pnl_usd"], abs_tol=0.01):
        raise ValueError("2026 zero-cost ledger does not reconcile to the frozen mission total")
    if not math.isclose(zero_2026["pnl"].sum() - y2026["pnl"].sum(), expected["modeled_cost_drag_usd"], abs_tol=0.01):
        raise ValueError("Full-tick vs zero-cost PnL difference does not reconcile")

    bars, daily, source_meta, raw_next, raw_path = load_source_bars()
    enriched = add_features(costed, bars, raw_next, raw_path)
    y2026 = enriched.filter(pl.col("ledger_year") == 2026)
    prior = enriched.filter(pl.col("ledger_year").is_between(2018, 2025))
    entry_ctx_path = LEDGERS / "2026/native_full_tick_cost/entry_context.csv"
    context = read_csv(entry_ctx_path)
    context_join = y2026.select("entry_time", "direction").join(
        context, on="entry_time", how="left", suffix="_context")
    if context_join.height != y2026.height or context_join["volatility_proxy"].null_count() != 0:
        raise ValueError("2026 entry_context rows do not join one-to-one to the full-tick ledger")
    if context_join.filter(pl.col("direction") != pl.col("side")).height:
        raise ValueError("2026 entry_context side differs from trade ledger")
    y2026 = y2026.join(context.select("entry_time", "volatility_proxy"), on="entry_time", how="left")
    paired = y2026.join(zero_2026.select("entry_time", "direction", "exit_time", "pnl")
                        .rename({"exit_time": "zero_cost_exit_time", "pnl": "zero_cost_pnl"}),
                        on=["entry_time", "direction"], how="inner")
    if paired.height != y2026.height:
        raise ValueError("Zero-cost and full-tick 2026 entries do not match one-to-one")
    paired = paired.with_columns((pl.col("gross_pnl") - pl.col("zero_cost_pnl")).round(2).alias("gross_delta_vs_zero_cost"))
    pair_delta_by_exit_type = (paired.group_by("exit_fill_order_type").agg(
        pl.len().alias("trades"), pl.col("gross_delta_vs_zero_cost").sum().alias("gross_delta_vs_zero_cost_usd"),
        pl.col("total_slippage_cost").sum().alias("recorded_slippage_usd"),
    ).sort("exit_fill_order_type").to_dicts())

    monthly = (agg(y2026, "entry_month").rename({"net_pnl_usd": "costed_net_usd",
                "costed_gross_before_commission_usd": "costed_gross_usd"})
               .sort("entry_month"))
    zero_month = (zero_2026.with_columns(pl.col("entry_time").dt.convert_time_zone("America/Chicago").dt.month().alias("entry_month"))
                  .group_by("entry_month").agg(pl.col("pnl").sum().alias("zero_cost_net_usd")))
    stop_month = y2026.group_by("entry_month").agg(
        (pl.col("exit_class") == "STOP").mean().alias("stop_share_pct"),
        (pl.col("exit_class") == "STOP").sum().alias("stop_trades"))
    reference_stop_month = prior.group_by("entry_month").agg(
        pl.len().alias("reference_trades"),
        (pl.col("exit_class") == "STOP").sum().alias("reference_stop_trades"),
        (pl.col("exit_class") == "STOP").mean().alias("reference_stop_share_pct"))
    exit_month = (y2026.group_by("entry_month", "exit_class").agg(pl.col("pnl").sum().alias("exit_class_net_usd"))
                  .pivot(on="exit_class", index="entry_month", values="exit_class_net_usd")
                  .rename({"STOP": "stop_net_usd", "MARKET": "market_net_usd"}))
    monthly = (monthly.join(zero_month, on="entry_month", how="left").join(stop_month, on="entry_month", how="left")
               .join(reference_stop_month, on="entry_month", how="left")
               .join(exit_month, on="entry_month", how="left").rename({"entry_month": "month"})
               .with_columns(pl.col("stop_net_usd").fill_null(0), pl.col("market_net_usd").fill_null(0)))
    monthly.write_csv(REPORT / "monthly_attribution.csv")
    market_monthly = (daily.filter(pl.col("chicago_date").dt.year() == 2026)
                      .with_columns(pl.col("chicago_date").dt.month().alias("month"))
                      .group_by("month").agg(
                          pl.len().alias("source_days"), pl.col("close").first().alias("first_close"),
                          pl.col("close").last().alias("last_close"),
                          pl.col("realized_vol_20d_pct").mean().alias("mean_realized_vol_20d_pct"),
                          pl.col("trend_20d_pct").mean().alias("mean_trend_20d_pct"),
                      ).with_columns(((pl.col("last_close") / pl.col("first_close") - 1) * 100).alias("monthly_return_pct"))
                      .sort("month"))

    prior_by_year = (agg(prior, "ledger_year").rename({"ledger_year": "year"}).sort("year"))
    reference_2018 = prior.filter(pl.col("ledger_year") == 2018)
    full_year_2018 = read_csv(LEDGERS / "2018/native_full_tick_cost/evaluation_trades.csv").filter(pl.col("status") == "closed")
    prior_summary = {"matched_2018_2025_jan_jul14": prior_by_year.to_dicts(),
                     "matched_2018_2025_n": prior.height,
                     "matched_2018_2025_net_pnl_usd": float(prior["pnl"].sum()),
                     "matched_2018_2025_mean_per_trade_usd": float(prior["pnl"].mean())}

    groupings = {"side": ["direction"], "exit_reason_raw": ["exit_reason"],
                 "exit_fill_order_type": ["exit_fill_order_type"], "exit_class": ["exit_class"],
                 "hold_bars": ["bars_held"], "session": ["session"], "month": ["entry_month"],
                 "side_by_exit": ["direction", "exit_class"], "month_by_side": ["entry_month", "direction"],
                 "month_by_exit": ["entry_month", "exit_class"], "session_by_side": ["session", "direction"]}
    breakdowns = {name: summarise(y2026, fields) for name, fields in groupings.items()}
    if not math.isclose(sum(row["net_pnl_usd"] for row in breakdowns["side"]), float(y2026["pnl"].sum()), abs_tol=0.01):
        raise AssertionError("Side attribution does not sum to total")
    if not math.isclose(sum(row["net_pnl_usd"] for row in breakdowns["exit_class"]), float(y2026["pnl"].sum()), abs_tol=0.01):
        raise AssertionError("Exit attribution does not sum to total")
    if not math.isclose(sum(row["costed_net_usd"] for row in monthly.to_dicts()), float(y2026["pnl"].sum()), abs_tol=0.01):
        raise AssertionError("Monthly attribution does not sum to total")
    if y2026.filter(pl.col("session") == "RTH").height == 0:
        raise AssertionError("Chicago RTH classification unexpectedly has no trades")
    if not math.isclose(sum(row["net_pnl_usd"] for row in breakdowns["session"]), float(y2026["pnl"].sum()), abs_tol=0.01):
        raise AssertionError("Session attribution does not sum to total")
    exit_totals = {row["exit_class"]: row for row in breakdowns["exit_class"]}
    if (exit_totals.get("STOP", {}).get("trades"), round(exit_totals.get("STOP", {}).get("net_pnl_usd", 0), 2),
            exit_totals.get("MARKET", {}).get("trades"), round(exit_totals.get("MARKET", {}).get("net_pnl_usd", 0), 2)) != (44, -48058.76, 194, 33891.80):
        raise AssertionError("Native 2026 STOP/MARKET fill attribution does not match the independent ledger reconciliation")

    reference = prior
    atr_cuts = quantile_cutpoints(reference, "atr20_bps")
    er_cuts = quantile_cutpoints(reference, "efficiency_20")
    y2026 = y2026.with_columns(
        pl.when(pl.col("atr20_bps") <= atr_cuts[0]).then(pl.lit("low"))
        .when(pl.col("atr20_bps") <= atr_cuts[1]).then(pl.lit("mid")).otherwise(pl.lit("high")).alias("atr_regime"),
        pl.when(pl.col("efficiency_20") <= er_cuts[0]).then(pl.lit("low"))
        .when(pl.col("efficiency_20") <= er_cuts[1]).then(pl.lit("mid")).otherwise(pl.lit("high")).alias("efficiency_regime"))
    reference = reference.with_columns((50.0 / pl.col("atr20")).alias("stop_50pt_over_atr20"))
    y2026 = y2026.with_columns((50.0 / pl.col("atr20")).alias("stop_50pt_over_atr20"))
    stop_ratio_cuts = quantile_cutpoints(reference, "stop_50pt_over_atr20")
    stop_ratio_rows = []
    for period, sample in (("reference_2018_2025", reference), ("2026", y2026)):
        labeled = sample.with_columns(
            pl.when(pl.col("stop_50pt_over_atr20") <= stop_ratio_cuts[0]).then(pl.lit("low_50pt_atr_ratio"))
            .when(pl.col("stop_50pt_over_atr20") <= stop_ratio_cuts[1]).then(pl.lit("mid_50pt_atr_ratio"))
            .otherwise(pl.lit("high_50pt_atr_ratio")).alias("stop_ratio_tercile"))
        for row in labeled.group_by("stop_ratio_tercile").agg(
            pl.len().alias("trades"), (pl.col("exit_class") == "STOP").mean().alias("stop_probability"),
            pl.col("pnl").sum().alias("net_pnl_usd"),
            pl.col("stop_50pt_over_atr20").median().alias("median_stop_50pt_over_atr20")
        ).sort("stop_ratio_tercile").to_dicts():
            stop_ratio_rows.append({"period": period, **row})
    stop_ratio_analysis = {
        "stop_distance_points": 50.0, "contract_multiplier_usd_per_point": MULTIPLIER,
        "nominal_stop_risk_usd_per_contract": 50.0 * MULTIPLIER,
        "reference_2018_full_year_median_entry_price": float(full_year_2018["entry_price"].median()),
        "reference_2018_2025_median_entry_price": float(reference["entry_price"].median()),
        "current_2026_median_entry_price": float(y2026["entry_price"].median()),
        "reference_2018_full_year_stop_bps_of_median_price": float(50 / full_year_2018["entry_price"].median() * 10000),
        "reference_2018_2025_stop_bps_of_median_price": float(50 / reference["entry_price"].median() * 10000),
        "current_stop_bps_of_median_price": float(50 / y2026["entry_price"].median() * 10000),
        "reference_median_pre_entry_atr20_points": float(reference["atr20"].median()),
        "current_median_pre_entry_atr20_points": float(y2026["atr20"].median()),
        "reference_tercile_cutpoints_for_50_over_atr20": list(stop_ratio_cuts),
        "stop_probability_by_tercile": stop_ratio_rows,
        "matched_season_stop_frequency_by_month": reference_stop_month.sort("entry_month").to_dicts(),
        "threshold_selection": "No stop level or threshold was selected or changed; fixed 50-point distance is descriptive only."
    }
    regime_rows = []
    for feature, label, cuts in [("atr20_bps", "atr_regime", atr_cuts), ("efficiency_20", "efficiency_regime", er_cuts)]:
        base_rows = reference.with_columns(
            pl.when(pl.col(feature) <= cuts[0]).then(pl.lit("low"))
            .when(pl.col(feature) <= cuts[1]).then(pl.lit("mid")).otherwise(pl.lit("high")).alias("regime"))
        current_rows = y2026.rename({label: "regime"})
        for source_name, frame in [("reference_2018_2025", base_rows), ("2026", current_rows)]:
            for row in summarise(frame, "regime"):
                regime_rows.append({"feature": feature, "source_period": source_name, **row})
    regimes = pl.DataFrame(regime_rows, infer_schema_length=None).sort("feature", "source_period", "regime")
    regimes.write_csv(REPORT / "regime_comparison.csv")
    ks_psi = {}
    for feature in ("atr20_bps", "efficiency_20", "prior_range_atr20", "channel_width_50_bps"):
        ref_vals = reference[feature].drop_nulls().to_list()
        cur_vals = y2026[feature].drop_nulls().to_list()
        ks = ks_2samp(ref_vals, cur_vals, alternative="two-sided", method="auto")
        psi_value = compute_psi(pl.Series("reference", ref_vals), pl.Series("current", cur_vals), n_bins=10).psi
        ks_psi[feature] = {"reference_n": len(ref_vals), "current_n": len(cur_vals),
                           "ks_statistic": float(ks.statistic), "ks_pvalue": float(ks.pvalue),
                           "psi_ml4t_diagnostic": float(psi_value)}

    # Retain month and day event groupings. News links only annotate a same-month association.
    event_rows = event_months(y2026)
    event_pnl = {str(row["entry_month"]): row for row in event_rows}
    top = top_concentration(y2026)
    worst = (y2026.sort("pnl").select("entry_time", "direction", "exit_reason", "bars_held", "pnl").head(10)
             .with_columns(pl.col("entry_time").dt.convert_time_zone("America/Chicago").dt.strftime("%Y-%m-%d %H:%M %Z").alias("entry_time"))
             .to_dicts())
    ledger_hashes = {}
    for year in range(2018, 2027):
        for filename in ("evaluation_trades.csv", "trades.csv", "fills.csv"):
            artifact = LEDGERS / str(year) / "native_full_tick_cost" / filename
            ledger_hashes[artifact.relative_to(PACKAGE).as_posix()] = sha256(artifact)
    zero_ledger = LEDGERS / "2026/native_zero_cost/evaluation_trades.csv"
    ledger_hashes[zero_ledger.relative_to(PACKAGE).as_posix()] = sha256(zero_ledger)
    metrics = {
        "analysis_classification": "EXPLORATORY retrospective historical review; NOT_APPROVED",
        "observation_cutoff_utc_inclusive": CUTOFF.isoformat(),
        "frozen_strategy_changed": False, "backtest_rerun": False, "holdout_accessed": False,
        "selected_or_optimized_any_rule": False,
        "corrective_audit": {
            "native_exit_order_type_source": "fills.csv odd row indices; paired by native trade row, timestamp-checked against trades.csv and joined to evaluation_trades.csv on (entry_time, exit_time, direction)",
            "native_fill_pairs_2026": 238, "evaluation_trade_one_to_one_join_2026": 238,
            "RTH_timezone": "America/Chicago with DST", "RTH_minutes_inclusive_exclusive": [510, 900],
            "complete_30m_feature_release": "bar_start + 30 minutes; backward as-of with release <= entry",
            "feature_release_violations": 0,
            "strategy_or_holdout_scope": "No trading rerun, no strategy change, no holdout access, no live orders",
            "ledger_input_sha256": ledger_hashes,
        },
        "accounting": {"2026_trades": y2026.height, "zero_cost_pnl_usd": float(zero_2026["pnl"].sum()),
                       "full_tick_costed_gross_before_commission_usd": float(y2026["gross_pnl"].sum()),
                       "full_tick_net_pnl_usd": float(y2026["pnl"].sum()),
                       "zero_cost_to_full_tick_net_difference_usd": float(zero_2026["pnl"].sum() - y2026["pnl"].sum()),
                       "commissions_usd": float(y2026["fees"].sum()),
                       "sum_of_total_slippage_cost_usd": float(y2026["total_slippage_cost"].sum()),
                       "entry_costed_gross_minus_net_usd": float((y2026["gross_pnl"] - y2026["pnl"]).sum()),
                       "paired_scenario_reconciliation": {
                           "entry_side_pairs": paired.height,
                           "same_exit_timestamp_pairs": int((paired["exit_time"] == paired["zero_cost_exit_time"]).sum()),
                           "costed_gross_minus_zero_cost_net_usd": float(paired["gross_delta_vs_zero_cost"].sum()),
                           "commission_usd": float(y2026["fees"].sum()),
                           "recorded_slippage_cost_usd": float(y2026["total_slippage_cost"].sum()),
                           "simple_recorded_cost_sum_usd": float(y2026["fees"].sum() + y2026["total_slippage_cost"].sum()),
                           "zero_cost_to_full_tick_net_difference_usd": float(zero_2026["pnl"].sum() - y2026["pnl"].sum()),
                           "simple_cost_sum_less_observed_net_difference_usd": float(y2026["fees"].sum() + y2026["total_slippage_cost"].sum() - (zero_2026["pnl"].sum() - y2026["pnl"].sum())),
                           "by_exit_fill_type": pair_delta_by_exit_type,
                           "note": "Separate scenario ledgers are paired by entry time and side. Recorded fill cost fields do not sum to the scenario PnL difference because exits and modeled fills are path-dependent; do not treat that residual as a pure cost estimate."
                       },
                       "win_rate": float((y2026["pnl"] > 0).mean()),
                       "winning_trades": int((y2026["pnl"] > 0).sum()),
                       "losing_trades": int((y2026["pnl"] < 0).sum()),
                       "average_winner_usd": float(y2026.filter(pl.col("pnl") > 0)["pnl"].mean()),
                       "average_loser_usd": float(y2026.filter(pl.col("pnl") < 0)["pnl"].mean()),
                       "median_net_trade_usd": float(y2026["pnl"].median()),
                       "mean_bars_held": float(y2026["bars_held"].mean()),
                       "median_bars_held": float(y2026["bars_held"].median()),
                       "profit_factor": float(y2026.filter(pl.col("pnl") > 0)["pnl"].sum() / -y2026.filter(pl.col("pnl") < 0)["pnl"].sum()),
                       "daily_cashflow_drawdown": daily_drawdown(y2026),
                       "top_trade_concentration": top,
                       "native_exit_fill_summary": breakdowns["exit_class"],
                       "native_exit_fill_monthly_pnl": monthly.select("month", "stop_trades", "stop_net_usd", "market_net_usd").to_dicts(),
                       "side_breakdown": breakdowns["side"], "exit_reason_raw_breakdown": breakdowns["exit_reason_raw"],
                       "exit_fill_order_type_breakdown": breakdowns["exit_fill_order_type"],
                       "stop_vs_market_breakdown": breakdowns["exit_class"], "hold_bars_breakdown": breakdowns["hold_bars"],
                       "session_breakdown": breakdowns["session"], "side_by_exit": breakdowns["side_by_exit"],
                       "month_by_side": breakdowns["month_by_side"], "month_by_exit": breakdowns["month_by_exit"],
                       "worst_10_trades": worst},
        "matched_prior_seasons": prior_summary,
        "features": {"entry_context_source_field": "volatility_proxy", "entry_context_join_rows": context_join.height,
                     "entry_context_nulls_after_join": context_join["volatility_proxy"].null_count(),
                     "entry_context_interpretation": "prior 50-bar channel range proxy, not standalone volatility",
                     "entry_to_channel_distance_points": {"median": float(y2026["breakout_distance_points"].median()),
                                                          "median_atr20": float(y2026["breakout_distance_atr20"].median()),
                                                          "q10": float(y2026["breakout_distance_points"].quantile(0.10)),
                                                          "q90": float(y2026["breakout_distance_points"].quantile(0.90))},
                     "next_observed_open_move_points": {"mean": float(y2026["next_observed_open_move_points"].mean()),
                                                        "median": float(y2026["next_observed_open_move_points"].median()),
                                                        "median_atr20": float(y2026["next_observed_open_move_atr20"].median()),
                                                        "positive_fraction": float((y2026["next_observed_open_move_points"] > 0).mean())},
                     "ledger_excursions_points": {"median_mfe": float(y2026["ledger_mfe_points"].median()),
                                                  "median_mae": float(y2026["ledger_mae_points"].median()),
                                                  "nominal_50pt_stop_excursions": int(y2026["nominal_50pt_stop_excursion"].sum()),
                                                  "ohlc_stop_touched_inclusive_entry_exit": int(y2026["nominal_stop_touched_in_trade_path"].sum()),
                                                  "ohlc_stop_touch_rate": float(y2026["nominal_stop_touched_in_trade_path"].mean()),
        "touch_window_includes_entry_and_exit_minute_ohlc": True,
        "touch_minute_ordering_resolved": False,
                                                  "recorded_stop_exit_trades": int(y2026.filter(pl.col("exit_class") == "STOP").height),
                                                  "interpretation": "MFE/MAE are post-entry path outcomes. MAE threshold flags potential 50-point excursions; one-minute OHLC cannot establish intraminute ordering or exact stop execution."},
                     "trailing_252_atr_regime": summarise(y2026.drop_nulls("atr_past252_regime"), "atr_past252_regime"),
                     "reference_2018_2025_tercile_cutpoints": {"atr20_bps": list(atr_cuts), "efficiency_20": list(er_cuts)},
                     "fixed_50_point_stop_analysis": stop_ratio_analysis,
                     "distribution_tests": ks_psi,
                     "regime_breakdown": regimes.to_dicts(), "engine": "ml4t.engineer.compute_features ATR(20) plus causal Polars features"},
        "event_month_pnl": event_pnl,
        "underlying_proxy_monthly_context": market_monthly.to_dicts(),
        "external_context": [
            {"period": "2026-01", "source": "Cboe Index Insights: January 2026", "url": "https://www.cboe.com/insights/posts/index-insights-january-2026/", "role": "dated market context only; no causal claim"},
            {"period": "2026-02", "source": "Nasdaq Global Indexes: February 2026 Scorecard", "url": "https://www.nasdaq.com/articles/global-indexes/index-monthly-scorecard-february-2026", "role": "official search result return value only; page retrieval blocked"},
            {"period": "2026-04", "source": "Nasdaq Global Indexes: April 2026 Scorecard", "url": "https://www.nasdaq.com/articles/global-indexes/monthly-scorecard-april-2026", "role": "official search result return value only; page retrieval blocked"},
            {"period": "2026-05", "source": "Nasdaq Global Indexes: May 2026 Scorecard", "url": "https://www.nasdaq.com/articles/global-indexes/monthly-scorecard-may-2026", "role": "official search result return value only; page retrieval blocked"},
            {"period": "2026-06", "source": "Cboe Index Insights: June 2026", "url": "https://www.cboe.com/insights/posts/index-insights-june-2026/", "role": "dated market context only; no causal claim"}],
        "source": source_meta,
        "confidence_tiers": {"verified": ["trade counts, PnL, fees, months, sides, exits, and source-window identities from frozen files"],
                              "inference": ["intraday breakout horizon may interact with measured price path and 30m regime slices"],
                              "hypothesis": ["external macro narrative may coincide with monthly trade results; no causal attribution is identified"]},
        "limitations": ["BID-only CFD/index proxy, not CME NQ", "one-minute OHLC does not resolve intraminute event order",
                        "native engine's OCO is non-atomic", "annual runs reset account state", "yearly costed and zero-cost trade paths are not asserted to match row by row",
                        "conditional slices are observational and are not causal treatment effects", "trade-level MFE/MAE are outcomes and are not used as causal features",
                        "no day-cluster confidence intervals were computed", "historical trial ledger is incomplete for DSR"],
    }
    (REPORT / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str) + "\n")
    y2026.select("entry_time", "feature_available_at", "direction", "entry_price", "exit_time", "exit_price", "pnl", "exit_reason", "exit_fill_order_type", "exit_class", "session",
                 "bars_held", "atr20", "breakout_distance_points", "breakout_distance_atr20",
                 "stop_50pt_over_atr20",
                 "entry_minute_open_gap_points", "next_timestamp", "next_observed_open_move_points",
                 "next_observed_open_move_atr20", "ledger_mfe_points", "ledger_mae_points",
                 "ledger_mfe_atr20", "ledger_mae_atr20", "nominal_50pt_stop_excursion",
                 "nominal_stop_touched_in_trade_path", "first_nominal_stop_touch_time", "minute_bars_in_trade_path_inclusive",
                 "atr_past252_regime").write_csv(REPORT / "trade_event_attribution.csv")
    write_chart(monthly, regimes.filter(pl.col("source_period") == "2026"), daily, REPORT / "one_bar_2026_regime_diagnostics.png")
    (REPORT / "README.md").write_text(render_report(metrics, monthly, regimes, breakdowns))
    readme = PACKAGE / "README.md"
    original = readme.read_text()
    section = "\n## 2026 regime attribution\n\nSee [the historical 2026 regime report](reports/regime_2026/README.md) and its [machine-readable metrics](reports/regime_2026/metrics.json). This is an accounting and conditional-attribution review. It does not change the fixed strategy or its `NOT_APPROVED` status.\n"
    if "## 2026 regime attribution" not in original:
        readme.write_text(original.rstrip() + "\n" + section)
    refresh_package_manifest()


def render_report(metrics: dict, monthly: pl.DataFrame, regimes: pl.DataFrame,
                  breakdowns: dict[str, list[dict]]) -> str:
    a = metrics["accounting"]
    exit_counts = {row["exit_class"]: row["trades"] for row in breakdowns["exit_class"]}
    recorded_stops = exit_counts.get("STOP", 0)
    ohlc_touches = metrics["features"]["ledger_excursions_points"]["ohlc_stop_touched_inclusive_entry_exit"]
    lines = ["# 2026 outcome attribution for the fixed one-bar strategy", "",
             "**Review type:** historical descriptive review. **Decision:** the package remains `EXPLORATORY` and `NOT_APPROVED`. No strategy rule changed. The backtest did not run again.", "",
             "## Finding", "",
             f"The frozen 2026 ledger has {a['2026_trades']} trades. It lost **${a['full_tick_net_pnl_usd']:,.2f} net** with full-tick costs and **${a['zero_cost_pnl_usd']:,.2f} in the separate zero-cost run**. The loss is therefore present before costs. The full-tick result is ${a['zero_cost_to_full_tick_net_difference_usd']:,.2f} below the zero-cost result. The costed `gross_pnl` field is before commissions but already includes fill slippage; do not read it as zero-cost PnL.", "",
             f"The full-tick ledger charges ${a['commissions_usd']:,.2f} in commission and records ${a['sum_of_total_slippage_cost_usd']:,.2f} in slippage. Their simple sum is ${a['paired_scenario_reconciliation']['simple_recorded_cost_sum_usd']:,.2f}, which is ${a['paired_scenario_reconciliation']['simple_cost_sum_less_observed_net_difference_usd']:,.2f} above the observed $3,360 scenario PnL gap. There are {a['paired_scenario_reconciliation']['entry_side_pairs']} matching entry-side pairs and {a['paired_scenario_reconciliation']['same_exit_timestamp_pairs']} matching exit timestamps. The remaining difference is path-dependent and is not a pure slippage estimate.", "",
             f"The win rate was {a['win_rate']:.1%} with profit factor {a['profit_factor']:.3f}. Average winning trade was ${a['average_winner_usd']:,.2f}; average losing trade was ${a['average_loser_usd']:,.2f}.", "",
             f"Native exit fills show {recorded_stops} protective STOP exits and {exit_counts.get('MARKET', 0)} scheduled MARKET exits. STOP exits lost ${next(r['net_pnl_usd'] for r in breakdowns['exit_class'] if r['exit_class'] == 'STOP'):,.2f}; MARKET exits gained ${next(r['net_pnl_usd'] for r in breakdowns['exit_class'] if r['exit_class'] == 'MARKET'):,.2f}. The market-exit trades were profitable as a group. The loss came from stop losses that outweighed those gains, plus monthly variation and modeled costs. All raw trade-ledger exit reasons say `signal`, so this split comes from native `fills.csv` order types. Source bars show {ohlc_touches} entry-path 1-minute OHLC touches of the nominal 50-point stop level. Intraminute order and stop gap behavior remain unresolved.", "",
             f"The entry-to-next-minute-open move, signed in the trade direction, had a ${metrics['features']['next_observed_open_move_points']['mean']:.2f} mean and a {metrics['features']['next_observed_open_move_points']['positive_fraction']:.1%} positive share. This immediate follow-through measure is descriptive only. The full-trade payoff remained negative.", "",
             "## Monthly attribution", "",
             "| Month | Trades | Full-tick net | Zero-cost net | STOP count / share | STOP net | MARKET net | 2018–25 same-month STOP share |",
             "|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in monthly.to_dicts():
        lines.append(f"| {row['month']} | {row['trades']} | ${row['costed_net_usd']:,.2f} | ${row['zero_cost_net_usd']:,.2f} | {row['stop_trades']} ({row['stop_share_pct']:.1%}) | ${row['stop_net_usd']:,.2f} | ${row['market_net_usd']:,.2f} | {row['reference_stop_trades']}/{row['reference_trades']} ({row['reference_stop_share_pct']:.1%}) |")
    lines += ["", "## Side, exits, hold time, and session", ""]
    lines += [f"- **Side:** `{row['direction']}`: {row['trades']} trades, net ${row['net_pnl_usd']:,.2f}, win rate {row['win_rate']:.1%}." for row in breakdowns["side"]]
    lines += [f"- **Exit:** `{row['exit_class']}`: {row['trades']} trades, net ${row['net_pnl_usd']:,.2f}, win rate {row['win_rate']:.1%}. The trade ledger writes `signal` for both stop and scheduled market exits. This table classifies from native fill order type." for row in breakdowns["exit_class"]]
    lines += [f"- **Session:** `{row['session']}`: {row['trades']} trades, net ${row['net_pnl_usd']:,.2f}, win rate {row['win_rate']:.1%}." for row in breakdowns["session"]]
    lines += [f"- Holding time: median {a['median_bars_held']:.0f} source minutes; mean {a['mean_bars_held']:.1f} source minutes. Full distribution is grouped by `bars_held` in `metrics.json`.",
              f"- Cash-flow drawdown: {a['daily_cashflow_drawdown']['max_drawdown_usd_from_running_cashflow_peak']}.",
              f"- Best/worst trade concentration: worst 10 sum ${a['top_trade_concentration']['worst_10_sum_usd']:,.2f}; best 10 sum ${a['top_trade_concentration']['best_10_sum_usd']:,.2f}.", "",
              "## Prior same-season comparison", "",
              f"The matched Jan 1–Jul 14 slices from 2018–2025 contain {metrics['matched_prior_seasons']['matched_2018_2025_n']:,} trades and net ${metrics['matched_prior_seasons']['matched_2018_2025_net_pnl_usd']:,.2f}. The average was ${metrics['matched_prior_seasons']['matched_2018_2025_mean_per_trade_usd']:,.2f} per trade. Annual summaries are in `metrics.json`. The 2026 outcome differs from the earlier same-season aggregate, but the comparison does not control for every execution or market structure change.", "",
              "Matched prior seasons averaged about 230 trades per partial year. The 2026 count of 238 was similar. The main difference was realized payoff: 2026 net per trade was -$59.53 versus +$59.16 for the 2018–2025 matched sample.", "",
              "## Fixed 50-point stop and pre-entry ATR", "",
              f"The unchanged 50-point stop represents $1,000 per illustrative contract at $20 per point. The full-year 2018 median entry price was {metrics['features']['fixed_50_point_stop_analysis']['reference_2018_full_year_median_entry_price']:,.1f}; 50 points equaled {metrics['features']['fixed_50_point_stop_analysis']['reference_2018_full_year_stop_bps_of_median_price']:.1f} bp of price. In 2026, median entry price was {metrics['features']['fixed_50_point_stop_analysis']['current_2026_median_entry_price']:,.1f}; the same stop equaled {metrics['features']['fixed_50_point_stop_analysis']['current_stop_bps_of_median_price']:.1f} bp. For matched Jan–Jul 14 trades, pre-entry ATR(20) medians were {metrics['features']['fixed_50_point_stop_analysis']['reference_median_pre_entry_atr20_points']:.1f} points for 2018–2025 and {metrics['features']['fixed_50_point_stop_analysis']['current_median_pre_entry_atr20_points']:.1f} for 2026.", "",
              "The table below compares native STOP probability across terciles of 50 / pre-entry ATR(20), using 2018–2025 matched-season cutpoints. This is a descriptive diagnostic. It does not select or change a stop threshold. The 2026 sample has no trades in the high-ratio tercile.", "",
              "| Period | 50 / ATR(20) tercile | Trades | Median ratio | STOP probability | Net PnL |",
              "|---|---|---:|---:|---:|---:|"]
    for row in metrics["features"]["fixed_50_point_stop_analysis"]["stop_probability_by_tercile"]:
        lines.append(f"| {row['period']} | {row['stop_ratio_tercile']} | {row['trades']} | {row['median_stop_50pt_over_atr20']:.2f} | {row['stop_probability']:.1%} | ${row['net_pnl_usd']:,.2f} |")
    lines += ["", "## Pre-entry regime diagnostics", "",
              "Each 30-minute feature is released at the next 30-minute open. The as-of backward join only accepts `feature_available_at <= entry_time`. ATR(20) comes from `ml4t.engineer.compute_features`; the 20-bar efficiency ratio, prior range / ATR, and 50-bar channel width use sorted Polars expressions. Regime cutpoints are the 2018–2025 matched-season terciles. They describe slices. They are not proposed trading filters.", "",
              "`entry_context.csv` contains `volatility_proxy`. A complete 2026 time join succeeded. The source code records that field as the channel `range_proxy`; this report does not call it realized volatility. ATR and channel width offer separate measures.", "",
              "| Feature | Period | Regime | Trades | Net PnL | Win rate |",
              "|---|---|---|---:|---:|---:|"]
    for row in regimes.sort("feature", "source_period", "regime").to_dicts():
        lines.append(f"| {row['feature']} | {row['source_period']} | {row['regime']} | {row['trades']} | ${row['net_pnl_usd']:,.2f} | {row['win_rate']:.1%} |")
    lines += ["", "The KS and PSI results in `metrics.json` compare feature distributions. They are drift diagnostics, not tests that the features caused the PnL change. Daily proxy trend and realized volatility are shown in the chart.", "",
              "## Source and macro context", "",
              "The source is Dukascopy USATECH.IDX/USD BID one-minute data, an index/CFD proxy. It is not a dated CME NQ contract. The source manifest ends on 2026-07-14. The source-feature calculation excludes later observations.", "",
              "The chart reports daily trend and realized volatility for the same local index proxy. These features do not represent a separate official Nasdaq index or a causal macro variable. Monthly values are in `metrics.json`.", "",
              "For context only, March coincided with geopolitical shocks, April and May with a broad market rebound, and June with technology leadership rotation. These are hypotheses about the surrounding period, not identified causes of trade PnL. The market-proxy monthly returns and trade PnL do not establish a causal link.", "",
              "Cboe described January 2026 as broadening beyond mega-cap technology, with Russell 2000 up 5.31% and MGTN down 0.8% ([Cboe](https://www.cboe.com/insights/posts/index-insights-january-2026/)). Cboe described June leadership rotation, with Russell 2000 up 3.6%, MGTN down 9.2%, and VIX rising from 15.3 to 16.5 ([Cboe](https://www.cboe.com/insights/posts/index-insights-june-2026/)). Nasdaq's official scorecard search results report NDX down 2.3% in February, up 15.6% in April, and up 10.5% in May ([February](https://www.nasdaq.com/articles/global-indexes/index-monthly-scorecard-february-2026), [April](https://www.nasdaq.com/articles/global-indexes/monthly-scorecard-april-2026), [May](https://www.nasdaq.com/articles/global-indexes/monthly-scorecard-may-2026)). Nasdaq page retrieval was blocked, so this report uses only those monthly return values and does not repeat driver claims from the pages. Strategy PnL was positive in April and May and negative in March and June. These public summaries do not match individual trade entry times. Any event/month link to PnL is a hypothesis only.", "",
              "## Confidence and limits", "",
              "- **Verified:** ledger identities, counts, PnL, modeled costs, monthly and conditional sums, entry-side/exit categories, entry timestamps, source cutoff, and matched same-season sample.",
              "- **Inference:** the fixed 50-point stop was smaller relative to 2026 ATR(20) and price than in earlier observations. Higher stop incidence is consistent with that change. This does not establish causality.",
              "- **Hypothesis:** monthly macro narratives may coincide with trade outcomes. Broad index returns do not explain intraday proxy PnL without event-time matching.",
              "- One-minute OHLC touches include the entry and exit minute. The data cannot determine event order inside those minutes. There were 51 nominal 50-point touches and 44 native STOP exits. Stop gaps can exceed nominal risk. The engine's OCO is non-atomic. Annual runs reset account state. The run does not verify CME contract mapping, bid/ask execution, or certified costs.",
              "- No day-cluster confidence intervals were computed. The historical trial ledger is incomplete for Deflated Sharpe Ratio. The report does not use MFE or MAE as pre-entry features.", "",
              "## Reproduction", "",
              "```bash", "UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp/mplconfig XDG_CACHE_HOME=/tmp/cache uv run python promote/one_bar_nq_30m/scripts/analyze_regime_2026.py", "UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp/mplconfig XDG_CACHE_HOME=/tmp/cache uv run python -m pytest promote/one_bar_nq_30m/tests/test_regime_2026.py", "```", "",
              "See `analysis_manifest.json` for frozen groups and feature definitions. The frozen reports, original run folders, and the post-2026-07-14 holdout were not changed or read.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
