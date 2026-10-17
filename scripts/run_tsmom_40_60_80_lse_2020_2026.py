"""Test 40/60/80-session time-series momentum on 2020-2026 data.

Primary data:
- Binance USD-M 1h canonical ml4t-data archive for BTCUSDT/ETHUSDT/HYPEUSDT.
- Fresh London Strategic Edge 1m provider exports for DAX and NIKKEI225.

DAX is fail-closed for the primary verdict if its upstream mixed-scale data
cannot pass a continuity/coverage gate. A causal repair is still reported as a
supplemental sensitivity.

All simulations use ml4t.backtest.Engine with NEXT_BAR OPEN execution.
"""

from __future__ import annotations

import glob
import json
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import exchange_calendars as xcals
import numpy as np
import polars as pl

from ml4t.engineer import compute_features
from ml4t.backtest import BacktestConfig, DataFeed, Engine, Strategy
from ml4t.backtest.config import CommissionType, ShareType, SlippageType

STORE_ROOT = Path("/home/quant/dev/quant/ml4t-data/.data/store")
LSE_FRESH_ROOT = Path("/tmp/lse-tsmom-20261007-v2")
CATALOG_PATH = STORE_ROOT / ".catalog/research-dataset-catalog.json"

START = pl.datetime(2020, 1, 1, 0, 0, 0, time_zone="UTC")
END = pl.datetime(2026, 10, 1, 0, 0, 0, time_zone="UTC")
INITIAL_CASH = 100_000.0
LOOKBACKS = (40, 60, 80)


@dataclass(frozen=True)
class Instrument:
    symbol: str
    kind: str
    calendar: str
    periods_per_year: int
    commission_rate: float
    slippage_rate: float
    primary_eligible: bool


INSTRUMENTS = {
    "BTCUSDT": Instrument("BTCUSDT", "crypto", "crypto", 365, 0.00045, 0.00015, True),
    "ETHUSDT": Instrument("ETHUSDT", "crypto", "crypto", 365, 0.00045, 0.00015, True),
    "HYPEUSDT": Instrument("HYPEUSDT", "crypto", "crypto", 365, 0.00045, 0.00015, True),
    "DAX_LSE": Instrument("DAX_LSE", "index", "XETRA", 252, 0.00020, 0.00010, False),
    "NIKKEI225_LSE": Instrument("NIKKEI225_LSE", "index", "JPX", 245, 0.00020, 0.00010, True),
}


def jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, (np.integer, np.floating)):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def sign_expr(col: str) -> pl.Expr:
    return (
        pl.when(pl.col(col) > 0)
        .then(pl.lit(1.0))
        .when(pl.col(col) < 0)
        .then(pl.lit(-1.0))
        .otherwise(pl.lit(0.0))
    )


def canonical_catalog_evidence() -> dict[str, Any]:
    catalog = json.loads(CATALOG_PATH.read_text())
    keys = {
        "crypto_futures_ohlcv_1h_BINANCE_UM_PERP",
        "index_minute_DAX",
        "index_minute_NIKKEI225",
    }
    entries = {}
    for entry in catalog.get("entries", []):
        if entry.get("dataset_key") in keys:
            entries[entry["dataset_key"]] = {
                "authority": entry.get("authority"),
                "qualification": entry.get("qualification"),
                "provider": entry.get("provider"),
                "source_symbol": entry.get("source_symbol"),
                "consumer_identity": entry.get("consumer_identity"),
                "entry_identity": entry.get("entry_identity"),
                "capabilities": entry.get("capabilities"),
            }
    return {
        "catalog_identity": catalog.get("catalog_identity"),
        "entries": entries,
    }


