"""Independent bar-fill oracle. This audit does not simulate a portfolio."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import re
from zoneinfo import ZoneInfo

import polars as pl
from ml4t.backtest.analytics import EquityCurve, TradeAnalyzer
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SID = "tokyo_fix_program3_ohlcv_execution_20261011_v1"
SEAL = date(2026, 9, 1)
PIP = 0.01


def price_decimal(value: float) -> Decimal:
    """Remove source float dust at the declared eight-decimal price resolution."""
    return Decimal(str(value)).quantize(Decimal("0.00000001"))


def strict_cross(side: str, high: float, low: float, limit: float, buffer_pips: float) -> bool:
    """Test strict crossing. An exact touch does not establish eligibility."""
    if side == "sell":
        return price_decimal(high) > price_decimal(limit) + Decimal(str(buffer_pips)) / 100
    if side == "buy":
        return price_decimal(low) < price_decimal(limit) - Decimal(str(buffer_pips)) / 100
    raise ValueError("Unknown order side")


def expected_limit_fill(bars: list[dict], limit: float, ttl: int, buffer_pips: float) -> dict | None:
    """Return the first eligible source bar after 09:55, within the frozen TTL."""
    if ttl not in (1, 3):
        raise ValueError("TTL must be 1 or 3 minutes")
    eligible = sorted((b for b in bars if 596 <= b["minute"] <= 595 + ttl), key=lambda b: b["timestamp"])
    for bar in eligible:
        if strict_cross("sell", float(bar["high"]), float(bar["low"]), limit, buffer_pips):
            return bar
    return None


def dollar_pnl(entry: float, exit_price: float, cost_pips: float = 0.0) -> float:
    """Convert one fixed USD 10000 short's JPY PnL at its exit quote."""
    if exit_price <= 0:
        raise ValueError("Exit quote must be positive")
    return 10000.0 * (entry - exit_price - cost_pips * PIP) / exit_price


def close(a: float, b: float, message: str, tolerance: float = 1e-7):
    if not math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=tolerance):
        raise AssertionError(f"{message}: {a} != {b}")


def parse_variant(name: str) -> tuple[float, int, float] | None:
    match = re.fullmatch(r"limit_o(0|0p5|1)_t(1|3)_b(0|0p5)", name)
    if not match:
        if name in ("market_gotobi", "market_ordinary"):
            return None
        raise AssertionError(f"Unknown trial: {name}")
    return float(match[1].replace("p", ".")), int(match[2]), float(match[3].replace("p", "."))


def load_original_bars() -> pl.DataFrame:
    files = [ROOT / "data/processed/tokyo_alpha_map_program1_v1" / f"USDJPY_03_12_JST_{year}.parquet" for year in range(2020, 2027)]
    return (pl.scan_parquet(files)
        .with_columns(pl.col("timestamp").dt.convert_time_zone("Asia/Tokyo").alias("jst"))
        .filter(pl.col("jst") < datetime(2026, 9, 1, tzinfo=ZoneInfo("Asia/Tokyo")))
        .with_columns(pl.col("jst").dt.date().alias("session"),
            (pl.col("jst").dt.hour().cast(pl.Int32) * 60 + pl.col("jst").dt.minute().cast(pl.Int32)).alias("minute"))
        .filter(pl.col("minute").is_between(510, 630))
        .select("timestamp", "session", "minute", "open", "high", "low", "close")
        .sort("timestamp").collect())


