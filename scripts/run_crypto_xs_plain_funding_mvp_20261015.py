"""Plain cross-sectional Binance USD-M funding factor MVP.

This runner is intentionally fail-fast:
1. Prepare bounded 2020-2023 panel inputs only.
2. Freeze the research session and require the repository panel audit to PASS.
3. Run native ml4t factor diagnostics.
4. Run native ml4t.backtest only if the frozen IC gate passes.
5. Apply actual funding events to the native broker cash ledger and reconcile.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from ml4t.backtest import BacktestConfig, DataFeed, Engine, Strategy
from ml4t.backtest.config import CommissionType, ExecutionPrice, ShareType, SlippageType
from ml4t.backtest.types import ExecutionMode
from ml4t.diagnostic.api import PortfolioAnalysis, compute_ic_hac_stats, cross_sectional_ic_series
from ml4t.engineer import compute_features

ROOT = Path(__file__).resolve().parents[1]
SESSION = "crypto_xs_plain_funding_mvp_20261015_v1"
DATA = ROOT / "data" / "processed" / SESSION
OUT = ROOT / "run_log" / "research_sessions" / SESSION / "mvp"

PRICE_STORE = Path(
    "/home/quant/dev/quant/ml4t-data/.data/store/"
    "crypto_futures_ohlcv_1h_BINANCE_UM_PERP"
)
STORE_ROOT = Path("/home/quant/dev/quant/ml4t-data/.data/store")
FUNDING_PREFIX = "crypto_futures_funding_"

WARMUP_START = datetime(2020, 1, 1, tzinfo=UTC)
DEV_START = datetime(2020, 6, 1, tzinfo=UTC)
DEV_END = datetime(2024, 1, 1, tzinfo=UTC)
YEARS = (2020, 2021, 2022, 2023)
HISTORY_HOURS = 720
TARGET_UNIVERSE = 40
MIN_UNIVERSE = 20
LEGS_PER_SIDE = 5
REBALANCE_HOURS = 48
LABEL_HOURS = 48
INITIAL_CASH = 100_000.0

IC_MIN = 0.020
IC_T_MIN = 2.0
MIN_CYCLES = 150
SHARPE_MIN = 0.50
MAX_DD_FLOOR = -0.35

BASE_COMMISSION = 0.0005
BASE_SLIPPAGE = 0.0004


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def sha256(path: Path) -> str:
    with path.open("rb") as fp:
        return hashlib.file_digest(fp, "sha256").hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False, default=str) + "\n")


def matched_funding_symbols() -> list[str]:
    symbols: list[str] = []
    for path in STORE_ROOT.glob(FUNDING_PREFIX + "*_PERP"):
        if not path.is_dir():
            continue
        symbol = path.name[len(FUNDING_PREFIX):-len("_PERP")]
        if symbol.endswith("USDT"):
            symbols.append(symbol)
    return sorted(set(symbols))


def _price_paths(year: int) -> list[str]:
    return [str(p) for p in PRICE_STORE.glob(f"symbol=*/year={year}/month=*/data.parquet")]


def _funding_paths(symbols: list[str], year: int) -> list[str]:
    paths: list[str] = []
    for symbol in symbols:
        paths.extend(
            str(p)
            for p in (
                STORE_ROOT / f"{FUNDING_PREFIX}{symbol}_PERP" / f"year={year}"
            ).glob("month=*/data.parquet")
        )
    return paths


def prepare() -> None:
    """Materialize only 2020-2023 panel data. Never scan a 2024+ partition."""
    DATA.mkdir(parents=True, exist_ok=True)
    funding_symbols = matched_funding_symbols()
    if len(funding_symbols) < MIN_UNIVERSE:
        raise RuntimeError("Insufficient matched canonical funding symbols")

    manifest: dict[str, Any] = {
        "session": SESSION,
        "price_store": str(PRICE_STORE),
        "funding_store_root": str(STORE_ROOT),
        "matched_usdt_funding_directories": len(funding_symbols),
        "protected_boundary": DEV_END.isoformat(),
        "years": {},
    }
    for year in YEARS:
        ppaths = _price_paths(year)
        if not ppaths:
            raise FileNotFoundError(f"No canonical price partitions for {year}")
        prices = (
            pl.scan_parquet(ppaths, hive_partitioning=True)
            .filter(pl.col("symbol").is_in(funding_symbols))
            .select("timestamp", "symbol", "open", "high", "low", "close", "volume")
            .sort("symbol", "timestamp")
            .collect()
        )
        if prices.is_empty() or prices.filter(pl.col("timestamp") >= DEV_END).height:
            raise RuntimeError(f"{year}: invalid bounded prices")
        if prices.group_by("symbol", "timestamp").len().filter(pl.col("len") > 1).height:
            raise RuntimeError(f"{year}: duplicate price entity timestamps")
        bad_price = prices.filter(
            (~pl.col("open").is_finite()) | (~pl.col("high").is_finite())
            | (~pl.col("low").is_finite()) | (~pl.col("close").is_finite())
            | (~pl.col("volume").is_finite()) | (pl.col("open") <= 0)
            | (pl.col("close") <= 0) | (pl.col("high") < pl.col("low"))
            | (pl.col("open") < pl.col("low")) | (pl.col("open") > pl.col("high"))
            | (pl.col("close") < pl.col("low")) | (pl.col("close") > pl.col("high"))
            | (pl.col("volume") < 0)
        ).height
        if bad_price:
            raise RuntimeError(f"{year}: invalid OHLCV rows {bad_price}")
        ptarget = DATA / f"prices_{year}.parquet"
        if ptarget.exists():
            if not pl.read_parquet(ptarget).equals(prices):
                raise FileExistsError(f"Existing prepared price panel differs: {ptarget}")
        else:
            prices.write_parquet(ptarget)

        fpaths = _funding_paths(funding_symbols, year)
        if not fpaths:
            raise FileNotFoundError(f"No canonical funding partitions for {year}")
        funding = (
            pl.scan_parquet(fpaths, hive_partitioning=True)
            .select("timestamp", "symbol", "funding_interval_hours", "funding_rate", "mark_price")
            .sort("symbol", "timestamp")
            .collect()
        )
        if funding.is_empty() or funding.filter(pl.col("timestamp") >= DEV_END).height:
            raise RuntimeError(f"{year}: invalid bounded funding")
        if funding.group_by("symbol", "timestamp").len().filter(pl.col("len") > 1).height:
            raise RuntimeError(f"{year}: duplicate funding entity timestamps")
        bad_funding = funding.filter(
            pl.col("funding_rate").is_null() | (~pl.col("funding_rate").is_finite())
            | (pl.col("funding_interval_hours") <= 0)
            | (
                pl.col("mark_price").is_not_null()
                & ((~pl.col("mark_price").is_finite()) | (pl.col("mark_price") <= 0))
            )
        ).height
        if bad_funding:
            raise RuntimeError(f"{year}: invalid funding rows {bad_funding}")
        ftarget = DATA / f"funding_{year}.parquet"
        if ftarget.exists():
            if not pl.read_parquet(ftarget).equals(funding):
                raise FileExistsError(f"Existing prepared funding panel differs: {ftarget}")
        else:
            funding.write_parquet(ftarget)

        manifest["years"][str(year)] = {
            "prices": {
                "rows": prices.height,
                "symbols": prices["symbol"].n_unique(),
                "first": str(prices["timestamp"].min()),
                "last": str(prices["timestamp"].max()),
                "path": str(ptarget.relative_to(ROOT)),
                "sha256": sha256(ptarget),
            },
            "funding": {
                "rows": funding.height,
                "symbols": funding["symbol"].n_unique(),
                "first": str(funding["timestamp"].min()),
                "last": str(funding["timestamp"].max()),
                "non_8h_events": funding.filter(pl.col("funding_interval_hours") != 8).height,
                "path": str(ftarget.relative_to(ROOT)),
                "sha256": sha256(ftarget),
            },
        }
        print("PREPARED", year, manifest["years"][str(year)], flush=True)
    write_json(DATA / "source_manifest.json", manifest)


def load_bounded() -> tuple[pl.DataFrame, pl.DataFrame]:
    price_paths = [DATA / f"prices_{year}.parquet" for year in YEARS]
    funding_paths = [DATA / f"funding_{year}.parquet" for year in YEARS]
    if not all(path.exists() for path in price_paths + funding_paths):
        raise FileNotFoundError("Prepared panel inputs are incomplete")
    prices = pl.concat([pl.read_parquet(path) for path in price_paths]).sort("symbol", "timestamp")
    funding = pl.concat([pl.read_parquet(path) for path in funding_paths]).sort("symbol", "timestamp")
    if prices.filter(pl.col("timestamp") >= DEV_END).height:
        raise AssertionError("Protected price observation loaded")
    if funding.filter(pl.col("timestamp") >= DEV_END).height:
        raise AssertionError("Protected funding observation loaded")
    return prices, funding


def price_features(prices: pl.DataFrame) -> pl.DataFrame:
    """Native ATR plus causal trailing dollar-volume extension."""
    native = compute_features(
        prices,
        [{"name": "atr", "params": {"period": 24}, "output": "atr24"}],
        group_col="symbol",
        timestamp_col="timestamp",
    )
    return (
        native.sort("symbol", "timestamp")
        .with_columns(
            ((pl.col("close") * pl.col("volume"))
             .rolling_sum(HISTORY_HOURS, min_samples=HISTORY_HOURS)
             .over("symbol")).alias("dollar_volume_720h"),
            pl.col("timestamp").shift(HISTORY_HOURS - 1).over("symbol").alias("trail_start"),
        )
    )


def _funding_cumulative(funding: pl.DataFrame) -> pl.DataFrame:
    return (
        funding.sort("symbol", "timestamp")
        .with_columns(
            pl.col("funding_rate").cum_sum().over("symbol").alias("fund_cum"),
            (pl.int_range(pl.len()).over("symbol") + 1).alias("fund_count_cum"),
        )
        .select("symbol", "timestamp", "fund_cum", "fund_count_cum")
    )


def attach_funding_24h(decisions: pl.DataFrame, funding: pl.DataFrame) -> pl.DataFrame:
    """Point-in-time trailing-24h funding using actual variable settlement events."""
    cumulative = _funding_cumulative(funding)
    current = cumulative.rename({
        "timestamp": "funding_observed_ts",
        "fund_cum": "fund_cum_now",
        "fund_count_cum": "fund_count_now",
    }).sort("symbol", "funding_observed_ts")
    prior = cumulative.rename({
        "timestamp": "funding_prior_ts",
        "fund_cum": "fund_cum_prior",
        "fund_count_cum": "fund_count_prior",
    }).sort("symbol", "funding_prior_ts")

    base = decisions.with_columns(
        (pl.col("decision_ts") + pl.duration(minutes=1)).alias("decision_available_ts"),
    ).sort("symbol", "decision_available_ts")
    base = base.join_asof(
        current,
        left_on="decision_available_ts",
        right_on="funding_observed_ts",
        by="symbol",
        strategy="backward",
    )
    base = base.with_columns(
        (pl.col("decision_available_ts") - pl.duration(hours=24)).alias("funding_lookback_ts")
    ).sort("symbol", "funding_lookback_ts")
    base = base.join_asof(
        prior,
        left_on="funding_lookback_ts",
        right_on="funding_prior_ts",
        by="symbol",
        strategy="backward",
    )
    return (
        base.with_columns(
            pl.col("fund_cum_prior").fill_null(0.0),
            pl.col("fund_count_prior").fill_null(0),
        )
        .with_columns(
            (pl.col("fund_cum_now") - pl.col("fund_cum_prior")).alias("cum_funding_24h"),
            (pl.col("fund_count_now") - pl.col("fund_count_prior")).alias("funding_events_24h"),
        )
        .filter(
            pl.col("fund_cum_now").is_not_null()
            & (pl.col("funding_events_24h") > 0)
            & (pl.col("funding_observed_ts") <= pl.col("decision_available_ts"))
        )
    )


def build_factor_panel(prices: pl.DataFrame, funding: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    features = price_features(prices)
    # The 23:00 bar is complete at 00:00 next day.
    decisions = (
        features.filter(pl.col("timestamp").dt.hour() == 23)
        .with_columns((pl.col("timestamp") + pl.duration(hours=1)).alias("decision_ts"))
    )
    anchor_seconds = int(DEV_START.timestamp())
    decisions = decisions.filter(
        (pl.col("decision_ts") >= DEV_START)
        & (pl.col("decision_ts") < DEV_END)
        & ((((pl.col("decision_ts").dt.epoch("s") - anchor_seconds) / 3600).cast(pl.Int64))
           % REBALANCE_HOURS == 0)
        & pl.col("dollar_volume_720h").is_not_null()
        & pl.col("atr24").is_not_null()
        & pl.col("trail_start").is_not_null()
        & ((pl.col("timestamp") - pl.col("trail_start"))
           == pl.duration(hours=HISTORY_HOURS - 1))
    )
    decisions = attach_funding_24h(decisions, funding)

    counts = decisions.group_by("decision_ts").agg(pl.len().alias("eligible_count"))
    decisions = decisions.join(counts, on="decision_ts", how="left").filter(
        pl.col("eligible_count") >= MIN_UNIVERSE
    )
    panel = (
        decisions.with_columns(
            pl.col("dollar_volume_720h")
            .rank(method="ordinal", descending=True)
            .over("decision_ts")
            .alias("liq_rank")
        )
        .filter(pl.col("liq_rank") <= TARGET_UNIVERSE)
        .with_columns(
            (-pl.col("cum_funding_24h")).alias("prediction"),
        )
    )

    opens = prices.select("symbol", "timestamp", pl.col("open").alias("entry_open"))
    panel = panel.with_columns(
        (pl.col("decision_ts") + pl.duration(hours=1)).alias("entry_ts"),
        (pl.col("decision_ts") + pl.duration(hours=1 + LABEL_HOURS)).alias("exit_ts"),
    )
    panel = (
        panel.join(opens.rename({"timestamp": "entry_ts"}), on=["symbol", "entry_ts"], how="left")
        .join(
            opens.rename({"timestamp": "exit_ts", "entry_open": "exit_open"}),
            on=["symbol", "exit_ts"],
            how="left",
        )
        .with_columns((pl.col("exit_open") / pl.col("entry_open") - 1).alias("forward_return_48h"))
        .filter(
            pl.col("entry_open").is_not_null()
            & pl.col("exit_open").is_not_null()
            & pl.col("forward_return_48h").is_finite()
            & (pl.col("exit_ts") < DEV_END)
        )
        .sort("decision_ts", "symbol")
    )

    cycle = (
        panel.group_by("decision_ts")
        .agg(
            pl.len().alias("universe_size"),
            pl.col("eligible_count").first().alias("eligible_before_topn"),
        )
        .sort("decision_ts")
    )
    return panel, cycle


def factor_diagnostics(panel: pl.DataFrame, cycle: pl.DataFrame) -> dict[str, Any]:
    predictions = panel.select(
        pl.col("decision_ts").alias("date"), "symbol", "prediction"
    )
    returns = panel.select(
        pl.col("decision_ts").alias("date"), "symbol",
        pl.col("forward_return_48h").alias("forward_return"),
    )
    ic = cross_sectional_ic_series(
        predictions,
        returns,
        pred_col="prediction",
        ret_col="forward_return",
        date_col="date",
        entity_col="symbol",
        method="spearman",
        min_obs=10,
    )
    stats = compute_ic_hac_stats(ic, ic_col="ic", maxlags=1, label_horizon=1)
    clean = ic.filter(pl.col("ic").is_not_null()).sort("date")
    values = clean["ic"].to_numpy()
    midpoint = len(values) // 2
    first_half = float(np.mean(values[:midpoint])) if midpoint else None
    second_half = float(np.mean(values[midpoint:])) if len(values) - midpoint else None
    ic_ir = (
        float(np.mean(values) / np.std(values, ddof=1))
        if len(values) > 1 and np.std(values, ddof=1) > 0 else None
    )
    return {
        "stats": {
            key: float(value) if isinstance(value, (float, np.floating)) and math.isfinite(value)
            else int(value) if isinstance(value, (int, np.integer))
            else value
            for key, value in stats.items()
        },
        "ic_ir": ic_ir,
        "first_half_mean_ic": first_half,
        "second_half_mean_ic": second_half,
        "ic_periods": clean.height,
        "eligible_cycles": cycle.height,
        "min_universe": int(cycle["universe_size"].min()) if cycle.height else 0,
        "median_universe": float(cycle["universe_size"].median()) if cycle.height else 0.0,
        "max_universe": int(cycle["universe_size"].max()) if cycle.height else 0,
        "ic_series": ic,
    }


def ic_gate(diag: dict[str, Any]) -> tuple[bool, list[str]]:
    stats = diag["stats"]
    reasons: list[str] = []
    mean_ic = stats.get("mean_ic")
    t_stat = stats.get("t_stat")
    if mean_ic is None or not math.isfinite(float(mean_ic)) or float(mean_ic) < IC_MIN:
        reasons.append(f"mean IC {mean_ic} < {IC_MIN}")
    if t_stat is None or not math.isfinite(float(t_stat)) or float(t_stat) < IC_T_MIN:
        reasons.append(f"HAC t-stat {t_stat} < {IC_T_MIN}")
    if diag["first_half_mean_ic"] is None or diag["first_half_mean_ic"] <= 0:
        reasons.append("first chronological half mean IC is not positive")
    if diag["second_half_mean_ic"] is None or diag["second_half_mean_ic"] <= 0:
        reasons.append("second chronological half mean IC is not positive")
    if diag["eligible_cycles"] < MIN_CYCLES:
        reasons.append(f"eligible cycles {diag['eligible_cycles']} < {MIN_CYCLES}")
    if diag["min_universe"] < MIN_UNIVERSE:
        reasons.append(f"minimum universe {diag['min_universe']} < {MIN_UNIVERSE}")
    return not reasons, reasons


def build_baskets(panel: pl.DataFrame) -> dict[datetime, dict[str, float]]:
    baskets: dict[datetime, dict[str, float]] = {}
    for decision, group in panel.group_by("decision_ts", maintain_order=True):
        ts = _utc(decision[0] if isinstance(decision, tuple) else decision)
        rows = group.select("symbol", "cum_funding_24h").sort(
            "cum_funding_24h", "symbol"
        )
        if rows.height < MIN_UNIVERSE:
            baskets[ts] = {}
            continue
        longs = rows.head(LEGS_PER_SIDE)["symbol"].to_list()
        shorts = rows.tail(LEGS_PER_SIDE).sort(
            "cum_funding_24h", "symbol", descending=[True, False]
        )["symbol"].to_list()
        if set(longs) & set(shorts):
            raise AssertionError("Long and short baskets overlap")
        target = {symbol: 0.10 for symbol in longs}
        target.update({symbol: -0.10 for symbol in shorts})
        if not math.isclose(sum(abs(weight) for weight in target.values()), 1.0, abs_tol=1e-12):
            raise AssertionError("Target gross weight is not 1.0")
        if not math.isclose(sum(target.values()), 0.0, abs_tol=1e-12):
            raise AssertionError("Target net weight is not zero")
        baskets[ts] = target
    return baskets



def required_funding_events(
    funding: pl.DataFrame,
    baskets: dict[datetime, dict[str, float]],
) -> pl.DataFrame:
    """Funding events that can affect a selected position under the frozen clock."""
    pieces: list[pl.DataFrame] = []
    for decision_ts, targets in sorted(baskets.items()):
        entry = decision_ts + timedelta(hours=1)
        exit_ = entry + timedelta(hours=LABEL_HOURS)
        symbols = sorted(targets)
        if not symbols:
            continue
        # Exact entry-boundary funding belongs to the position carried from the
        # prior cycle. Events after entry through exact exit affect this cycle.
        piece = funding.filter(
            pl.col("symbol").is_in(symbols)
            & (pl.col("timestamp") > entry)
            & (pl.col("timestamp") <= exit_)
        )
        if piece.height:
            pieces.append(piece)
    if not pieces:
        return funding.head(0)
    return (
        pl.concat(pieces)
        .unique(subset=["symbol", "timestamp"], maintain_order=True)
        .sort("timestamp", "symbol")
    )


def _load_ml4t_data_funding_provider():
    """Load the existing canonical Binance REST provider without duplicating it."""
    import importlib
    import sys

    repo = "/home/quant/dev/quant/ml4t-data"
    scripts = f"{repo}/scripts"
    for path in (scripts, repo):
        if path not in sys.path:
            sys.path.insert(0, path)
    return importlib.import_module("fetch_binance_perp_funding")


def qualify_exact_funding_marks(
    local_funding: pl.DataFrame,
    baskets: dict[datetime, dict[str, float]],
) -> tuple[bool, pl.DataFrame, dict[str, Any]]:
    """Fail closed on the first held funding event lacking exact REST markPrice."""
    required = required_funding_events(local_funding, baskets)
    evidence_dir = OUT / "execution_mark_api"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    provider = _load_ml4t_data_funding_provider()
    limiter = provider.RateLimiter(90, per_seconds=60.0)
    cache: dict[tuple[str, str], pl.DataFrame] = {}
    qualified: list[dict[str, Any]] = []
    provider_path = Path(provider.__file__).resolve()
    audit: dict[str, Any] = {
        "provider_file": str(provider_path),
        "provider_sha256": sha256(provider_path),
        "endpoint": "https://fapi.binance.com/fapi/v1/fundingRate",
        "required_events": required.height,
        "queries": [],
        "status": "PASS",
        "blocker": None,
    }
    for event in required.iter_rows(named=True):
        symbol = event["symbol"]
        ts = _utc(event["timestamp"])
        day = ts.date().isoformat()
        key = (symbol, day)
        if key not in cache:
            start = datetime(ts.year, ts.month, ts.day, tzinfo=UTC)
            end = start + timedelta(days=1) - timedelta(milliseconds=1)
            frame = provider.fetch_api_dataframe(
                symbol,
                int(start.timestamp() * 1000),
                int(end.timestamp() * 1000),
                limiter,
            ).sort("timestamp")
            cache[key] = frame
            target = evidence_dir / f"{symbol}_{day}.parquet"
            frame.write_parquet(target)
            audit["queries"].append({
                "symbol": symbol,
                "date": day,
                "rows": frame.height,
                "path": str(target.relative_to(ROOT)),
                "sha256": sha256(target),
            })
        official = cache[key].filter(pl.col("timestamp") == ts)
        if official.height != 1:
            audit["status"] = "BLOCKED"
            audit["blocker"] = {
                "reason": "exact_official_funding_event_missing",
                "symbol": symbol,
                "timestamp": ts.isoformat(),
                "matches": official.height,
            }
            break
        row = official.row(0, named=True)
        if not math.isclose(
            float(row["funding_rate"]), float(event["funding_rate"]),
            rel_tol=0.0, abs_tol=1e-15,
        ):
            audit["status"] = "BLOCKED"
            audit["blocker"] = {
                "reason": "official_local_funding_rate_mismatch",
                "symbol": symbol,
                "timestamp": ts.isoformat(),
                "local_rate": float(event["funding_rate"]),
                "official_rate": float(row["funding_rate"]),
            }
            break
        mark = row["mark_price"]
        if mark is None or not math.isfinite(float(mark)) or float(mark) <= 0:
            audit["status"] = "BLOCKED"
            audit["blocker"] = {
                "reason": "exact_settlement_mark_price_unavailable",
                "symbol": symbol,
                "timestamp": ts.isoformat(),
                "funding_rate": float(event["funding_rate"]),
                "official_mark_price": None if mark is None else float(mark),
            }
            break
        qualified.append({
            "timestamp": ts,
            "symbol": symbol,
            "funding_interval_hours": int(event["funding_interval_hours"]),
            "funding_rate": float(event["funding_rate"]),
            "mark_price": float(mark),
        })
    exact = (
        pl.DataFrame(qualified)
        if qualified
        else pl.DataFrame(
            schema={
                "timestamp": pl.Datetime("us", "UTC"),
                "symbol": pl.String,
                "funding_interval_hours": pl.Int64,
                "funding_rate": pl.Float64,
                "mark_price": pl.Float64,
            }
        )
    )
    if audit["status"] == "PASS" and exact.height != required.height:
        raise AssertionError("Exact-mark qualification count mismatch")
    if exact.height:
        exact.write_parquet(evidence_dir / "qualified_required_events.parquet")
        audit["qualified_events_sha256"] = sha256(
            evidence_dir / "qualified_required_events.parquet"
        )
    write_json(OUT / "execution_mark_preflight.json", audit)
    return audit["status"] == "PASS", exact, audit

def funding_cashflow(quantity: float, mark_price: float, funding_rate: float) -> float:
    """Linear USDT perpetual funding cashflow: long pays positive funding."""
    return -float(quantity) * float(mark_price) * float(funding_rate)


def funding_events_by_hour(
    funding: pl.DataFrame, symbols: set[str]
) -> dict[datetime, list[dict[str, Any]]]:
    selected = funding.filter(
        pl.col("symbol").is_in(sorted(symbols))
        & (pl.col("timestamp") >= DEV_START)
        & (pl.col("timestamp") < DEV_END)
    ).sort("timestamp", "symbol")
    out: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
    for row in selected.iter_rows(named=True):
        ts = _utc(row["timestamp"])
        hour = ts.replace(minute=0, second=0, microsecond=0)
        out[hour].append({
            "timestamp": ts,
            "symbol": row["symbol"],
            "funding_rate": float(row["funding_rate"]),
            "mark_price": float(row["mark_price"]),
        })
    return dict(out)


class FundingBasketStrategy(Strategy):
    """Native rebalance strategy with narrow native-ledger funding cash mutation."""

    def __init__(
        self,
        baskets: dict[datetime, dict[str, float]],
        funding_events: dict[datetime, list[dict[str, Any]]],
        *,
        apply_funding: bool,
        flatten_ts: datetime,
    ):
        self.baskets = baskets
        self.funding_events = funding_events
        self.apply_funding = apply_funding
        self.flatten_ts = flatten_ts
        self.prior_quantities: dict[str, float] = {}
        self.funding_ledger: list[dict[str, Any]] = []
        self.order_expected_fill: dict[str, datetime] = {}
        self.rebalance_log: list[dict[str, Any]] = []

    def _quantity(self, broker, symbol: str) -> float:
        position = broker.get_position(symbol)
        return float(position.quantity) if position is not None else 0.0

    def _apply_hour_funding(self, timestamp: datetime, broker) -> None:
        if not self.apply_funding:
            return
        for event in self.funding_events.get(timestamp, []):
            symbol = event["symbol"]
            event_ts = event["timestamp"]
            # Exact hour-boundary settlement uses the position carried from the
            # prior bar. Later-in-hour events use post-open current holdings.
            quantity = (
                self.prior_quantities.get(symbol, 0.0)
                if event_ts == timestamp
                else self._quantity(broker, symbol)
            )
            if quantity == 0.0:
                continue
            cashflow = funding_cashflow(
                quantity, event["mark_price"], event["funding_rate"]
            )
            before = float(broker.cash)
            broker.cash = before + cashflow
            self.funding_ledger.append({
                **event,
                "quantity": quantity,
                "cashflow": cashflow,
                "cash_before": before,
                "cash_after": float(broker.cash),
            })

    def _submit_targets(self, timestamp: datetime, targets: dict[str, float], broker) -> None:
        orders = broker.rebalance_to_weights(targets)
        submitted = 0
        for order in orders:
            if order is None:
                continue
            self.order_expected_fill[order.order_id] = timestamp + timedelta(hours=1)
            submitted += 1
        self.rebalance_log.append({
            "decision_ts": timestamp,
            "target_count": len(targets),
            "target_gross": sum(abs(v) for v in targets.values()),
            "target_net": sum(targets.values()),
            "orders_submitted": submitted,
        })

    def on_data(self, timestamp, data, context, broker) -> None:
        ts = _utc(timestamp)
        self._apply_hour_funding(ts, broker)
        if ts in self.baskets:
            self._submit_targets(ts, self.baskets[ts], broker)
        elif ts == self.flatten_ts:
            self._submit_targets(ts, {}, broker)
        self.prior_quantities = {
            symbol: float(position.quantity)
            for symbol, position in broker.get_positions().items()
            if position.quantity != 0
        }


def _config(cost_multiplier: float) -> BacktestConfig:
    return BacktestConfig(
        initial_cash=INITIAL_CASH,
        allow_short_selling=True,
        allow_leverage=True,
        share_type=ShareType.FRACTIONAL,
        execution_mode=ExecutionMode.NEXT_BAR,
        execution_price=ExecutionPrice.OPEN,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=BASE_COMMISSION * cost_multiplier,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=BASE_SLIPPAGE * cost_multiplier,
    )


def _risk_metrics(equity: pl.DataFrame) -> tuple[dict[str, Any], pl.DataFrame, dict[str, float]]:
    daily = (
        equity.with_columns(pl.col("timestamp").dt.date().alias("date"))
        .group_by("date").agg(pl.col("equity").last().alias("equity")).sort("date")
    )
    returns = daily["equity"].pct_change().fill_null(0.0).to_numpy()
    summary = PortfolioAnalysis(
        returns=returns, periods_per_year=365.25
    ).compute_summary_stats()
    risk = {}
    for key, value in vars(summary).items():
        if isinstance(value, (int, float, np.number)):
            x = float(value)
            risk[key] = x if math.isfinite(x) else None
    yearly = (
        daily.with_columns(pl.col("equity").pct_change().fill_null(0.0).alias("ret"))
        .with_columns(pl.col("date").dt.year().alias("year"))
        .group_by("year")
        .agg(((pl.col("ret") + 1).product() - 1).alias("return"))
        .sort("year")
    )
    yearly_map = {str(row["year"]): float(row["return"]) for row in yearly.iter_rows(named=True)}
    return risk, daily, yearly_map


def run_native_arm(
    arm: str,
    prices: pl.DataFrame,
    funding: pl.DataFrame,
    baskets: dict[datetime, dict[str, float]],
    *,
    cost_multiplier: float,
    apply_funding: bool,
) -> dict[str, Any]:
    destination = OUT / "portfolio" / arm
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"Immutable arm already exists: {destination}")
    destination.mkdir(parents=True, exist_ok=True)

    selected_symbols = set().union(*(set(targets) for targets in baskets.values()))
    feed_prices = prices.filter(
        pl.col("symbol").is_in(sorted(selected_symbols))
        & (pl.col("timestamp") >= DEV_START)
        & (pl.col("timestamp") < DEV_END)
    ).sort("timestamp", "symbol")
    if feed_prices.is_empty():
        raise RuntimeError("No portfolio feed prices")

    events = funding_events_by_hour(funding, selected_symbols)
    flatten_ts = max(baskets) + timedelta(hours=LABEL_HOURS)
    if flatten_ts >= DEV_END:
        raise AssertionError("Flatten timestamp reaches protected boundary")
    strategy = FundingBasketStrategy(
        baskets, events, apply_funding=apply_funding, flatten_ts=flatten_ts
    )
    result = Engine(
        DataFeed(prices_df=feed_prices, entity_col="symbol", timestamp_col="timestamp"),
        strategy,
        _config(cost_multiplier),
    ).run()

    fills = result.to_fills_dataframe()
    trades = result.to_trades_dataframe()
    equity = result.to_equity_dataframe()
    rejected = result.to_rejected_orders_dataframe()
    fills.write_csv(destination / "fills.csv")
    trades.write_csv(destination / "trades.csv")
    equity.write_parquet(destination / "hourly_equity.parquet")
    pl.DataFrame(strategy.funding_ledger).write_parquet(destination / "funding_ledger.parquet")
    pl.DataFrame(strategy.rebalance_log).write_csv(destination / "rebalance_log.csv")

    if rejected.height:
        rejected.write_csv(destination / "rejected_orders.csv")
        raise AssertionError(f"{arm}: native rejected orders {rejected.height}")
    if result.portfolio_state and result.portfolio_state[-1][5] != 0:
        raise AssertionError(f"{arm}: final native position count is not zero")

    fill_map = {
        row["order_id"]: _utc(row["timestamp"])
        for row in fills.iter_rows(named=True)
    }
    missing_order_fills = set(strategy.order_expected_fill) - set(fill_map)
    if missing_order_fills:
        raise AssertionError(f"{arm}: submitted native orders without fills")
    for order_id, expected in strategy.order_expected_fill.items():
        if fill_map[order_id] != expected:
            raise AssertionError(
                f"{arm}: order {order_id} filled {fill_map[order_id]} not {expected}"
            )

    closed = trades.filter(pl.col("status") == "closed") if trades.height else trades
    trade_pnl = float(closed["pnl"].sum()) if closed.height else 0.0
    funding_total = float(sum(row["cashflow"] for row in strategy.funding_ledger))
    native_net = float(result.metrics["final_value"]) - INITIAL_CASH
    ledger_error = native_net - (trade_pnl + funding_total)
    if abs(ledger_error) > max(0.10, abs(native_net) * 1e-7):
        raise AssertionError(
            f"{arm}: native equity != trade PnL + funding: error {ledger_error}"
        )

    risk, daily, yearly = _risk_metrics(equity)
    daily.write_csv(destination / "daily_equity.csv")
    max_gross = max(
        (
            state[3] / state[1]
            for state in result.portfolio_state
            if len(state) > 3 and state[1] > 0
        ),
        default=0.0,
    )
    payload = {
        "arm": arm,
        "cost_multiplier": cost_multiplier,
        "commission_bps_per_side": BASE_COMMISSION * 10_000 * cost_multiplier,
        "slippage_bps_per_side": BASE_SLIPPAGE * 10_000 * cost_multiplier,
        "funding_applied": apply_funding,
        "symbols_ever_selected": len(selected_symbols),
        "rebalance_cycles": len(baskets),
        "fills": fills.height,
        "closed_native_trade_records": closed.height,
        "funding_events_nonzero_position": len(strategy.funding_ledger),
        "funding_cashflow_usdt": funding_total,
        "trade_pnl_usdt": trade_pnl,
        "final_equity_usdt": float(result.metrics["final_value"]),
        "net_pnl_usdt": native_net,
        "total_return": native_net / INITIAL_CASH,
        "native_equity_reconciliation_error_usdt": ledger_error,
        "native_fill_clock_exact_next_hour": True,
        "native_rejected_orders": 0,
        "max_gross_notional_over_equity": max_gross,
        "daily_risk": risk,
        "yearly_returns": yearly,
        "native_metrics": {
            k: (
                float(v) if isinstance(v, (int, float, np.number)) and math.isfinite(float(v))
                else str(v)
            )
            for k, v in result.metrics.items()
        },
    }
    write_json(destination / "metrics.json", payload)
    print("ARM", arm, json.dumps({
        "net": native_net,
        "return": payload["total_return"],
        "funding": funding_total,
        "sharpe": risk.get("sharpe_ratio"),
        "max_dd": risk.get("max_drawdown"),
    }), flush=True)
    return payload


def _metric(risk: dict[str, Any], name: str) -> float | None:
    value = risk.get(name)
    return float(value) if value is not None else None


def portfolio_gate(
    base: dict[str, Any], stress: dict[str, Any]
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    sharpe = _metric(base["daily_risk"], "sharpe_ratio")
    max_dd = _metric(base["daily_risk"], "max_drawdown")
    if base["total_return"] <= 0:
        reasons.append("base-cost net total return is not positive")
    if sharpe is None or sharpe < SHARPE_MIN:
        reasons.append(f"base-cost daily Sharpe {sharpe} < {SHARPE_MIN}")
    if max_dd is None or max_dd < MAX_DD_FLOOR:
        reasons.append(f"base-cost max drawdown {max_dd} < {MAX_DD_FLOOR}")
    if base["funding_cashflow_usdt"] <= 0:
        reasons.append("realized funding cashflow is not positive")
    if stress["total_return"] <= 0:
        reasons.append("2x execution-cost stress is not net profitable")
    return not reasons, reasons


def run_research() -> None:
    frozen = ROOT / "run_log" / "research_sessions" / SESSION / "frozen_spec.json"
    if not frozen.exists():
        raise RuntimeError("Research session must be frozen before outcomes")
    if OUT.exists() and (OUT / "terminal_decision.json").exists():
        raise FileExistsError("Terminal MVP evidence already exists")
    OUT.mkdir(parents=True, exist_ok=True)

    prices, funding = load_bounded()
    panel, cycles = build_factor_panel(prices, funding)
    panel.write_parquet(OUT / "factor_panel.parquet")
    cycles.write_csv(OUT / "cycle_breadth.csv")
    diag = factor_diagnostics(panel, cycles)
    diag["ic_series"].write_csv(OUT / "ic_series.csv")
    diag_serial = {k: v for k, v in diag.items() if k != "ic_series"}
    write_json(OUT / "ic_diagnostics.json", diag_serial)

    passed, ic_reasons = ic_gate(diag)
    print("IC", json.dumps({
        "passed": passed,
        "mean_ic": diag["stats"].get("mean_ic"),
        "t": diag["stats"].get("t_stat"),
        "first": diag["first_half_mean_ic"],
        "second": diag["second_half_mean_ic"],
        "cycles": diag["eligible_cycles"],
        "min_universe": diag["min_universe"],
    }), flush=True)

    if not passed:
        write_json(OUT / "terminal_decision.json", {
            "decision": "REJECT",
            "stage": "IC_GATE",
            "reasons": ic_reasons,
            "ic": diag_serial,
            "portfolio_executed": False,
            "protected_2024_plus_accessed": False,
        })
        return

    baskets = build_baskets(panel)
    if len(baskets) < MIN_CYCLES:
        raise AssertionError("Basket count diverges from IC cycle count")

    exact_marks_ok, exact_funding, mark_audit = qualify_exact_funding_marks(
        funding, baskets
    )
    if not exact_marks_ok:
        write_json(OUT / "terminal_decision.json", {
            "decision": "INCONCLUSIVE",
            "stage": "EXECUTION_DATA_GATE",
            "reasons": [
                "Exact historical Binance settlement markPrice is unavailable "
                "for at least one funding event that affects a selected position."
            ],
            "ic": diag_serial,
            "execution_mark_preflight": mark_audit,
            "portfolio_executed": False,
            "protected_2024_plus_accessed": False,
        })
        return

    base = run_native_arm(
        "native_funding_base_cost", prices, exact_funding, baskets,
        cost_multiplier=1.0, apply_funding=True,
    )
    stress = run_native_arm(
        "native_funding_double_cost", prices, exact_funding, baskets,
        cost_multiplier=2.0, apply_funding=True,
    )
    nofund = run_native_arm(
        "native_no_funding_decomposition", prices, exact_funding, baskets,
        cost_multiplier=1.0, apply_funding=False,
    )
    passed_portfolio, portfolio_reasons = portfolio_gate(base, stress)
    verdict = "VALIDATE" if passed_portfolio else "REJECT"
    write_json(OUT / "terminal_decision.json", {
        "decision": verdict,
        "stage": "PORTFOLIO_GATE",
        "reasons": portfolio_reasons,
        "protected_2024_plus_accessed": False,
        "ic": diag_serial,
        "base": base,
        "double_cost": stress,
        "no_funding": nofund,
        "price_alpha_decomposition_usdt": nofund["net_pnl_usdt"],
        "funding_aware_increment_vs_no_funding_usdt": (
            base["net_pnl_usdt"] - nofund["net_pnl_usdt"]
        ),
    })


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.prepare == args.run:
        parser.error("Choose exactly one of --prepare or --run")
    if args.prepare:
        prepare()
    else:
        run_research()


if __name__ == "__main__":
    main()