def load_crypto_daily(symbol: str) -> tuple[pl.DataFrame, dict[str, Any]]:
    base = STORE_ROOT / "crypto_futures_ohlcv_1h_BINANCE_UM_PERP" / f"symbol={symbol}"
    files = glob.glob(str(base / "year=202[0-6]" / "month=*" / "data.parquet"))
    raw = (
        pl.scan_parquet(files)
        .filter((pl.col("timestamp") >= START) & (pl.col("timestamp") < END))
        .select(["timestamp", "open", "high", "low", "close", "volume"])
        .sort("timestamp")
        .collect()
        .with_columns(pl.col("timestamp").dt.cast_time_unit("us"))
    )
    daily_all = (
        raw.group_by_dynamic("timestamp", every="1d", closed="left", label="left")
        .agg(
            pl.col("open").first().alias("open"),
            pl.col("high").max().alias("high"),
            pl.col("low").min().alias("low"),
            pl.col("close").last().alias("close"),
            pl.col("volume").sum().alias("volume"),
            pl.len().alias("source_rows"),
        )
        .sort("timestamp")
    )
    daily = (
        daily_all.filter(pl.col("source_rows") == 24)
        .with_columns(pl.lit(symbol).alias("symbol"))
        .select(["timestamp", "symbol", "open", "high", "low", "close", "volume", "source_rows"])
    )
    audit = {
        "source": str(base),
        "raw_rows": raw.height,
        "raw_start": str(raw["timestamp"].min()),
        "raw_end": str(raw["timestamp"].max()),
        "daily_rows": daily.height,
        "dropped_partial_days": daily_all.height - daily.height,
        "daily_start": str(daily["timestamp"].min()),
        "daily_end": str(daily["timestamp"].max()),
        "duplicates": int(raw.select(pl.col("timestamp").is_duplicated().sum()).item()),
        "ohlc_violations": int(
            raw.filter(
                (pl.col("high") < pl.col("low"))
                | (pl.col("close") > pl.col("high"))
                | (pl.col("close") < pl.col("low"))
            ).height
        ),
        "status": "PASS",
    }
    return daily, audit


def official_dates(calendar: str) -> set[date]:
    cal = xcals.get_calendar(calendar)
    sessions = cal.sessions_in_range("2020-01-01", "2026-09-30")
    return {ts.date() for ts in sessions.to_pydatetime()}


def load_lse_raw(key: str) -> pl.DataFrame:
    base = LSE_FRESH_ROOT / key
    files = glob.glob(str(base / "year=202[0-6]" / "month=*" / "data.parquet"))
    if not files:
        raise FileNotFoundError(base)
    return (
        pl.scan_parquet(files)
        .filter((pl.col("timestamp") >= START) & (pl.col("timestamp") < END))
        .select(["timestamp", "open", "high", "low", "close", "volume"])
        .sort("timestamp")
        .collect()
        .with_columns(pl.col("timestamp").dt.cast_time_unit("us"))
    )


def local_cash_rows(raw: pl.DataFrame, *, tz: str, market: str) -> pl.DataFrame:
    local = pl.col("timestamp").dt.convert_time_zone(tz)
    frame = raw.with_columns(
        local.dt.date().alias("session_date"),
        (local.dt.hour().cast(pl.Int32) * 60 + local.dt.minute().cast(pl.Int32)).alias("minute_of_day"),
    )
    if market == "DAX":
        frame = frame.filter((pl.col("minute_of_day") >= 540) & (pl.col("minute_of_day") < 1050))
    elif market == "NIKKEI":
        pre_expansion = pl.col("session_date") < pl.date(2024, 11, 5)
        close_minute = pl.when(pre_expansion).then(pl.lit(900)).otherwise(pl.lit(930))
        frame = frame.filter(
            (pl.col("minute_of_day") >= 540)
            & (pl.col("minute_of_day") < close_minute)
            & ~((pl.col("minute_of_day") >= 690) & (pl.col("minute_of_day") < 750))
        )
    else:
        raise ValueError(market)
    return frame.sort("timestamp")


