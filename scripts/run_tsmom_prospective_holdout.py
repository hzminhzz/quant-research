"""Fail-closed prospective holdout runner for the frozen TSMOM candidate.

The runner refuses to compute holdout performance before the scheduled
checkpoint or if frozen strategy inputs drift.

Frozen candidate:
- equal average of sign(ROC40), sign(ROC60), sign(ROC80)
- 20% annualized realized-volatility target, capped at 1x gross
- NEXT_BAR OPEN execution
- no regime gate
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import exchange_calendars as xcals
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.run_tsmom_40_60_80_lse_2020_2026 as base
from ml4t.backtest import BacktestConfig, DataFeed, Engine
from ml4t.backtest.config import CommissionType, ShareType, SlippageType

STORE_ROOT = Path("/home/quant/dev/quant/ml4t-data/.data/store")
CATALOG_PATH = STORE_ROOT / ".catalog/research-dataset-catalog.json"

FREEZE_PATH = ROOT / "run_log/tsmom_40_60_80_lse_2020_2026/prospective_holdout_freeze.json"
EXPECTED_FREEZE_SHA256 = "6f8a2c823363e878532727fc796c95170426926cc6a910732d9cb8e34c5e3f78"
EXPECTED_BASE_SHA256 = "76cca6fe3ecb45a6702941fa985359e1d338682a0765ce68576ae543cd5781a9"
EXPECTED_CONFIG_SHA256 = "6784c4bd12607620da442214d61555747c7d9f468bb2b2b0b3ff33fac8187f75"

HOLDOUT_START = date(2026, 10, 8)
CHECKPOINTS = {
    90: date(2027, 1, 6),
    180: date(2027, 4, 6),
}
WARMUP_START = pl.datetime(2026, 4, 1, 0, 0, 0, time_zone="UTC")
PRIMARY = ("BTCUSDT", "ETHUSDT", "HYPEUSDT", "NIKKEI225_LSE")
SIGNAL_COL = "sig_ensemble_vt"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(status: str, reason: str, **extra: Any) -> None:
    payload = {"status": status, "reason": reason, **extra}
    print(json.dumps(payload, sort_keys=True))
    raise SystemExit(2)


def verify_freeze() -> dict[str, Any]:
    if not FREEZE_PATH.is_file():
        fail("BLOCKED_FREEZE_MISSING", str(FREEZE_PATH))
    if sha256(FREEZE_PATH) != EXPECTED_FREEZE_SHA256:
        fail(
            "BLOCKED_FREEZE_DRIFT",
            "Prospective freeze artifact changed after approval.",
            observed_sha256=sha256(FREEZE_PATH),
            expected_sha256=EXPECTED_FREEZE_SHA256,
        )

    strategy_path = ROOT / "scripts/run_tsmom_40_60_80_lse_2020_2026.py"
    config_path = ROOT / "config/research_sessions/tsmom_40_60_80_lse_2020_2026.yaml"
    if sha256(strategy_path) != EXPECTED_BASE_SHA256:
        fail("BLOCKED_STRATEGY_DRIFT", "Frozen strategy source hash changed.")
    if sha256(config_path) != EXPECTED_CONFIG_SHA256:
        fail("BLOCKED_CONFIG_DRIFT", "Frozen research config hash changed.")

    freeze = json.loads(FREEZE_PATH.read_text())
    if freeze["holdout"]["start_inclusive"] != "2026-10-08":
        fail("BLOCKED_FREEZE_DRIFT", "Holdout start changed.")
    if freeze["candidate"]["regime_gating"]:
        fail("BLOCKED_FREEZE_DRIFT", "Regime gating was enabled after freeze.")
    return freeze


def verify_catalog() -> dict[str, Any]:
    catalog = json.loads(CATALOG_PATH.read_text())
    entries = {e["dataset_key"]: e for e in catalog.get("entries", [])}

    crypto = entries.get("crypto_futures_ohlcv_1h_BINANCE_UM_PERP")
    nikkei = entries.get("index_minute_NIKKEI225")
    if not crypto or crypto.get("provider") != "binance" or crypto.get("authority") != "canonical":
        fail("BLOCKED_PROVIDER_DRIFT", "Canonical Binance USD-M dataset mapping changed.")
    if (
        not nikkei
        or nikkei.get("provider") != "london_strategic_edge"
        or nikkei.get("source_symbol") != "JP225/USD"
        or nikkei.get("authority") != "canonical"
    ):
        fail("BLOCKED_PROVIDER_DRIFT", "Canonical LSE Nikkei mapping changed.")
    return {
        "catalog_identity": catalog.get("catalog_identity"),
        "crypto_entry_identity": crypto.get("entry_identity"),
        "nikkei_entry_identity": nikkei.get("entry_identity"),
    }


def daterange(start: date, end_exclusive: date) -> list[date]:
    n = (end_exclusive - start).days
    return [start + timedelta(days=i) for i in range(n)]


def load_crypto_daily(symbol: str, end_exclusive: date) -> tuple[pl.DataFrame, dict[str, Any]]:
    base_dir = STORE_ROOT / "crypto_futures_ohlcv_1h_BINANCE_UM_PERP" / f"symbol={symbol}"
    files = glob.glob(str(base_dir / "year=*" / "month=*" / "data.parquet"))
    if not files:
        fail("WAITING_DATA", f"No canonical files for {symbol}.")

    end_expr = pl.datetime(
        end_exclusive.year, end_exclusive.month, end_exclusive.day, time_zone="UTC"
    )
    raw = (
        pl.scan_parquet(files)
        .filter((pl.col("timestamp") >= WARMUP_START) & (pl.col("timestamp") < end_expr))
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

    required_dates = set(daterange(HOLDOUT_START, end_exclusive))
    counts = {
        row["timestamp"].date(): int(row["source_rows"])
        for row in daily_all.select(["timestamp", "source_rows"]).iter_rows(named=True)
    }
    bad = sorted(d for d in required_dates if counts.get(d) != 24)
    if bad:
        fail(
            "WAITING_DATA",
            f"{symbol} does not yet have 24 hourly bars for every holdout day.",
            missing_or_partial_count=len(bad),
            sample=[str(x) for x in bad[:10]],
            latest_timestamp=str(raw["timestamp"].max()) if raw.height else None,
        )

    pre = daily_all.filter(pl.col("timestamp").dt.date() < HOLDOUT_START)
    if pre.filter(pl.col("source_rows") == 24).height < 100:
        fail("BLOCKED_WARMUP", f"{symbol} has fewer than 100 complete warmup days.")

    daily = (
        daily_all.filter(pl.col("source_rows") == 24)
        .with_columns(pl.lit(symbol).alias("symbol"))
        .select(["timestamp", "symbol", "open", "high", "low", "close", "volume", "source_rows"])
    )
    return daily, {
        "status": "PASS",
        "latest_timestamp": str(raw["timestamp"].max()),
        "holdout_complete_days": len(required_dates),
        "duplicates": int(raw.select(pl.col("timestamp").is_duplicated().sum()).item()),
    }


def nikkei_cash_rows(raw: pl.DataFrame) -> pl.DataFrame:
    local = pl.col("timestamp").dt.convert_time_zone("Asia/Tokyo")
    frame = raw.with_columns(
        local.dt.date().alias("session_date"),
        (local.dt.hour().cast(pl.Int32) * 60 + local.dt.minute().cast(pl.Int32)).alias("minute_of_day"),
    )
    pre_expansion = pl.col("session_date") < pl.date(2024, 11, 5)
    close_minute = pl.when(pre_expansion).then(pl.lit(900)).otherwise(pl.lit(930))
    return (
        frame.filter(
            (pl.col("minute_of_day") >= 540)
            & (pl.col("minute_of_day") < close_minute)
            & ~((pl.col("minute_of_day") >= 690) & (pl.col("minute_of_day") < 750))
        )
        .sort("timestamp")
    )


def load_nikkei_daily(end_exclusive: date) -> tuple[pl.DataFrame, dict[str, Any]]:
    base_dir = STORE_ROOT / "index_minute_NIKKEI225"
    files = glob.glob(str(base_dir / "year=*" / "month=*" / "data.parquet"))
    if not files:
        fail("WAITING_DATA", "No canonical LSE Nikkei files.")

    end_expr = pl.datetime(
        end_exclusive.year, end_exclusive.month, end_exclusive.day, time_zone="UTC"
    )
    raw = (
        pl.scan_parquet(files)
        .filter((pl.col("timestamp") >= WARMUP_START) & (pl.col("timestamp") < end_expr))
        .select(["timestamp", "open", "high", "low", "close", "volume"])
        .sort("timestamp")
        .collect()
        .with_columns(pl.col("timestamp").dt.cast_time_unit("us"))
    )
    cash = nikkei_cash_rows(raw)

    cal = xcals.get_calendar("XTKS")
    expected_all = {
        ts.date()
        for ts in cal.sessions_in_range(
            WARMUP_START.date(), end_exclusive - timedelta(days=1)
        ).to_pydatetime()
    }
    cash = cash.filter(pl.col("session_date").is_in(list(expected_all)))
    daily = (
        cash.group_by("session_date")
        .agg(
            pl.col("open").sort_by("timestamp").first().alias("open"),
            pl.col("high").max().alias("high"),
            pl.col("low").min().alias("low"),
            pl.col("close").sort_by("timestamp").last().alias("close"),
            pl.col("volume").sum().alias("volume"),
            pl.len().alias("source_rows"),
        )
        .sort("session_date")
    )

    holdout_expected = {
        ts.date()
        for ts in cal.sessions_in_range(
            HOLDOUT_START, end_exclusive - timedelta(days=1)
        ).to_pydatetime()
    }
    observed = set(daily["session_date"].to_list())
    missing = sorted(holdout_expected - observed)
    coverage = 1.0 - (len(missing) / len(holdout_expected)) if holdout_expected else 0.0
    if coverage < 0.98:
        fail(
            "WAITING_DATA",
            "Nikkei holdout coverage is below 98% of expected XTKS sessions.",
            coverage=coverage,
            missing_count=len(missing),
            sample=[str(x) for x in missing[:10]],
            latest_timestamp=str(raw["timestamp"].max()) if raw.height else None,
        )

    if len([d for d in observed if d < HOLDOUT_START]) < 100:
        fail("BLOCKED_WARMUP", "Nikkei has fewer than 100 warmup sessions.")

    daily = daily.with_columns(
        pl.col("session_date")
        .cast(pl.Datetime("us"))
        .dt.replace_time_zone("UTC")
        .alias("timestamp"),
        pl.lit("NIKKEI225_LSE").alias("symbol"),
    ).select(
        ["timestamp", "symbol", "open", "high", "low", "close", "volume", "source_rows"]
    )

    holdout = daily.filter(
        (pl.col("timestamp").dt.date() >= HOLDOUT_START)
        & (pl.col("timestamp").dt.date() < end_exclusive)
    ).with_columns((pl.col("close") / pl.col("close").shift(1) - 1).alias("ret"))
    extreme = holdout.filter(pl.col("ret").abs() > 0.20)
    if extreme.height:
        fail(
            "BLOCKED_DATA_QUALITY",
            "Nikkei holdout contains an absolute daily return above 20%.",
            extreme_days=extreme.height,
        )

    return daily, {
        "status": "PASS",
        "latest_timestamp": str(raw["timestamp"].max()),
        "expected_sessions": len(holdout_expected),
        "observed_sessions": len(holdout_expected) - len(missing),
        "coverage": coverage,
        "missing_sessions": [str(x) for x in missing],
    }


def run_market(
    inst: base.Instrument,
    daily: pl.DataFrame,
    end_exclusive: date,
    *,
    cost_multiplier: float,
):
    feat = base.engineer_features(inst, daily)
    frame = feat.filter(
        (pl.col("timestamp").dt.date() >= HOLDOUT_START)
        & (pl.col("timestamp").dt.date() < end_exclusive)
    ).select(
        ["timestamp", "symbol", "open", "high", "low", "close", "volume", SIGNAL_COL]
    ).drop_nulls([SIGNAL_COL])

    if frame.height < 2:
        fail("WAITING_DATA", f"Insufficient holdout bars for {inst.symbol}.")

    config = BacktestConfig(
        initial_cash=base.INITIAL_CASH,
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
            prices_df=frame.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"]),
            signals_df=frame.select(["timestamp", "symbol", SIGNAL_COL]),
            entity_col="symbol",
            timestamp_col="timestamp",
        ),
        base.SignalTargetStrategy(SIGNAL_COL),
        config,
    ).run()
    daily_ret = result.to_daily_pnl(session_aligned=False).select(
        ["date", pl.col("return_pct").alias("return")]
    )
    return result, daily_ret


def series_metrics(values: np.ndarray, periods_per_year: int) -> dict[str, Any]:
    r = values[np.isfinite(values)]
    wealth = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(wealth)
    dd = wealth / peak - 1.0
    std = float(np.std(r, ddof=1)) if r.size > 1 else 0.0
    return {
        "n": int(r.size),
        "total_return": float(wealth[-1] - 1.0) if r.size else None,
        "sharpe": float(np.mean(r) / std * math.sqrt(periods_per_year)) if std > 0 else 0.0,
        "max_drawdown": float(-np.min(dd)) if r.size else None,
    }


def portfolio_metrics(
    returns_by_market: dict[str, pl.DataFrame],
    end_exclusive: date,
) -> dict[str, Any]:
    days = daterange(HOLDOUT_START, end_exclusive)
    merged = pl.DataFrame({"date": days})
    cols = []
    for symbol, df in returns_by_market.items():
        col = f"ret_{symbol}"
        merged = merged.join(df.rename({"return": col}), on="date", how="left")
        merged = merged.with_columns(pl.col(col).fill_null(0.0))
        cols.append(col)
    merged = merged.with_columns(pl.mean_horizontal(cols).alias("portfolio_return"))
    metrics = series_metrics(merged["portfolio_return"].to_numpy(), 365)
    return {
        **metrics,
        "daily_rows": merged.height,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint-days", type=int, choices=sorted(CHECKPOINTS), default=90)
    parser.add_argument("--write-result", action="store_true")
    args = parser.parse_args()

    freeze = verify_freeze()
    catalog = verify_catalog()
    end_exclusive = CHECKPOINTS[args.checkpoint_days]

    today_utc = datetime.now(timezone.utc).date()
    if today_utc < end_exclusive:
        fail(
            "BLOCKED_TOO_EARLY",
            "Prospective checkpoint is not yet eligible. No holdout performance was computed.",
            today_utc=str(today_utc),
            holdout_start=str(HOLDOUT_START),
            checkpoint_end_exclusive=str(end_exclusive),
            calendar_days=args.checkpoint_days,
        )

    data: dict[str, pl.DataFrame] = {}
    audits: dict[str, Any] = {}
    for symbol in ("BTCUSDT", "ETHUSDT", "HYPEUSDT"):
        data[symbol], audits[symbol] = load_crypto_daily(symbol, end_exclusive)
    data["NIKKEI225_LSE"], audits["NIKKEI225_LSE"] = load_nikkei_daily(end_exclusive)

    results: dict[str, Any] = {}
    base_returns: dict[str, pl.DataFrame] = {}
    stress_returns: dict[str, pl.DataFrame] = {}
    for symbol in PRIMARY:
        inst = base.INSTRUMENTS[symbol]
        base_result, base_daily = run_market(inst, data[symbol], end_exclusive, cost_multiplier=1.0)
        stress_result, stress_daily = run_market(inst, data[symbol], end_exclusive, cost_multiplier=2.0)
        base_returns[symbol] = base_daily
        stress_returns[symbol] = stress_daily
        results[symbol] = {
            "base": {
                "total_return": float(base_result.metrics["total_return"]),
                "sharpe": float(base_result.metrics["sharpe"]),
                "max_drawdown": float(base_result.metrics["max_drawdown"]),
                "num_trades": int(base_result.metrics["num_trades"]),
            },
            "stress_2x": {
                "total_return": float(stress_result.metrics["total_return"]),
                "sharpe": float(stress_result.metrics["sharpe"]),
                "max_drawdown": float(stress_result.metrics["max_drawdown"]),
                "num_trades": int(stress_result.metrics["num_trades"]),
            },
        }

    portfolio_base = portfolio_metrics(base_returns, end_exclusive)
    portfolio_stress = portfolio_metrics(stress_returns, end_exclusive)
    positive_markets = sum(results[s]["base"]["total_return"] > 0 for s in PRIMARY)

    supportive = (
        portfolio_base["total_return"] > 0
        and portfolio_base["sharpe"] > 0
        and portfolio_stress["total_return"] > 0
        and positive_markets >= 2
        and portfolio_base["max_drawdown"] < 0.15
    )
    decision = "SUPPORTIVE" if supportive else "INCONCLUSIVE"

    output = {
        "schema": "tsmom_prospective_checkpoint/v1",
        "status": "COMPLETE",
        "decision": decision,
        "deployment_approval": False,
        "session_id": freeze["session_id"],
        "checkpoint_days": args.checkpoint_days,
        "holdout_start_inclusive": str(HOLDOUT_START),
        "holdout_end_exclusive": str(end_exclusive),
        "catalog": catalog,
        "data_audit": audits,
        "markets": results,
        "portfolio_equal_weight": {
            "base": portfolio_base,
            "stress_2x": portfolio_stress,
            "positive_markets_base": positive_markets,
        },
        "decision_rule": freeze["first_checkpoint_decision_rule"],
        "limitations": [
            "This checkpoint does not approve deployment.",
            "Crypto funding remains excluded because the frozen candidate excluded funding.",
            "Nikkei remains an index-price research proxy, not a contract-level futures series.",
            "DAX remains excluded from the primary portfolio.",
        ],
    }

    print("RESULT_JSON_BEGIN")
    print(json.dumps(output, sort_keys=True))
    print("RESULT_JSON_END")

    if args.write_result:
        out = (
            ROOT
            / "run_log/tsmom_40_60_80_lse_2020_2026"
            / f"prospective_checkpoint_{args.checkpoint_days}d.json"
        )
        if out.exists():
            fail("BLOCKED_RESULT_EXISTS", f"Refusing to overwrite {out}.")
        out.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
        print(f"WROTE {out}")


if __name__ == "__main__":
    main()