def verify_run(name: str, orders: pl.DataFrame, trades: pl.DataFrame, panel: pl.DataFrame,
               original: pl.DataFrame) -> dict:
    variant = parse_variant(name)
    cohort = "ordinary" if name == "market_ordinary" else "gotobi"
    sessions = panel.filter(pl.col(cohort))["session"].to_list()
    if any(s >= SEAL for s in sessions):
        raise AssertionError("Holdout session in trial")
    bars_by_day = {g["session"][0]: g.to_dicts() for g in original.partition_by("session")}
    trade_by_day = {r["session"]: r for r in trades.to_dicts()}
    if len(trade_by_day) != trades.height:
        raise AssertionError("Duplicate closed trades")
    if set(trade_by_day) - set(sessions):
        raise AssertionError("Trade outside calendar cohort")
    expected_count = 0
    for session in sessions:
        bars = bars_by_day[session]
        by_minute = {r["minute"]: r for r in bars}
        ref = float(by_minute[594]["close"])
        if variant is None:
            fill = by_minute[596]
            price = float(fill["open"])
        else:
            offset, ttl, buffer = variant
            price = float(price_decimal(ref) + Decimal(str(offset)) / 100)
            fill = expected_limit_fill(bars, price, ttl, buffer)
        day_orders = orders.filter(pl.col("session") == session)
        entries = day_orders.filter(pl.col("role") == "entry")
        if entries.height != 1:
            raise AssertionError(f"{name} {session}: entry order count {entries.height}")
        entry = entries.row(0, named=True)
        submitted = entry["submitted_at"].astimezone(ZoneInfo("Asia/Tokyo"))
        if submitted.hour * 60 + submitted.minute != 595:
            raise AssertionError("Entry submission must be 09:55")
        if fill is None:
            if session in trade_by_day or entry["fill_at"] is not None:
                raise AssertionError("Phantom fill without strict crossing")
            if str(entry["status"]).lower().split(".")[-1] not in ("cancelled", "canceled", "expired"):
                raise AssertionError("Missed order remains active")
            if day_orders.filter(pl.col("role") == "exit").height:
                raise AssertionError("Exit exists without entry fill")
            continue
        expected_count += 1
        if session not in trade_by_day:
            raise AssertionError("Eligible signal omitted from native trades")
        trade = trade_by_day[session]
        if entry["fill_at"] != fill["timestamp"]:
            raise AssertionError("Native fill is not first eligible source bar")
        if entry["fill_at"] <= entry["submitted_at"]:
            raise AssertionError("Same-bar fill")
        if str(entry["status"]).lower().split(".")[-1] != "filled":
            raise AssertionError("Entry fill status is inconsistent")
        close(entry["price"], price, "Entry price")
        close(abs(entry["quantity"]), 10000.0, "Fixed notional")
        if variant:
            close(entry["limit"], price, "Submitted limit")
        exits = day_orders.filter(pl.col("role") == "exit")
        if exits.height != 1:
            raise AssertionError("Position needs exactly one exit")
        exit_order = exits.row(0, named=True)
        exit_bar = by_minute[610]
        if exit_order["fill_at"] != exit_bar["timestamp"]:
            raise AssertionError("Exit is not 10:10 source open")
        if exit_order["submitted_at"] != exit_bar["timestamp"] - timedelta(minutes=1):
            raise AssertionError("Exit submission is not 10:09")
        if str(exit_order["status"]).lower().split(".")[-1] != "filled":
            raise AssertionError("Exit fill status is inconsistent")
        close(abs(exit_order["quantity"]), abs(entry["quantity"]), "Close quantity")
        close(exit_order["price"], exit_bar["open"], "Exit price")
        close(trade["entry"], price, "Trade entry")
        close(trade["exit"], exit_bar["open"], "Trade exit")
        if trade["entry_time"] != fill["timestamp"] or trade["exit_time"] != exit_bar["timestamp"]:
            raise AssertionError("Trade timestamps disagree with source")
        close(trade["pnl_jpy"], 10000.0 * (price - exit_bar["open"]), "JPY PnL")
        close(trade["gross_usd"], dollar_pnl(price, exit_bar["open"]), "USD conversion")
        for cost in (0.8, 1, 1.4, 2):
            field = f"net_usd_c{cost}"
            if field in trade:
                close(trade[field], dollar_pnl(price, exit_bar["open"], cost), "Cost-adjusted USD conversion")
    if expected_count != trades.height or orders.height != len(sessions) + expected_count:
        raise AssertionError("Order or trade accounting mismatch")
    return {"trial": name, "status": "PASS", "signals_checked": len(sessions),
            "trades_checked": expected_count, "fills_checked": expected_count * 2,
            "missed_checked": len(sessions) - expected_count}