def daily_from_clean_rows(
    rows: pl.DataFrame,
    *,
    symbol: str,
    calendar: str,
) -> tuple[pl.DataFrame, dict[str, Any]]:
    expected = official_dates(calendar)
    rows = rows.filter(pl.col("session_date").is_in(list(expected)))
    daily = (
        rows.group_by("session_date")
        .agg(
            pl.col("open").sort_by("timestamp").first().alias("open"),
            pl.col("high").max().alias("high"),
            pl.col("low").min().alias("low"),
            pl.col("close").sort_by("timestamp").last().alias("close"),
            pl.col("volume").sum().alias("volume"),
            pl.len().alias("source_rows"),
        )
        .sort("session_date")
        .with_columns(
            pl.col("session_date")
            .cast(pl.Datetime("us"))
            .dt.replace_time_zone("UTC")
            .alias("timestamp"),
            pl.lit(symbol).alias("symbol"),
        )
        .select(["timestamp", "symbol", "open", "high", "low", "close", "volume", "source_rows", "session_date"])
    )
    observed = set(daily["session_date"].to_list())
    missing = sorted(expected - observed)
    ret = daily.with_columns((pl.col("close") / pl.col("close").shift(1) - 1).alias("ret"))
    audit = {
        "expected_sessions": len(expected),
        "observed_sessions": daily.height,
        "missing_sessions": len(missing),
        "missing_sample": [str(x) for x in missing[:12]],
        "min_source_rows": int(daily["source_rows"].min()) if daily.height else 0,
        "median_source_rows": float(daily["source_rows"].median()) if daily.height else 0.0,
        "min_daily_return": float(ret["ret"].min()) if daily.height > 1 else None,
        "max_daily_return": float(ret["ret"].max()) if daily.height > 1 else None,
    }
    return daily.drop("session_date"), audit


def load_nikkei_daily() -> tuple[pl.DataFrame, dict[str, Any]]:
    raw = load_lse_raw("index_minute_NIKKEI225")
    cash = local_cash_rows(raw, tz="Asia/Tokyo", market="NIKKEI")
    daily, audit = daily_from_clean_rows(cash, symbol="NIKKEI225_LSE", calendar="XTKS")
    audit.update(
        {
            "source": str(LSE_FRESH_ROOT / "index_minute_NIKKEI225"),
            "raw_rows": raw.height,
            "raw_start": str(raw["timestamp"].min()),
            "raw_end": str(raw["timestamp"].max()),
            "duplicates": int(raw.select(pl.col("timestamp").is_duplicated().sum()).item()),
            "ohlc_violations": int(
                raw.filter(
                    (pl.col("high") < pl.col("low"))
                    | (pl.col("close") > pl.col("high"))
                    | (pl.col("close") < pl.col("low"))
                ).height
            ),
        }
    )
    missing_ratio = audit["missing_sessions"] / audit["expected_sessions"]
    audit["status"] = "PASS" if missing_ratio <= 0.01 else "FAIL"
    return daily, audit


