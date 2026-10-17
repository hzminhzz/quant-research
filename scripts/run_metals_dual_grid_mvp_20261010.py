"""Exploratory Lighter XAU/XAG dual-grid A/B using ML4T feature and execution APIs."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import yaml
from ml4t.backtest import BacktestConfig, DataFeed, Engine, Strategy
from ml4t.backtest.config import CommissionType, ShareType, SlippageType
from ml4t.backtest.core import SubmitOrderOptions
from ml4t.backtest.types import (
    ExecutionMode,
    ExitReason,
    OrderSide,
    OrderStatus,
    OrderType,
)
from ml4t.diagnostic import quantile_profile
from ml4t.engineer import compute_features

from scripts.run_hyperliquid_xyz_full_ladder_ab_20261009 import SharedVolumeBudget

ROOT = Path(__file__).resolve().parents[1]
CFG_PATH = ROOT / "config/research_sessions/metals_dual_grid_mvp_20261010.yaml"
SESSION = "metals_dual_grid_mvp_20261010"
ASSETS = ("XAU", "XAG")
FEATURE_DIR = ROOT / "data/features" / SESSION
RUN_DIR = ROOT / "run_log/research_sessions" / SESSION
BETA_COLUMN = "rolling_beta_xag_on_xau"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_files(cfg: dict) -> list[Path]:
    root = Path(cfg["source"]["root"])
    start = datetime.fromisoformat(cfg["source"]["first_available_utc"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(cfg["source"]["last_available_utc"].replace("Z", "+00:00"))
    year, month = start.year, start.month
    paths = []
    while (year, month) <= (end.year, end.month):
        for symbol in ASSETS:
            paths.append(root / f"symbol={symbol}" / f"year={year}" / f"month={month:02d}" / "data.parquet")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing source partition(s): {missing}")
    return paths


def freeze(cfg: dict) -> Path:
    """Record inputs and code before any feature, diagnostic, or backtest run."""
    files = _source_files(cfg)
    if not files:
        raise FileNotFoundError(f"No monthly parquet partitions under {cfg['source']['root']}")
    source = [{"path": str(p), "sha256": _sha256(p), "size_bytes": p.stat().st_size} for p in files]
    spec = {
        "session_id": SESSION,
        "classification": "EXPLORATORY",
        "approval_status": "NOT_APPROVED",
        "frozen_at_utc": datetime.now(UTC).isoformat(),
        "config_path": str(CFG_PATH.relative_to(ROOT)),
        "config_sha256": _sha256(CFG_PATH),
        "runner_path": str(Path(__file__).resolve().relative_to(ROOT)),
        "runner_sha256": _sha256(Path(__file__)),
        "source_partitions": source,
        "source_partition_count": len(source),
        "source_total_bytes": sum(item["size_bytes"] for item in source),
        "trial_ids": ["A_fixed_spacing", "B_beta_adjusted_silver_spacing"],
    }
    spec["frozen_sha256"] = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    target = RUN_DIR / "frozen_spec.json"
    target.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
    return target


def _read_source(cfg: dict) -> pl.DataFrame:
    start = datetime.fromisoformat(cfg["source"]["first_available_utc"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(cfg["source"]["last_available_utc"].replace("Z", "+00:00"))
    frames = []
    partitions = _source_files(cfg)
    for symbol in ASSETS:
        paths = [
            str(path) for path in partitions
            if path.parent.parent.parent.name == f"symbol={symbol}"
        ]
        frame = pl.scan_parquet(paths).select(
            "timestamp", "open", "high", "low", "close", "volume"
        ).with_columns(pl.lit(symbol).alias("symbol")).collect()
        frame = frame.filter((pl.col("timestamp") >= start) & (pl.col("timestamp") <= end))
        if frame.is_empty():
            raise ValueError(f"No source rows for {symbol} in the frozen date window")
        frames.append(frame)
    raw = pl.concat(frames).sort(["symbol", "timestamp"])
    if raw.select(pl.any_horizontal(pl.all().is_null())).to_series().any():
        raise ValueError("Null source values found")
    if raw.filter((pl.col("high") < pl.max_horizontal("open", "close")) | (pl.col("low") > pl.min_horizontal("open", "close")) | (pl.col("volume") < 0)).height:
        raise ValueError("Invalid OHLCV source row")
    dupes = raw.group_by(["symbol", "timestamp"]).len().filter(pl.col("len") > 1)
    if dupes.height:
        raise ValueError("Duplicate symbol timestamps in source")
    return raw


def make_two_minute_panel(raw: pl.DataFrame) -> pl.DataFrame:
    """Aggregate UTC-aligned 1m bars into complete 2m bars."""
    bars = (
        raw.sort(["symbol", "timestamp"])
        .group_by_dynamic("timestamp", every="2m", group_by="symbol", closed="left", label="left")
        .agg(
            pl.col("open").first(), pl.col("high").max(), pl.col("low").min(),
            pl.col("close").last(), pl.col("volume").sum(), pl.len().alias("source_rows"),
        )
        .filter(pl.col("source_rows") == 2)
        .drop("source_rows")
        .sort(["symbol", "timestamp"])
    )
    if bars.is_empty():
        raise ValueError("No complete 2-minute bars")
    unpaired = (
        bars.group_by("timestamp")
        .agg(pl.col("symbol").n_unique().alias("symbol_count"))
        .filter(pl.col("symbol_count") != len(ASSETS))
    )
    if unpaired.height:
        raise ValueError("XAU/XAG 2-minute timestamps do not match")
    gap_minutes = (
        bars.select("timestamp").unique().sort("timestamp")
        .select(pl.col("timestamp").diff().dt.total_minutes().max())
        .item()
    )
    if gap_minutes is not None and gap_minutes > 2:
        raise ValueError("Missing 2-minute timestamps in paired source data")
    return bars


def add_beta(panel: pl.DataFrame, lookback_bars: int = 21_600) -> pl.DataFrame:
    """Add strictly lagged beta; current-bar returns never enter beta(t)."""
    enriched = compute_features(
        panel,
        [{"name": "multi_horizon_returns", "params": {"horizons": [1], "log_returns": True}, "output": "ret"}],
        group_col="symbol",
        timestamp_col="timestamp",
    )
    if isinstance(enriched, pl.LazyFrame):
        enriched = enriched.collect()
    ret_col = "ret_log_ret_1m"
    wide = (
        enriched.select("timestamp", "symbol", ret_col)
        .pivot(on="symbol", index="timestamp", values=ret_col)
        .sort("timestamp")
        .rename({"XAU": "xau_ret", "XAG": "xag_ret"})
        .with_columns(
            (pl.col("xau_ret") * pl.col("xag_ret")).alias("cross"),
            pl.col("xau_ret").pow(2).alias("xau_sq"),
        )
        .with_columns(
            pl.col("xau_ret").rolling_mean(lookback_bars, min_samples=lookback_bars).shift(1).alias("mx"),
            pl.col("xag_ret").rolling_mean(lookback_bars, min_samples=lookback_bars).shift(1).alias("my"),
            pl.col("cross").rolling_mean(lookback_bars, min_samples=lookback_bars).shift(1).alias("mxy"),
            pl.col("xau_sq").rolling_mean(lookback_bars, min_samples=lookback_bars).shift(1).alias("mx2"),
        )
        .with_columns(
            ((pl.col("mxy") - pl.col("mx") * pl.col("my")) /
             (pl.col("mx2") - pl.col("mx").pow(2))).alias(BETA_COLUMN)
        )
        .with_columns(pl.col(BETA_COLUMN).abs().alias(BETA_COLUMN))
        .with_columns(
            pl.when(pl.col(BETA_COLUMN).is_finite() & pl.col(BETA_COLUMN).is_between(0.1, 3.0))
            .then(pl.col(BETA_COLUMN)).otherwise(None).alias(BETA_COLUMN)
        )
        .select("timestamp", BETA_COLUMN)
    )
    return panel.join(wide, on="timestamp", how="inner").sort(["symbol", "timestamp"])


def prepare(cfg: dict) -> pl.DataFrame:
    raw = _read_source(cfg)
    panel = make_two_minute_panel(raw)
    lookback = int(cfg["evaluation"]["beta_estimation_bars_2m"])
    enriched = add_beta(panel, lookback)
    if enriched.filter(pl.col(BETA_COLUMN).is_not_null()).is_empty():
        raise ValueError("Beta warm-up not reached")
    return enriched


def save_phase2(panel: pl.DataFrame) -> Path:
    FEATURE_DIR.mkdir(parents=True, exist_ok=True)
    path = FEATURE_DIR / "paired_2m_beta.parquet"
    panel.write_parquet(path)
    beta = panel.filter(pl.col(BETA_COLUMN).is_not_null())
    manifest = {
        "session_id": SESSION,
        "frozen_sha256": json.loads((RUN_DIR / "frozen_spec.json").read_text())["frozen_sha256"],
        "artifact": str(path.relative_to(ROOT)),
        "sha256": _sha256(path),
        "rows": panel.height,
        "columns": panel.columns,
        "schema": {name: str(dtype) for name, dtype in panel.schema.items()},
        "first_utc": str(panel["timestamp"].min()),
        "last_utc": str(panel["timestamp"].max()),
        "first_beta_utc": str(beta["timestamp"].min()),
        "beta_ready_timestamp_count": beta["timestamp"].n_unique(),
    }
    (RUN_DIR / "phase2_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return path


def _verify_frozen() -> dict:
    spec_path = RUN_DIR / "frozen_spec.json"
    if not spec_path.is_file():
        raise RuntimeError("Run --phase freeze before computing research artifacts")
    spec = json.loads(spec_path.read_text())
    if spec["config_sha256"] != _sha256(CFG_PATH) or spec["runner_sha256"] != _sha256(Path(__file__)):
        raise RuntimeError("Frozen config or runner changed; freeze again before continuing")
    return spec


def load_phase2() -> pl.DataFrame:
    spec = _verify_frozen()
    manifest_path = RUN_DIR / "phase2_manifest.json"
    artifact = FEATURE_DIR / "paired_2m_beta.parquet"
    if not manifest_path.is_file() or not artifact.is_file():
        raise RuntimeError("Run --phase 2 before diagnostics or backtesting")
    manifest = json.loads(manifest_path.read_text())
    if manifest["frozen_sha256"] != spec["frozen_sha256"] or manifest["sha256"] != _sha256(artifact):
        raise RuntimeError("Phase 2 artifact does not match the frozen inputs")
    panel = pl.read_parquet(artifact)
    if panel.height != manifest["rows"] or panel.columns != manifest["columns"]:
        raise RuntimeError("Phase 2 artifact schema or row count changed")
    return panel


def paired_wide(panel: pl.DataFrame) -> pl.DataFrame:
    return panel.pivot(
        on="symbol", index="timestamp", values=["open", "high", "low", "close", "volume", BETA_COLUMN]
    ).sort("timestamp")


def run_diagnostics(panel: pl.DataFrame, cfg: dict) -> dict:
    wide = paired_wide(panel).filter(pl.col(BETA_COLUMN + "_XAU").is_not_null())
    if wide.is_empty():
        raise ValueError("No warmed beta observations")
    # The beta is one paired-series risk descriptor, not a cross-sectional alpha.
    # Use non-overlapping 30-minute forward residuals as a descriptive stability check.
    wide = wide.with_columns(
        (pl.col("close_XAU").log().shift(-15) - pl.col("close_XAU").log()).alias("fwd_xau_30m"),
        (pl.col("close_XAG").log().shift(-15) - pl.col("close_XAG").log()).alias("fwd_xag_30m"),
    ).with_columns(
        (pl.col("fwd_xag_30m") - pl.col(BETA_COLUMN + "_XAU") * pl.col("fwd_xau_30m")).alias("fwd_beta_residual_30m")
    ).filter((pl.col("timestamp").dt.minute() % 30 == 0) & pl.col("fwd_beta_residual_30m").is_not_null())
    profile = quantile_profile(
        wide.select("timestamp", (pl.col(BETA_COLUMN + "_XAU")).alias("beta"), "fwd_beta_residual_30m"),
        feature="beta", label="fwd_beta_residual_30m", n_quantiles=5, by=None, min_per_bucket=20,
    )
    beta_frame = panel.filter(pl.col(BETA_COLUMN).is_not_null()).unique("timestamp")
    beta_values = beta_frame.select(BETA_COLUMN).to_series()
    report = {
        "session_id": SESSION,
        "diagnostic": "rolling beta stability; descriptive quantiles of non-overlapping 30m forward residuals",
        "beta_observations": beta_frame.height,
        "beta_min": float(beta_values.min()),
        "beta_median": float(beta_values.median()),
        "beta_max": float(beta_values.max()),
        "sample_start_utc": str(panel["timestamp"].min()),
        "sample_end_utc": str(panel["timestamp"].max()),
        "quantile_profile": repr(profile),
        "interpretation": "Descriptive risk diagnostic only; it does not establish grid profitability or justify beta tuning.",
        "decision": "Beta rule is computationally testable; economic value remains for the preregistered A/B run.",
    }
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    target = RUN_DIR / "phase3_diagnostic.json"
    target.write_text(json.dumps(report, indent=2, default=str) + "\n")
    return report


def _limit_qty(notional: float, price: float, lot: float) -> float:
    return math.floor((notional / price + 1e-12) / lot) * lot


class DualGrid(Strategy):
    """Independent one-lot-per-level grids; every order is a native resting limit."""
    def __init__(self, arm: str, cfg: dict):
        super().__init__()
        self.arm = arm
        self.cfg = cfg
        self.cap = cfg["capital"]
        self.grid = cfg["strategy"]
        self.exec_cfg = cfg["execution"]
        self.anchors: dict[str, float] = {}
        self.levels: dict[tuple[str, int], dict] = {}
        self.order_meta: dict[str, tuple[str, int, str]] = {}
        self.fill_cursor = 0
        self.bar = 0
        self.high_water = float(self.cap["initial_margin_usdc"])
        self.max_drawdown = 0.0
        self.halted = False
        self.halt_bar: int | None = None
        self.maker_notional = 0.0
        self.completed_notional = 0.0
        self.completed_cycles = 0
        self.emergency_notional = 0.0
        self.emergency_cost = 0.0
        self.opening_notional = defaultdict(float)
        self.close_notional = defaultdict(float)
        self.position_qty = defaultdict(float)
        self.unfilled_emergency = 0
        self.rejected_emergency_orders = 0
        self.max_gross = 0.0

    def _submit(
        self, broker, symbol: str, level: int, role: str, quantity: float, price: float
    ) -> bool:
        if not quantity or not math.isfinite(price) or (role != "emergency" and price <= 0):
            return False
        if role == "emergency":
            order = broker.close_position(
                symbol,
                order_type=OrderType.MARKET,
                _options=SubmitOrderOptions(
                    eligible_in_next_bar_mode=True,
                    risk_exit_reason="grid_risk_stop",
                    exit_reason=ExitReason.RISK_LIQUIDATION,
                ),
            )
        else:
            order = broker.submit_order(symbol, quantity, order_type=OrderType.LIMIT, limit_price=price)
        if order is None:
            if role == "emergency":
                self.rejected_emergency_orders += 1
            return False
        if order.status == OrderStatus.PENDING or role == "emergency":
            self.order_meta[order.order_id] = (symbol, level, role)
            self.levels[(symbol, level)][role + "_id"] = order.order_id
            if role == "emergency" and order.status == OrderStatus.REJECTED:
                self.rejected_emergency_orders += 1
        return order.status == OrderStatus.PENDING

    def _cancel_pending(self, broker) -> None:
        for oid in list(self.order_meta):
            order = broker.get_order(oid)
            if order is not None and order.status == OrderStatus.PENDING:
                broker.cancel_order(oid)
    def _cancel_grid_orders(self, broker) -> None:
        for oid, (_symbol, _level, role) in list(self.order_meta.items()):
            order = broker.get_order(oid)
            if role != "emergency" and order is not None and order.status == OrderStatus.PENDING:
                broker.cancel_order(oid)

    def _flatten(self, broker) -> None:
        for symbol in ASSETS:
            qty = self.position_qty[symbol]
            if abs(qty) <= 1e-10:
                continue
            state = self.levels.setdefault((symbol, -1), {})
            oid = state.get("emergency_id")
            order = broker.get_order(oid) if oid else None
            if order is not None and order.status == OrderStatus.PENDING:
                continue
            self._submit(broker, symbol, -1, "emergency", -qty, 0.0)

    def _consume_fills(self, broker, marks: dict[str, float]) -> None:
        for fill in broker.fills[self.fill_cursor:]:
            meta = self.order_meta.get(fill.order_id)
            if meta is None:
                continue
            symbol, level, role = meta
            order = broker.get_order(fill.order_id)
            if order is None:
                continue
            qty = float(fill.quantity) * (1 if order.side == OrderSide.BUY else -1)
            notional = abs(qty * float(fill.price))
            if role == "emergency":
                self.emergency_notional += notional
                cost_bps = self.exec_cfg["emergency_taker_fee_bps"] + self.exec_cfg["emergency_slippage_bps"]
                self.emergency_cost += notional * cost_bps / 10_000
                self.position_qty[symbol] += qty
            else:
                self.maker_notional += notional
                state = self.levels[(symbol, level)]
                if role == "entry":
                    state.update(
                        qty=qty,
                        entry_price=float(fill.price),
                        rearm_price=float(fill.price),
                        entry_bar=self.bar,
                        entry_notional=notional,
                    )
                    self.position_qty[symbol] += qty
                    self.opening_notional[symbol] += notional
                    self._submit(broker, symbol, level, "exit", -qty, float(fill.price))
                elif role == "exit":
                    self.position_qty[symbol] += qty
                    self.close_notional[symbol] += notional
                    self.completed_notional += float(state["entry_notional"]) + notional
                    self.completed_cycles += 1
                    state.update(qty=0.0, entry_price=None, entry_bar=None, entry_notional=0.0)
            if order.status != OrderStatus.PENDING:
                self.order_meta.pop(fill.order_id, None)
        self.fill_cursor = len(broker.fills)

    def _risk(self, broker, marks: dict[str, float]) -> tuple[float, float]:
        gross = sum(abs(self.position_qty[symbol] * marks[symbol]) for symbol in ASSETS)
        reserved = 0.0
        for oid, (_symbol, _level, role) in list(self.order_meta.items()):
            order = broker.get_order(oid)
            if order is None or order.status != OrderStatus.PENDING:
                self.order_meta.pop(oid, None)
                continue
            if role == "entry":
                reserved += abs(float(order.quantity) * float(order.limit_price))
        self.max_gross = max(self.max_gross, gross + reserved)
        equity = float(broker.get_account_value()) - self.emergency_cost
        self.high_water = max(self.high_water, equity)
        self.max_drawdown = max(self.max_drawdown, self.high_water - equity)
        if not self.halted and (
            self.max_drawdown >= self.cap["max_drawdown_usdc"]
            or gross + reserved > self.cap["max_gross_notional_usdc"]
        ):
            self.halted = True
            self.halt_bar = self.bar
            self._cancel_grid_orders(broker)
            self._flatten(broker)
        return gross, reserved
    def on_data(self, timestamp, data, context, broker):
        self.bar += 1
        if not all(symbol in data for symbol in ASSETS):
            return
        marks = {symbol: float(data[symbol]["close"]) for symbol in ASSETS}
        self._consume_fills(broker, marks)
        beta = context.get(BETA_COLUMN)
        if beta is None or not math.isfinite(float(beta)):
            return
        if not self.anchors:
            self.anchors = marks.copy()
            for symbol in ASSETS:
                for level in range(1, int(self.grid["levels_per_leg"]) + 1):
                    self.levels[(symbol, level)] = {
                        "qty": 0.0,
                        "entry_price": None,
                        "entry_bar": None,
                        "entry_notional": 0.0,
                        "target_qty": 0.0,
                    }
        gross, reserved = self._risk(broker, marks)
        if self.halted:
            self._cancel_grid_orders(broker)
            self._flatten(broker)
            return
        exposure = gross + reserved
        levels = int(self.grid["levels_per_leg"])
        base_spacing = float(self.grid["spacing_bps"]) / 10_000
        beta_scale = float(beta) if self.arm == "B" else 1.0
        for symbol in ASSETS:
            side = 1 if symbol == "XAU" else -1
            lot_step = float(self.cfg["order"]["quantity_rounding_by_asset"][symbol])
            tick = float(self.cfg["order"]["price_tick_by_asset"][symbol])
            for level in range(1, levels + 1):
                state = self.levels[(symbol, level)]
                if state.get("qty", 0.0):
                    continue
                entry_id = state.get("entry_id")
                order = broker.get_order(entry_id) if entry_id else None
                pending = order is not None and order.status == OrderStatus.PENDING
                if pending and state.get("rearm_price") is None and self.arm == "B" and symbol == "XAG":
                    desired = self.anchors[symbol] * (1 + level * base_spacing * beta_scale)
                    desired = round(round(desired / tick) * tick, 8)
                    if entry_id is not None and order is not None and abs(float(order.limit_price) - desired) >= tick:
                        broker.cancel_order(entry_id)
                        self.order_meta.pop(entry_id, None)
                        exposure -= abs(float(order.quantity) * float(order.limit_price))
                        state["entry_id"] = None
                        pending = False
                if pending:
                    continue
                step = base_spacing * (beta_scale if symbol == "XAG" else 1.0)
                anchor = self.anchors[symbol]
                price = anchor * (1 - level * step) if side > 0 else anchor * (1 + level * step)
                rearm_price = state.get("rearm_price")
                if rearm_price is not None:
                    price = float(rearm_price)
                price = round(round(price / tick) * tick, 8)
                qty = (
                    float(state["target_qty"])
                    if rearm_price is not None
                    else _limit_qty(self.cap["quantity_per_level_usdc"], price, lot_step)
                )
                notional = abs(qty * price)
                if qty <= 0 or exposure + notional > self.cap["max_gross_notional_usdc"]:
                    continue
                if self._submit(broker, symbol, level, "entry", side * qty, price):
                    state["target_qty"] = qty
                    exposure += notional
        self.max_gross = max(self.max_gross, exposure)
    def on_end(self, broker):
        for oid, (_symbol, _level, role) in self.order_meta.items():
            order = broker.get_order(oid)
            if role == "emergency" and order is not None and order.status == OrderStatus.PENDING:
                self.unfilled_emergency += 1
        self._cancel_pending(broker)


def _engine_feed(panel: pl.DataFrame, cfg: dict) -> tuple[pl.DataFrame, pl.DataFrame]:
    wide = paired_wide(panel).filter(pl.col(BETA_COLUMN + "_XAU").is_not_null())
    start = datetime.fromisoformat(cfg["evaluation"]["start_utc"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(cfg["evaluation"]["end_exclusive_utc"].replace("Z", "+00:00"))
    wide = wide.filter((pl.col("timestamp") >= start) & (pl.col("timestamp") < end))
    pieces = []
    for symbol in ASSETS:
        suffix = "_" + symbol
        pieces.append(wide.select(
            "timestamp", pl.lit(symbol).alias("symbol"),
            pl.col("open" + suffix).alias("open"), pl.col("high" + suffix).alias("high"),
            pl.col("low" + suffix).alias("low"), pl.col("close" + suffix).alias("close"),
            pl.col("volume" + suffix).alias("volume"),
        ))
    prices = pl.concat(pieces).sort(["timestamp", "symbol"])
    context = wide.select("timestamp", pl.col(BETA_COLUMN + "_XAU").alias(BETA_COLUMN))
    return prices, context


def run_arm(panel: pl.DataFrame, cfg: dict, arm: str) -> dict:
    prices, context = _engine_feed(panel, cfg)
    volume_gate = SharedVolumeBudget(
        participation=float(cfg["execution"]["max_bar_volume_participation"]),
        partial=bool(cfg["execution"]["partial_fills"]),
        lot_steps=cfg["order"]["quantity_rounding_by_asset"],
    )
    strategy = DualGrid(arm, cfg)
    engine_cfg = BacktestConfig(
        initial_cash=float(cfg["capital"]["initial_margin_usdc"]),
        share_type=ShareType.FRACTIONAL,
        allow_short_selling=True,
        allow_leverage=True,
        execution_mode=ExecutionMode.NEXT_BAR,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=float(cfg["execution"]["maker_fee_bps"]) / 10_000,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=0.0,
        partial_fills_allowed=False,
    )
    engine = Engine(
        DataFeed(prices_df=prices, context_df=context, entity_col="symbol", timestamp_col="timestamp"),
        strategy,
        engine_cfg,
        execution_limits=volume_gate,
    )
    volume_gate.bind(engine.broker)
    started = time.monotonic()
    engine.run()
    elapsed = time.monotonic() - started
    ending_marks = {symbol: float(engine.broker.get_last_price(symbol)) for symbol in ASSETS}
    ending_inventory = {symbol: strategy.position_qty[symbol] * ending_marks[symbol] for symbol in ASSETS}
    unfinished = sum(abs(value) for value in ending_inventory.values())
    equity = float(engine.equity_curve[-1][1]) if engine.equity_curve else float(cfg["capital"]["initial_margin_usdc"])
    net_pnl = equity - float(cfg["capital"]["initial_margin_usdc"]) - strategy.emergency_cost
    metric = (
        strategy.completed_notional / strategy.max_drawdown
        if strategy.max_drawdown > 0
        else None
    )
    return {
        "arm": arm,
        "elapsed_seconds": round(elapsed, 2),
        "bars_per_symbol": prices.height // 2,
        "maker_fill_notional_usdc": round(strategy.maker_notional, 4),
        "completed_maker_volume_usdc": round(strategy.completed_notional, 4),
        "maker_volume_per_max_drawdown": round(metric, 4) if metric is not None else None,
        "completed_grid_cycles": strategy.completed_cycles,
        "net_mark_to_market_pnl_usdc": round(net_pnl, 4),
        "max_drawdown_usdc": round(strategy.max_drawdown, 4),
        "max_gross_plus_reserved_usdc": round(strategy.max_gross, 4),
        "ending_inventory_notional_usdc": {k: round(v, 4) for k, v in ending_inventory.items()},
        "unfinished_inventory_usdc": round(unfinished, 4),
        "emergency_taker_notional_usdc": round(strategy.emergency_notional, 4),
        "rejected_emergency_orders": strategy.rejected_emergency_orders,
        "risk_halted": strategy.halted,
        "risk_halt_bar": strategy.halt_bar,
        "volume_gate_ambiguities": volume_gate.ambiguous,
        "volume_gate_max_overshoot": volume_gate.max_overshoot,
        "maker_volume_fraction_completed": (
            round(strategy.completed_notional / strategy.maker_notional, 6)
            if strategy.maker_notional > 0
            else None
        ),
        "unfilled_emergency_orders": strategy.unfilled_emergency,
        "terminal_inventory_mark_only": True,
    }


def run_phase4(panel: pl.DataFrame, cfg: dict) -> dict:
    arms = [run_arm(panel, cfg, "A"), run_arm(panel, cfg, "B")]
    result = {
        "session_id": SESSION,
        "status": "EXPLORATORY_NOT_APPROVED",
        "primary_metric": "completed_maker_volume_usdc_per_max_drawdown_usdc",
        "arms": arms,
        "comparison": {
            "B_minus_A_primary_metric": (
                round(arms[1]["maker_volume_per_max_drawdown"] - arms[0]["maker_volume_per_max_drawdown"], 4)
                if all(arm["maker_volume_per_max_drawdown"] is not None for arm in arms)
                else None
            ),
            "primary_metric_winner": (
                max(arms, key=lambda arm: arm["maker_volume_per_max_drawdown"])["arm"]
                if all(arm["maker_volume_per_max_drawdown"] is not None for arm in arms)
                else None
            ),
        },
        "limitations": [
            "Historical OHLCV touch fills do not model queue position or passive fill probability.",
            "Funding history was unavailable and excluded.",
            "The full period was previously inspected in related Lighter grid studies; this is not an untouched holdout.",
            "Ending inventory is marked, not liquidated; emergency costs apply only to actual risk-stop market fills.",
            "Per-lot breakeven exits create no planned gross price profit; results screen volume generation and inventory risk, not strategy profitability.",
        ],
    }
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    (RUN_DIR / "phase4_ab_result.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("freeze", "2", "3", "4"), required=True)
    args = parser.parse_args()
    cfg = yaml.safe_load(CFG_PATH.read_text())
    if args.phase == "freeze":
        print(freeze(cfg))
        return
    _verify_frozen()
    if args.phase == "2":
        panel = prepare(cfg)
        path = save_phase2(panel)
        beta_ready = panel.filter(pl.col(BETA_COLUMN).is_not_null())
        print(json.dumps({
            "feature_path": str(path.relative_to(ROOT)),
            "rows": panel.height,
            "beta_ready_timestamp_count": beta_ready["timestamp"].n_unique(),
            "phase2_manifest": str((RUN_DIR / "phase2_manifest.json").relative_to(ROOT)),
        }, indent=2))
        return
    panel = load_phase2()
    if args.phase == "3":
        print(json.dumps(run_diagnostics(panel, cfg), indent=2, default=str))
    else:
        print(json.dumps(run_phase4(panel, cfg), indent=2, default=str))


if __name__ == "__main__":
    main()