def verify_analytics(path: Path, trades: pl.DataFrame, result: dict, original: pl.DataFrame,
                     panel: pl.DataFrame, calendar: pl.DataFrame) -> dict:
    """Reconcile USD cash flows and verified library metrics with raw source marks."""
    checks = []
    raw_marks = original.filter(pl.col("minute").is_between(594, 630)
        & pl.col("session").is_in(panel["session"].implode())).sort("timestamp")
    for scenario in result["scenarios"]:
        cost = scenario["cost_pips"]
        col = f"net_usd_c{cost}"
        actual = pl.read_parquet(path / f"daily_cost{cost}.parquet")
        expected = (calendar.select("session").join(trades.select("session", pl.col(col).alias("pnl")),
            on="session", how="left", validate="1:1").with_columns(pl.col("pnl").fill_null(0))
            .with_columns((10000 + pl.col("pnl").cum_sum()).alias("equity")))
        if not expected.equals(actual.select(expected.columns)):
            raise AssertionError("Daily cash flow, equity or flat-bank-date accounting mismatch")
        timestamps = [datetime.combine(calendar["session"][0] - timedelta(days=1), datetime.min.time(), ZoneInfo("Asia/Tokyo"))]
        timestamps += [datetime.combine(s, datetime.min.time(), ZoneInfo("Asia/Tokyo")) for s in expected["session"]]
        equity = EquityCurve(timestamps, [10000.0] + expected["equity"].to_list(), periods_per_year_override=252)
        analyzer = TradeAnalyzer([SimpleNamespace(pnl=p, pnl_percent=p / 10000, status="closed") for p in trades[col]])
        for field, value in [("daily_sharpe", equity.sharpe), ("max_closed_drawdown_pct", equity.max_dd * 100),
                             ("return_pct", equity.total_return * 100), ("win_rate", analyzer.win_rate),
                             ("profit_factor", analyzer.profit_factor)]:
            if math.isfinite(value):
                close(scenario[field], value, f"Verified library metric {field}")
            elif scenario[field] is not None:
                raise AssertionError("Nonfinite metric should be explicitly unresolved")
        prior = expected.select("session", (pl.col("pnl").cum_sum().shift(1).fill_null(0)).alias("prior"))
        marks = raw_marks.join(prior, on="session", validate="m:1").join(trades.select("session", "entry", "entry_time", "exit_time", pl.col(col).alias("net")), on="session", how="left", validate="m:1")
        # Reconstruct marks from native executions. This is an accounting oracle, not an order simulator.
        values = []
        for row in marks.iter_rows(named=True):
            unrealized = 0.0
            if row["entry_time"] is not None:
                if row["timestamp"] >= row["exit_time"]:
                    unrealized = row["net"]
                elif row["timestamp"] >= row["entry_time"]:
                    unrealized = dollar_pnl(row["entry"], row["close"], cost)
            values.append(10000 + row["prior"] + unrealized)
        mtm = EquityCurve(marks["timestamp"].to_list(), values)
        close(scenario["minute_close_mtm_drawdown_pct"], mtm.max_dd * 100, "Native-fill source-close MTM drawdown")
        checks.append({"cost_pips": cost, "daily_points": expected.height, "source_mtm_points": marks.height,
                       "metric_status": "PASS", "closed_and_mtm_drawdown_separate": True})
    return {"trial": path.name, "status": "PASS", "scenarios": checks}