def load_dax_repaired_daily() -> tuple[pl.DataFrame, dict[str, Any]]:
    raw = load_lse_raw("index_minute_DAX")
    cash = local_cash_rows(raw, tz="Europe/Berlin", market="DAX")
    expected = official_dates("XETR")
    cash = cash.filter(pl.col("session_date").is_in(list(expected))).sort("timestamp")

    records: list[dict[str, Any]] = []
    previous_close: float | None = None
    zero_days = 0
    for day in cash.partition_by("session_date", maintain_order=True):
        session_date = day["session_date"][0]
        if previous_close is None:
            chosen = day
        else:
            chosen = day.filter(
                (pl.col("close") >= previous_close * 0.5)
                & (pl.col("close") <= previous_close * 1.5)
            )
        if chosen.height == 0:
            zero_days += 1
            continue
        close = float(chosen["close"][-1])
        records.append(
            {
                "session_date": session_date,
                "open": float(chosen["open"][0]),
                "high": float(chosen["high"].max()),
                "low": float(chosen["low"].min()),
                "close": close,
                "volume": float(chosen["volume"].sum()),
                "source_rows": chosen.height,
            }
        )
        previous_close = close

    repaired_all = pl.DataFrame(records).sort("session_date")
    usable = repaired_all.filter(pl.col("source_rows") >= 30)
    usable = (
        usable.with_columns(
            pl.col("session_date")
            .cast(pl.Datetime("us"))
            .dt.replace_time_zone("UTC")
            .alias("timestamp"),
            pl.lit("DAX_LSE").alias("symbol"),
        )
        .select(["timestamp", "symbol", "open", "high", "low", "close", "volume", "source_rows", "session_date"])
    )
    observed_usable = set(usable["session_date"].to_list())
    missing_or_sparse = len(expected - observed_usable)
    ret = usable.with_columns((pl.col("close") / pl.col("close").shift(1) - 1).alias("ret"))

    raw_daily = (
        cash.group_by("session_date")
        .agg(pl.col("close").sort_by("timestamp").last().alias("close"))
        .sort("session_date")
        .with_columns((pl.col("close") / pl.col("close").shift(1) - 1).alias("ret"))
    )
    extreme_raw = int(raw_daily.filter(pl.col("ret").abs() > 0.5).height)
    missing_ratio = missing_or_sparse / len(expected)
    audit = {
        "source": str(LSE_FRESH_ROOT / "index_minute_DAX"),
        "raw_rows": raw.height,
        "raw_start": str(raw["timestamp"].min()),
        "raw_end": str(raw["timestamp"].max()),
        "duplicates": int(raw.select(pl.col("timestamp").is_duplicated().sum()).item()),
        "ohlc_violations": int(
            raw.filter(
                (pl.col("high") < pl.col("low"))
                | (pl.col("close") > pl.col("high"))
                | (pl.col("close") < pl.col("low"))
            ).height
        ),
        "raw_daily_returns_over_50pct": extreme_raw,
        "repair_rule": "cash-session row close must remain within 0.5x..1.5x prior accepted close; keep days with >=30 accepted rows",
        "expected_sessions": len(expected),
        "repaired_nonzero_days": repaired_all.height,
        "usable_sessions": usable.height,
        "zero_candidate_days": zero_days,
        "missing_or_sparse_sessions": missing_or_sparse,
        "missing_or_sparse_ratio": missing_ratio,
        "median_accepted_rows": float(repaired_all["source_rows"].median()) if repaired_all.height else 0.0,
        "min_repaired_return": float(ret["ret"].min()) if usable.height > 1 else None,
        "max_repaired_return": float(ret["ret"].max()) if usable.height > 1 else None,
        "status": "FAIL_PRIMARY_DATA_GATE" if missing_ratio > 0.02 or extreme_raw > 0 else "PASS",
    }
    return usable.drop("session_date"), audit


def engineer_features(inst: Instrument, daily: pl.DataFrame) -> pl.DataFrame:
    base = daily.drop(["symbol", "source_rows"]).with_columns(
        pl.col("close").pct_change().alias("returns")
    )
    specs: list[dict[str, Any]] = [
        {"name": "roc", "output": f"roc_{lb}", "params": {"period": lb}}
        for lb in LOOKBACKS
    ]
    specs.append(
        {
            "name": "realized_volatility",
            "output": "rv20",
            "params": {
                "period": 20,
                "annualize": True,
                "trading_periods": inst.periods_per_year,
            },
        }
    )
    feat = compute_features(base, specs).with_columns(pl.lit(inst.symbol).alias("symbol"))
    feat = feat.with_columns(
        pl.when(pl.col("rv20") > 0)
        .then((0.20 / pl.col("rv20")).clip(0.0, 1.0))
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .alias("vol_scalar")
    )
    for lb in LOOKBACKS:
        feat = feat.with_columns(
            sign_expr(f"roc_{lb}").alias(f"sig_raw_{lb}")
        ).with_columns(
            (pl.col(f"sig_raw_{lb}") * pl.col("vol_scalar")).alias(f"sig_vt_{lb}")
        )
    feat = feat.with_columns(
        (
            (pl.col("sig_raw_40") + pl.col("sig_raw_60") + pl.col("sig_raw_80"))
            / 3.0
        ).alias("sig_ensemble_raw")
    ).with_columns(
        (pl.col("sig_ensemble_raw") * pl.col("vol_scalar")).alias("sig_ensemble_vt")
    )
    return feat.sort("timestamp")


class SignalTargetStrategy(Strategy):
    def __init__(self, signal_col: str):
        super().__init__()
        self.signal_col = signal_col

    def on_data(self, timestamp, data, context, broker) -> None:
        for symbol, bar in data.items():
            signal = bar["signals"].get(self.signal_col)
            if signal is None:
                continue
            target = float(signal)
            if not math.isfinite(target):
                continue
            broker.order_target_percent(symbol, max(-1.0, min(1.0, target)))


