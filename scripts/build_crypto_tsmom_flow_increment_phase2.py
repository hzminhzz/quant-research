"""Build frozen v4 TSMOM and taker-flow features and forward-return labels."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import yaml
from ml4t.engineer import __version__ as engineer_version
from ml4t.engineer import compute_features, feature_catalog

ROOT = Path(__file__).resolve().parents[1]
SESSION_ID = "crypto_tsmom_flow_increment_20261008_v4"
SESSION_DIR = ROOT / "run_log/research_sessions" / SESSION_ID
CONFIG_PATH = ROOT / "config/research_sessions" / f"{SESSION_ID}.yaml"
FROZEN_PATH = SESSION_DIR / "frozen_spec.json"
GATE_PATH = SESSION_DIR / "data_gate_report.json"
FEATURE_PATH = ROOT / "data/features" / f"{SESSION_ID}.parquet"
LABEL_PATH = ROOT / "data/labels" / f"{SESSION_ID}.parquet"
REPORT_PATH = SESSION_DIR / "phase2_feature_report.json"
MOMENTUM_HOURS = (24, 72, 168)


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def utc_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_inputs() -> tuple[dict[str, Any], dict[str, Any], datetime, datetime, list[pl.LazyFrame], list[dict[str, Any]]]:
    config: dict[str, Any] = yaml.safe_load(CONFIG_PATH.read_text())
    frozen: dict[str, Any] = json.loads(FROZEN_PATH.read_text())
    gate: dict[str, Any] = json.loads(GATE_PATH.read_text())
    if config["session_id"] != SESSION_ID or frozen["classification"] != "EXPLORATORY":
        raise ValueError("Session identity or classification differs from the frozen study.")
    if sha256(CONFIG_PATH) != frozen["identity"]["config"]["sha256"]:
        raise ValueError("Config does not match its frozen identity.")
    if gate["status"] != "PASS" or gate["frozen_spec_sha256"] != frozen["frozen_sha256"]:
        raise ValueError("Phase 1 data gate does not pass for this frozen specification.")

    evaluation = config["evaluation"]
    start, end = utc_datetime(evaluation["development_start"]), utc_datetime(evaluation["development_end"])
    if start >= end or end != utc_datetime(evaluation["holdout_start"]):
        raise ValueError("Development and holdout boundaries are inconsistent.")

    frozen_data = {item["path"]: item for item in frozen["identity"]["data"]}
    price_inputs = [item for item in config["data"] if item["role"] == "prices"]
    symbols = [item["symbol"] for item in price_inputs]
    if set(symbols) != {"BTCUSDT", "ETHUSDT", "SOLUSDT"} or len(set(symbols)) != len(symbols):
        raise ValueError("Price inputs do not match the frozen three-symbol universe.")

    required = {"timestamp", "open", "high", "low", "close", "volume", "quote_volume", "taker_buy_quote_volume"}
    scans, records = [], []
    for item in price_inputs:
        path = ROOT / item["path"]
        expected = frozen_data.get(item["path"])
        if expected is None or not path.is_file() or sha256(path) != expected["sha256"]:
            raise ValueError(f"Price input identity mismatch: {item['path']}")
        missing = required - set(pl.scan_parquet(path).collect_schema().names())
        if missing:
            raise ValueError(f"{item['path']} is missing columns: {sorted(missing)}")
        scans.append(
            pl.scan_parquet(path)
            .filter((pl.col("timestamp") >= start) & (pl.col("timestamp") < end))
            .select(sorted(required - {"timestamp"}) + ["timestamp"])
            .with_columns(pl.lit(item["symbol"]).alias("symbol"))
        )
        records.append({"symbol": item["symbol"], "path": item["path"], "sha256": expected["sha256"]})
    if "roc" not in feature_catalog.list():
        raise ValueError("ml4t.engineer feature catalog does not register ROC.")
    return config, frozen, start, end, scans, records


def validate(
    full: pl.DataFrame,
    symbols: list[str],
    expected_rows: int,
    horizons: tuple[int, ...],
    expected_zero_timestamp: datetime,
) -> dict[str, Any]:
    ordered = full.sort(["symbol", "timestamp"])
    coverage = ordered.group_by("symbol").agg(
        pl.len().alias("rows"), pl.col("timestamp").min().alias("first"), pl.col("timestamp").max().alias("last")
    )
    if full.height != expected_rows * len(symbols) or coverage.height != len(symbols):
        raise AssertionError("Input row counts differ from the passing Phase 1 data gate.")
    if ordered.select(pl.struct(["symbol", "timestamp"]).n_unique()).item() != full.height:
        raise AssertionError("Duplicate symbol/timestamp rows found.")
    gap_count = ordered.with_columns(pl.col("timestamp").diff().over("symbol").alias("_gap"))
    gap_count = gap_count.filter(pl.col("_gap").is_not_null() & (pl.col("_gap") != pl.duration(hours=1))).height
    if gap_count:
        raise AssertionError(f"Found {gap_count} non-hourly transitions.")

    feature_nulls = {f"roc_{h}h_pct": full.get_column(f"roc_{h}h_pct").null_count() for h in MOMENTUM_HOURS}
    expected_feature_nulls = {f"roc_{h}h_pct": h * len(symbols) for h in MOMENTUM_HOURS}
    if feature_nulls != expected_feature_nulls:
        raise AssertionError(f"Unexpected momentum warmup boundaries: {feature_nulls}")
    signal_nulls = {f"tsmom_{h}h_signal": full.get_column(f"tsmom_{h}h_signal").null_count() for h in MOMENTUM_HOURS}
    expected_signal_nulls = {f"tsmom_{h}h_signal": 168 * len(symbols) for h in MOMENTUM_HOURS}
    if signal_nulls != expected_signal_nulls:
        raise AssertionError(f"Signals violate the common 168-hour warmup: {signal_nulls}")


    zero_denominator = ordered.filter(pl.col("quote_volume") <= 0).select("symbol", "timestamp")
    zero_counts = zero_denominator.group_by("symbol").len()
    if zero_denominator.height != len(symbols) or zero_counts.height != len(symbols):
        raise AssertionError("Flow denominator exclusions differ from the frozen data gate.")
    if any(count != 1 for count in zero_counts.get_column("len")):
        raise AssertionError("Each symbol must have one flow denominator exclusion.")
    if zero_denominator.get_column("timestamp").unique().to_list() != [expected_zero_timestamp]:
        raise AssertionError("Flow denominator exclusion is at an unexpected timestamp.")
    flow_values = ordered.get_column("flow_imbalance").drop_nulls()
    flow_min, flow_max = flow_values.min(), flow_values.max()
    if flow_min is None or flow_max is None or not (-1.0 - 1e-12 <= flow_min <= flow_max <= 1.0 + 1e-12):
        raise AssertionError("Signed flow imbalance falls outside [-1, 1].")
    expected_flow_nulls = len(symbols)
    if ordered.get_column("flow_imbalance").null_count() != expected_flow_nulls:
        raise AssertionError("Flow null count differs from the frozen zero-denominator policy.")
    expected_pair_nulls = (168 + 1) * len(symbols)
    flow_score_nulls = {}
    for column in ("tsmom_72h_flow_baseline_score", "tsmom_72h_flow_augmented_score"):
        flow_score_nulls[column] = ordered.get_column(column).null_count()
        if flow_score_nulls[column] != expected_pair_nulls:
            raise AssertionError(f"Unexpected shared flow-comparison boundaries in {column}.")

    label_nulls = {f"forward_return_{h}h": full.get_column(f"forward_return_{h}h").null_count() for h in horizons}
    if label_nulls != {f"forward_return_{h}h": h * len(symbols) for h in horizons}:
        raise AssertionError(f"Unexpected forward-label boundaries: {label_nulls}")

    for symbol in symbols:
        rows = ordered.filter(pl.col("symbol") == symbol)
        close, open_ = rows.get_column("close"), rows.get_column("open")
        if rows.height != expected_rows:
            raise AssertionError(f"Unexpected row count for {symbol}.")
        for index in (168, 1_000, rows.height - 100):
            for h in MOMENTUM_HOURS:
                expected = 100.0 * (close[index] - close[index - h]) / close[index - h]
                actual = rows.get_column(f"roc_{h}h_pct")[index]
                if abs(actual - expected) > 1e-10 * max(1.0, abs(expected)):
                    raise AssertionError(f"ROC formula mismatch for {symbol}, {h}h.")
            for h in horizons:
                expected = close[index + h] / open_[index + 1] - 1.0
                actual = rows.get_column(f"forward_return_{h}h")[index]
                if abs(actual - expected) > 1e-12:
                    raise AssertionError(f"Forward-return formula mismatch for {symbol}, {h}h.")
    return {
        "rows": full.height,
        "per_symbol": {row["symbol"]: row["rows"] for row in coverage.iter_rows(named=True)},
        "momentum_nulls": feature_nulls,
        "signal_nulls": signal_nulls,
        "flow_invalid_rows": zero_denominator.height,
        "flow_invalid_timestamp": expected_zero_timestamp.isoformat(),
        "flow_score_nulls": flow_score_nulls,
        "forward_return_nulls": label_nulls,
        "hourly_grid_contiguous": True,
        "duplicate_symbol_timestamp_rows": 0,
    }


def build() -> dict[str, Any]:
    config, frozen, start, end, scans, input_records = load_inputs()
    feature_specs: list[str | dict[str, Any]] = [
        {"name": "roc", "output": f"roc_{h}h_pct", "params": {"period": h}}
        for h in MOMENTUM_HOURS
    ]
    panel = pl.concat(scans).sort(["symbol", "timestamp"])
    computed = compute_features(panel, feature_specs, group_col="symbol", timestamp_col="timestamp")
    if not isinstance(computed, pl.LazyFrame):
        raise TypeError("Lazy input must produce a lazy feature plan.")

    safe_volume = pl.when(pl.col("quote_volume") > 0).then(pl.col("quote_volume")).otherwise(None)
    computed = computed.with_columns(
        ((2.0 * pl.col("taker_buy_quote_volume") - pl.col("quote_volume")) / safe_volume).alias("flow_imbalance")
    )
    warmup_complete = pl.col("roc_168h_pct").is_not_null()
    for h in MOMENTUM_HOURS:
        roc = pl.col(f"roc_{h}h_pct")
        computed = computed.with_columns(
            pl.when(warmup_complete & (roc > 0))
            .then(1)
            .when(warmup_complete & (roc < 0))
            .then(-1)
            .when(warmup_complete)
            .then(0)
            .otherwise(None)
            .cast(pl.Int8)
            .alias(f"tsmom_{h}h_signal")
        )

    flow_valid = pl.col("flow_imbalance").is_not_null() & pl.col("tsmom_72h_signal").is_not_null()
    computed = computed.with_columns(
        pl.when(flow_valid).then(pl.col("tsmom_72h_signal")).otherwise(None).alias("tsmom_72h_flow_baseline_score"),
        pl.when(flow_valid)
        .then(pl.col("tsmom_72h_signal") + pl.col("flow_imbalance"))
        .otherwise(None)
        .alias("tsmom_72h_flow_augmented_score"),
    )

    flow_spec = config["evaluation"]["flow_feature"]
    horizons = tuple(flow_spec["forward_return_horizons_hours"])
    if horizons != (1, 4, 24, 72) or flow_spec["primary_horizon_hours"] != 1:
        raise ValueError("Forward-return horizons differ from the frozen Phase 2 contract.")
    # The library label API has one price column for both endpoints. The frozen
    # target uses open[i + 1] and close[i + H], so use exact vectorized shifts.
    labels = []
    for h in horizons:
        next_time = pl.col("timestamp").shift(-1).over("symbol")
        future_time = pl.col("timestamp").shift(-h).over("symbol")
        valid = (next_time == pl.col("timestamp") + pl.duration(hours=1)) & (
            future_time == pl.col("timestamp") + pl.duration(hours=h)
        )
        labels.append(
            pl.when(valid)
            .then(pl.col("close").shift(-h).over("symbol") / pl.col("open").shift(-1).over("symbol") - 1.0)
            .otherwise(None)
            .alias(f"forward_return_{h}h")
        )
    full = computed.with_columns(labels).collect()
    symbols = [item["symbol"] for item in config["data"] if item["role"] == "prices"]
    expected_rows = int(json.loads(GATE_PATH.read_text())["checks"]["hourly_prices_and_flow"]["hourly_rows_per_symbol"])
    zero_timestamp = utc_datetime(flow_spec["zero_denominator_observations"]["timestamp_utc"])
    checks = validate(full, symbols, expected_rows, horizons, zero_timestamp)

    for symbol in symbols:
        coverage = full.filter(pl.col("symbol") == symbol).select(
            pl.col("timestamp").min().alias("first"),
            pl.col("timestamp").max().alias("last"),
        ).row(0)
        if coverage != (start, end - timedelta(hours=1)):
            raise AssertionError(f"Timestamp bounds differ from the development window for {symbol}.")
    checks["timestamp_bounds_verified"] = True

    feature_columns = [
        "timestamp", "symbol", *(f"roc_{h}h_pct" for h in MOMENTUM_HOURS),
        *(f"tsmom_{h}h_signal" for h in MOMENTUM_HOURS), "flow_imbalance",
        "tsmom_72h_flow_baseline_score", "tsmom_72h_flow_augmented_score",
    ]
    label_columns = ["timestamp", "symbol", *(f"forward_return_{h}h" for h in horizons)]
    features, label_frame = full.select(feature_columns), full.select(label_columns)
    FEATURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    LABEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    features.write_parquet(FEATURE_PATH)
    label_frame.write_parquet(LABEL_PATH)
    feature_readback, label_readback = pl.read_parquet(FEATURE_PATH), pl.read_parquet(LABEL_PATH)
    if (
        feature_readback.height != full.height
        or label_readback.height != full.height
        or feature_readback.columns != feature_columns
        or label_readback.columns != label_columns
    ):
        raise AssertionError("Written artifact rows or schemas differ from the source panel.")
    checks["artifact_readback_schema_match"] = True

    report = {
        "session_id": SESSION_ID,
        "phase": "Phase 2: Feature Engineering",
        "status": "PASS",
        "classification": frozen["classification"],
        "approval_status": frozen["approval_status"],
        "frozen_spec_sha256": frozen["frozen_sha256"],
        "config_sha256": sha256(CONFIG_PATH),
        "builder_sha256": sha256(Path(__file__).resolve()),
        "ml4t_engineer_version": engineer_version,
        "polars_version": pl.__version__,
        "development_window_utc": {"start_inclusive": start.isoformat(), "end_exclusive": end.isoformat()},
        "holdout_values_read": False,
        "input_data": input_records,
        "checks": checks | {"roc_formula_samples_match": True, "forward_return_formula_samples_match": True, "artifact_readback_rows_match": True, "diagnostics_run": False, "backtests_run": False},
        "feature_artifact": {
            "path": str(FEATURE_PATH.relative_to(ROOT)),
            "sha256": sha256(FEATURE_PATH),
            "rows": feature_readback.height,
            "columns": feature_columns,
        },
        "label_artifact": {
            "path": str(LABEL_PATH.relative_to(ROOT)),
            "sha256": sha256(LABEL_PATH),
            "rows": label_readback.height,
            "columns": label_columns,
            "definition": "close[i + H] / open[i + 1] - 1; contiguous hourly bars required; development boundary only",
        },
        "feature_definitions": {
            "roc": "ml4t.engineer ROC in percent, grouped by symbol; 24h, 72h, and 168h",
            "flow_imbalance": "(2 * taker_buy_quote_volume - quote_volume) / quote_volume; null when denominator <= 0",
            "flow_scores": "sign(72h return), and that score plus flow imbalance; paired timestamps only; diagnostic, not orders",
        },
        "label_api_note": "fixed_time_horizon_labels uses one price column for both endpoints; vectorized Polars shifts preserve the frozen open-to-close label definition.",
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


if __name__ == "__main__":
    result = build()
    print(json.dumps({"status": result["status"], "rows": result["checks"]["rows"], "feature_artifact": result["feature_artifact"]["path"], "label_artifact": result["label_artifact"]["path"], "report": str(REPORT_PATH.relative_to(ROOT))}, indent=2))