def verify_proxies(out: Path, original: pl.DataFrame) -> dict:
    """Verify endpoints, label timing and window completeness against source prices."""
    proxy = pl.read_parquet(out / "proxy_event_panel.parquet")
    grouped = {g["session"][0]: {r["minute"]: r for r in g.to_dicts()} for g in original.partition_by("session")}
    checked = 0
    for row in proxy.iter_rows(named=True):
        bars = grouped[row["session"]]
        if row["feature_bar"] != bars[594]["timestamp"] or row["available_at"] != bars[594]["timestamp"] + timedelta(minutes=1):
            raise AssertionError("Proxy available timestamp is not last completed minute")
        if row["first_fill_time"] <= row["available_at"]:
            raise AssertionError("Proxy fill uses unavailable feature")
        for field, start, gate in [("extension0830", 510, "proxy0830_complete"), ("extension0930", 570, "proxy0930_complete")]:
            if row[gate]:
                close(row[field], math.log(bars[594]["close"] / bars[start]["close"]), "Source proxy endpoint", 1e-10)
                checked += 1
        for end in (610, 630):
            if row[f"y{end}"] is not None:
                close(row[f"y{end}"], (bars[596]["open"] - bars[end]["open"]) / PIP, "Source future markout", 1e-7)
                if bars[596]["timestamp"] <= row["available_at"]:
                    raise AssertionError("Label entry precedes feature availability")
                checked += 1
    gates = pl.read_parquet(out / "window_gates.parquet")
    for label, start, end in [("execution", 594, 630), ("proxy0830", 510, 594), ("proxy0930", 570, 594), ("placebo", 565, 580)]:
        observed = original.filter(pl.col("minute").is_between(start, end)).group_by("session").agg(pl.len().alias("independent_observed"))
        comparison = gates.join(observed, on="session", how="left").with_columns(pl.col("independent_observed").fill_null(0))
        if comparison.filter(pl.col(f"{label}_observed") != pl.col("independent_observed")).height:
            raise AssertionError("Window gate missingness differs from original source")
        if comparison.filter(pl.col(f"{label}_complete") & (pl.col("independent_observed") != end - start + 1)).height:
            raise AssertionError("Incomplete minute window admitted")
    return {"status": "PASS", "proxy_rows": proxy.height, "source_endpoint_and_label_checks": checked,
            "window_gates_checked": gates.height * 4, "feature_information_last_bar": "09:54 close available09:55",
            "limitations": "No future mutation test on full runner; library causality mutation regression is in tests."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "run_log" / SID))
    args = parser.parse_args()
    out = Path(args.out)
    dest = out / "T3_oracle" / "result.json"
    if dest.exists():
        raise RuntimeError("Independent oracle artifact already exists")
    original = load_original_bars()
    panel = pl.read_parquet(out / "event_panel.parquet")
    if panel["session"].is_duplicated().any():
        raise AssertionError("Duplicate event panel session")
    execution = pl.scan_parquet(out / "execution_bars.parquet").select(
        "timestamp", "open", "high", "low", "close").collect()
    if execution["timestamp"].is_duplicated().any():
        raise AssertionError("Duplicate execution bar")
    source_compare = execution.join(original.select("timestamp", "open", "high", "low", "close"),
        on="timestamp", how="left", suffix="_original", validate="1:1")
    # The runner can include a wider feature window. Check all execution minutes independently.
    in_execution_window = source_compare.filter(
        pl.col("timestamp").dt.convert_time_zone("Asia/Tokyo").dt.strftime("%H:%M").is_between(pl.lit("09:54"), pl.lit("10:30")))
    if in_execution_window.filter(pl.any_horizontal([
        pl.col(f"{column}_original").is_null() | (pl.col(column) != pl.col(f"{column}_original"))
        for column in ("open", "high", "low", "close")])).height:
        raise AssertionError("Runner execution prices differ from original snapshot")
    results = []
    initial_results = []
    for path in sorted((out / "runs").iterdir()):
        if path.is_dir() and (path / "result.json").exists():
            try:
                audit = verify_run(path.name, pl.read_parquet(path / "orders.parquet"), pl.read_parquet(path / "trades.parquet"), panel, original)
                initial_results.append({"trial": path.name, "status": "PASS", "trades_checked": audit["trades_checked"]})
            except AssertionError as error:
                initial_results.append({"trial": path.name, "status": "REJECTED", "reason": str(error)})
    paths = {path.name: path for path in (out / "runs").iterdir() if path.is_dir()}
    corrected = out / "runs_corrected"
    if corrected.exists():
        paths = {path.name: path for path in corrected.iterdir() if path.is_dir()}
    calendar = pl.read_parquet(ROOT / "run_log/tokyo_fix_alpha_map_program1_20261010/execution_v1/calendar_event_registry.parquet").filter(pl.col("session") < SEAL).select("session").sort("session")
    analytics = []
    for path in sorted(paths.values(), key=lambda p: p.name):
        if path.is_dir() and (path / "result.json").exists():
            trades = pl.read_parquet(path / "trades.parquet")
            checked = verify_run(path.name, pl.read_parquet(path / "orders.parquet"), trades, panel, original)
            native_result = json.loads((path / "result.json").read_text())
            for field, expected in [("submitted", checked["signals_checked"]), ("filled", checked["trades_checked"]),
                                    ("missed", checked["missed_checked"]), ("cancelled", checked["missed_checked"])]:
                if native_result[field] != expected:
                    raise AssertionError(f"Reported {field} count differs from original-source oracle")
            close(native_result["native_quote_pnl_jpy"], trades["pnl_jpy"].sum(), "Native quote reconciliation", 1e-5)
            for scenario in native_result["scenarios"]:
                cost = scenario["cost_pips"]
                values = trades[f"net_usd_c{cost}"]
                close(scenario["net_usd"], values.sum(), "Reported net USD")
                close(scenario["per_fill_usd"], values.mean(), "Conditional per-fill expectancy")
                close(scenario["per_signal_usd"], values.sum() / checked["signals_checked"], "Per-signal expectancy")
            results.append(checked)
            analytics.append(verify_analytics(path, trades, native_result, original, panel, calendar))
    if len(results) != 14:
        raise AssertionError(f"Expected 14 native trials, found {len(results)}")
    result = {"status": "PASS", "source": "original immutable annual OHLCV snapshots",
              "holdout_read": False, "method": "Independent strict-cross, TTL, next-bar, exit-time and USD-conversion audit; no portfolio simulation", "results": results,
              "verifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "initial_preserved_run_audits": initial_results, "effective_runs": str(corrected if corrected.exists() else out / "runs"),
              "price_resolution": "Independent Decimal quantization1e-8 removes source float dust; strict decimal crossing, no exact touch admitted",
              "analytics": analytics, "proxies": verify_proxies(out, original),
              "remaining_limitations": ["Gate establishes hypothetical bar eligibility; executable broker quote/queue probability UNKNOWN", "MTM uses minute closes, not intrabar or tick path", "No new holdout evidence"]}
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