def metric_value(metrics: dict[str, Any], *names: str, default: float = 0.0) -> float:
    for name in names:
        value = metrics.get(name)
        if value is not None:
            return float(value)
    return default


def run_backtest(
    inst: Instrument,
    feat: pl.DataFrame,
    signal_col: str,
    *,
    cost_multiplier: float = 1.0,
) -> dict[str, Any]:
    frame = feat.select(
        ["timestamp", "symbol", "open", "high", "low", "close", "volume", signal_col]
    ).drop_nulls([signal_col])
    prices = frame.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
    signals = frame.select(["timestamp", "symbol", signal_col])

    config = BacktestConfig(
        initial_cash=INITIAL_CASH,
        allow_short_selling=True,
        allow_leverage=True,
        share_type=ShareType.FRACTIONAL,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=inst.commission_rate * cost_multiplier,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=inst.slippage_rate * cost_multiplier,
        calendar=inst.calendar,
    )
    result = Engine(
        DataFeed(
            prices_df=prices,
            signals_df=signals,
            entity_col="symbol",
            timestamp_col="timestamp",
        ),
        SignalTargetStrategy(signal_col),
        config,
    ).run()
    metrics = result.metrics
    return {
        "bars": frame.height,
        "start": str(frame["timestamp"].min()),
        "end": str(frame["timestamp"].max()),
        "total_return": metric_value(metrics, "total_return", "total_return_pct"),
        "sharpe": metric_value(metrics, "sharpe"),
        "max_drawdown": metric_value(metrics, "max_drawdown", "max_drawdown_pct"),
        "num_trades": int(metric_value(metrics, "num_trades")),
        "win_rate": metric_value(metrics, "win_rate"),
        "profit_factor": metric_value(metrics, "profit_factor"),
        "total_costs": metric_value(metrics, "total_costs"),
        "execution_mode": str(config.execution_mode),
        "execution_price": str(config.execution_price),
        "calendar": inst.calendar,
        "commission_rate_per_side": inst.commission_rate * cost_multiplier,
        "slippage_rate_per_side": inst.slippage_rate * cost_multiplier,
    }


def run_asset(inst: Instrument, daily: pl.DataFrame) -> tuple[dict[str, Any], dict[str, Any]]:
    feat = engineer_features(inst, daily)
    results: dict[str, Any] = {}
    for lb in LOOKBACKS:
        results[f"roc_{lb}_raw"] = run_backtest(inst, feat, f"sig_raw_{lb}")
        results[f"roc_{lb}_vol20"] = run_backtest(inst, feat, f"sig_vt_{lb}")
    results["ensemble_raw"] = run_backtest(inst, feat, "sig_ensemble_raw")
    results["ensemble_vol20"] = run_backtest(inst, feat, "sig_ensemble_vt")
    results["ensemble_vol20_cost_stress_2x"] = run_backtest(
        inst, feat, "sig_ensemble_vt", cost_multiplier=2.0
    )
    feature_audit = {
        "rv20_median": float(feat["rv20"].drop_nulls().median()),
        "rv20_p10": float(feat["rv20"].drop_nulls().quantile(0.10)),
        "rv20_p90": float(feat["rv20"].drop_nulls().quantile(0.90)),
        "vol_scalar_median": float(feat["vol_scalar"].drop_nulls().median()),
    }
    return results, feature_audit


def plateau_summary(results: dict[str, Any]) -> dict[str, Any]:
    raw = [results[f"roc_{lb}_raw"] for lb in LOOKBACKS]
    vt = [results[f"roc_{lb}_vol20"] for lb in LOOKBACKS]
    return {
        "raw_positive_count": sum(x["total_return"] > 0 for x in raw),
        "vol20_positive_count": sum(x["total_return"] > 0 for x in vt),
        "raw_sharpes": {str(lb): results[f"roc_{lb}_raw"]["sharpe"] for lb in LOOKBACKS},
        "vol20_sharpes": {str(lb): results[f"roc_{lb}_vol20"]["sharpe"] for lb in LOOKBACKS},
        "raw_returns": {str(lb): results[f"roc_{lb}_raw"]["total_return"] for lb in LOOKBACKS},
        "vol20_returns": {str(lb): results[f"roc_{lb}_vol20"]["total_return"] for lb in LOOKBACKS},
        "raw_all_three_positive": all(x["total_return"] > 0 for x in raw),
        "vol20_all_three_positive": all(x["total_return"] > 0 for x in vt),
    }


def main() -> None:
    data: dict[str, pl.DataFrame] = {}
    audits: dict[str, Any] = {}

    for sym in ("BTCUSDT", "ETHUSDT", "HYPEUSDT"):
        data[sym], audits[sym] = load_crypto_daily(sym)
    data["NIKKEI225_LSE"], audits["NIKKEI225_LSE"] = load_nikkei_daily()
    data["DAX_LSE"], audits["DAX_LSE"] = load_dax_repaired_daily()

    results: dict[str, Any] = {}
    feature_audits: dict[str, Any] = {}
    plateau: dict[str, Any] = {}
    for symbol, inst in INSTRUMENTS.items():
        asset_results, feat_audit = run_asset(inst, data[symbol])
        results[symbol] = asset_results
        feature_audits[symbol] = feat_audit
        plateau[symbol] = plateau_summary(asset_results)

    primary_symbols = [
        symbol
        for symbol, inst in INSTRUMENTS.items()
        if inst.primary_eligible and audits[symbol]["status"] == "PASS"
    ]
    primary = {
        "symbols": primary_symbols,
        "raw_all3_positive_markets": sum(
            plateau[s]["raw_all_three_positive"] for s in primary_symbols
        ),
        "vol20_all3_positive_markets": sum(
            plateau[s]["vol20_all_three_positive"] for s in primary_symbols
        ),
        "roc60_raw_positive_markets": sum(
            results[s]["roc_60_raw"]["total_return"] > 0 for s in primary_symbols
        ),
        "roc60_vol20_positive_markets": sum(
            results[s]["roc_60_vol20"]["total_return"] > 0 for s in primary_symbols
        ),
        "ensemble_vol20_positive_markets": sum(
            results[s]["ensemble_vol20"]["total_return"] > 0 for s in primary_symbols
        ),
        "ensemble_vol20_2x_cost_positive_markets": sum(
            results[s]["ensemble_vol20_cost_stress_2x"]["total_return"] > 0
            for s in primary_symbols
        ),
    }

    output = {
        "schema": "tsmom_40_60_80_lse_2020_2026/v1",
        "session_id": "tsmom_40_60_80_lse_2020_2026",
        "classification": "EXPLORATORY",
        "approval_status": "NOT_APPROVED",
        "window": {
            "requested_start": "2020-01-01",
            "end_inclusive": "2026-09-30",
            "hype_available_from": "2025-05-30",
        },
        "method": {
            "lookbacks_sessions": list(LOOKBACKS),
            "volatility_target": 0.20,
            "volatility_feature": "ml4t.engineer realized_volatility(period=20, annualized)",
            "backtest_engine": "ml4t.backtest.Engine",
            "execution": "NEXT_BAR OPEN",
            "winner_selection": False,
            "crypto_funding_included": False,
        },
        "catalog": canonical_catalog_evidence(),
        "data_audit": audits,
        "feature_audit": feature_audits,
        "results": results,
        "plateau": plateau,
        "primary_summary": primary,
        "limitations": [
            "This is development/exploratory evidence, not a fresh final holdout.",
            "HYPEUSDT did not exist in 2020; its test begins after listing and has a much shorter sample.",
            "Crypto funding is excluded because no HYPE funding dataset exists in the canonical local catalog.",
            "LSE DAX DE30/EUR fresh exports contain an interleaved ~600-900 price stream and fail the raw data gate.",
            "DAX results use a causal continuity repair and days with at least 30 accepted cash-session rows; DAX is supplemental and excluded from the primary verdict.",
            "LSE index price series are research proxies, not executable contract-level futures; index costs are exploratory placeholders.",
            "The session YAML was written before the run but was not committed/frozen in Git before execution, so do not describe this as formal preregistration.",
        ],
    }
    print("RESULT_JSON_BEGIN")
    print(json.dumps(jsonable(output), sort_keys=True))
    print("RESULT_JSON_END")


if __name__ == "__main__":
    main()
