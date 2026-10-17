"""Event-driven, frozen SPY/QQQ grid comparison using ml4t.backtest.

Exploratory risk experiment, NOT maker-execution backtest: CCXT provides 1m
OHLCV without historical order books or queue position. All fills are next-bar
market fills with explicit friction. Nothing here can place live orders.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import yaml
from ml4t.backtest import BacktestConfig, DataFeed, Engine, Strategy
from ml4t.backtest.config import CommissionType, ShareType, SlippageType
from ml4t.backtest.types import ExecutionMode

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config/research_sessions/lighter_spy_qqq_pair_grid_20261009.yaml"
OUTPUT_DIR = ROOT / "run_log/lighter_spy_qqq_pair_grid_20261009"


def as_utc(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(UTC)


@dataclass
class Layer:
    uid: int
    price: float
    quantity: float
    created_bar: int


class GridComparisonStrategy(Strategy):
    """Market-order proxy for one-sided grids and coordinated beta-neutral pairs."""

    def __init__(self, mode: str, params: dict, beta: float):
        super().__init__()
        if mode not in ("solo", "independent", "paired"):
            raise ValueError(mode)
        self.mode = mode
        self.cfg = params
        self.beta = beta
        self.bar_no = 0
        self.layers: dict[str, list[Layer]] = {"SPY": [], "QQQ": []}
        self.pending: dict[str, dict] = {}
        self.last_fill_idx = 0
        self.next_uid = 1
        self.last_add_bar = {"SPY": -10**9, "QQQ": -10**9}
        self.pair_count = 0
        self.pair_direction = 0
        self.pair_created_bar = 0
        self.last_pair_add = -10**9
        self.pair_partial: dict | None = None
        self.exit_pending_bar: int | None = None
        self.halted = False
        self.kill_reason: str | None = None
        self.highwater = float(self.cfg["initial_cash_usdc"])
        self.orphan_events = 0
        self.unknown_fills = 0
        self.order_failures = 0
        self.layer_entries = 0
        self.layer_exits = 0
        self.pair_entries = 0
        self.pair_exits = 0
        self.max_beta_residual_usdc = 0.0

    def _position_qty(self, broker, asset: str) -> float:
        pos = broker.get_position(asset)
        return float(pos.quantity) if pos else 0.0

    def _submit_dollars(self, broker, asset: str, signed_notional: float, kind: str, uid: int = 0):
        order = (
            broker.buy(asset, dollars=signed_notional)
            if signed_notional > 0
            else broker.sell(asset, dollars=-signed_notional)
        )
        if order is None:
            self.order_failures += 1
            return None
        self.pending[order.order_id] = {"kind": kind, "asset": asset, "uid": uid, "bar": self.bar_no}
        return order

    def _submit_quantity(self, broker, asset: str, signed_qty: float, kind: str, uid: int = 0):
        order = broker.submit_order(asset, signed_qty)
        if order is None:
            self.order_failures += 1
            return None
        self.pending[order.order_id] = {"kind": kind, "asset": asset, "uid": uid, "bar": self.bar_no}
        return order

    def _reconcile(self, broker) -> None:
        new_fills = broker.fills[self.last_fill_idx :]
        self.last_fill_idx = len(broker.fills)
        for fill in new_fills:
            ref = self.pending.pop(fill.order_id, None)
            if ref is None:
                self.unknown_fills += 1
                continue
            kind, asset = ref["kind"], ref["asset"]
            if kind == "grid_add":
                signed_qty = abs(float(fill.quantity)) * (1 if asset == "SPY" else -1)
                self.layers[asset].append(
                    Layer(uid=ref["uid"], price=float(fill.price), quantity=signed_qty, created_bar=self.bar_no)
                )
                self.layer_entries += 1
            elif kind == "grid_close":
                before = len(self.layers[asset])
                self.layers[asset] = [layer for layer in self.layers[asset] if layer.uid != ref["uid"]]
                if len(self.layers[asset]) != before - 1:
                    raise RuntimeError("grid layer exit not found")
                self.layer_exits += 1
            elif kind == "pair_add":
                if self.pair_partial is None or self.pair_partial["uid"] != ref["uid"]:
                    raise RuntimeError("unmatched pair execution")
                self.pair_partial["fills"][asset] = fill
                if len(self.pair_partial["fills"]) == 2:
                    self.pair_count += 1
                    self.pair_direction = self.pair_partial["direction"]
                    if self.pair_count == 1:
                        self.pair_created_bar = self.bar_no
                    self.pair_partial = None
                    self.pair_entries += 1
            elif kind in ("pair_close", "risk_close"):
                pass

    def _has_pending_asset(self, asset: str) -> bool:
        return any(ref["asset"] == asset for ref in self.pending.values())

    def _close_all(self, broker, reason: str) -> None:
        for asset in ("SPY", "QQQ"):
            qty = self._position_qty(broker, asset)
            if abs(qty) > 1e-9 and not self._has_pending_asset(asset):
                self._submit_quantity(broker, asset, -qty, "risk_close" if reason == "risk" else "pair_close")
        self.layers = {"SPY": [], "QQQ": []}
        if self.mode == "paired":
            self.pair_count = 0
            self.pair_direction = 0
            self.pair_partial = None
            if reason != "risk":
                self.pair_exits += 1
        self.exit_pending_bar = self.bar_no

    def _risk_check(self, broker) -> bool:
        equity = float(broker.get_account_value())
        self.highwater = max(self.highwater, equity)
        limit = float(self.cfg["max_drawdown_usdc"])
        if equity <= float(self.cfg["initial_cash_usdc"]) - limit or self.highwater - equity >= limit:
            if not self.halted:
                self.halted = True
                self.kill_reason = "strategy_loss_limit"
                self._close_all(broker, "risk")
            return False
        if self.halted:
            return False
        if self.exit_pending_bar is not None:
            if abs(self._position_qty(broker, "SPY")) < 1e-8 and abs(self._position_qty(broker, "QQQ")) < 1e-8:
                self.exit_pending_bar = None
            elif self.bar_no - self.exit_pending_bar >= 3:
                self.orphan_events += 1
                self.halted = True
                self.kill_reason = "unclosed_hedge_leg"
                self._close_all(broker, "risk")
                return False
        if self.pair_partial is not None and self.bar_no - self.pair_partial["bar"] >= 3:
            self.orphan_events += 1
            self.halted = True
            self.kill_reason = "orphan_pair"
            self._close_all(broker, "risk")
            return False
        if self.pending and min(ref["bar"] for ref in self.pending.values()) < self.bar_no - 3:
            self.halted = True
            self.kill_reason = "stale_order"
            self._close_all(broker, "risk")
            return False
        return not self.halted

    def _step_grid(self, asset: str, side: int, last_price: float, volume: float, broker) -> None:
        if volume <= 0 or self._has_pending_asset(asset):
            return
        layers = self.layers[asset]
        tp = float(self.cfg["take_profit_fraction"])
        for layer in layers:
            profitable = (
                last_price >= layer.price * (1 + tp)
                if side > 0
                else last_price <= layer.price * (1 - tp)
            )
            if profitable:
                self._submit_quantity(broker, asset, -layer.quantity, "grid_close", layer.uid)
                return

        if len(layers) >= int(self.cfg["max_levels"]):
            return
        if self.bar_no - self.last_add_bar[asset] < int(self.cfg["min_add_interval_bars"]):
            return
        step = float(self.cfg["grid_step_fraction"])
        adverse = (
            not layers
            or (last_price <= layers[-1].price * (1 - step) if side > 0
                else last_price >= layers[-1].price * (1 + step))
        )
        if not adverse:
            return
        uid = self.next_uid
        self.next_uid += 1
        notional = (
            float(self.cfg["base_gross_notional_per_level"]) if self.mode == "solo"
            else float(self.cfg["independent_leg_notional_per_level"])
        )
        order = self._submit_dollars(broker, asset, side * notional, "grid_add", uid)
        if order is not None:
            self.last_add_bar[asset] = self.bar_no

    def _step_pair(self, z: float, spy_vol: float, qqq_vol: float, broker) -> None:
        if not math.isfinite(z) or spy_vol <= 0 or qqq_vol <= 0:
            return
        if self.exit_pending_bar is not None or self.pending or self.pair_partial is not None:
            return

        if self.pair_count:
            if (
                self.pair_direction * z >= -float(self.cfg["zscore_exit"])
                or abs(z) >= float(self.cfg["zscore_stop"])
                or self.bar_no - self.pair_created_bar >= int(self.cfg["max_pair_hold_minutes"])
            ):
                self._close_all(broker, "pair")
                return
            direction = self.pair_direction
            threshold = float(self.cfg["zscore_entry"]) + float(self.cfg["zscore_add_step"]) * self.pair_count
            if self.pair_count >= int(self.cfg["max_levels"]) or direction * z > -threshold:
                return
        else:
            threshold = float(self.cfg["zscore_entry"])
            if abs(z) < threshold or abs(z) >= float(self.cfg["zscore_stop"]):
                return
            direction = 1 if z < 0 else -1

        if self.bar_no - self.last_pair_add < int(self.cfg["min_add_interval_bars"]):
            return
        gross = float(self.cfg["base_gross_notional_per_level"])
        spy_dollars = gross / (1.0 + self.beta)
        qqq_dollars = gross - spy_dollars
        uid = self.next_uid
        self.next_uid += 1
        self.pair_partial = {"uid": uid, "direction": direction, "bar": self.bar_no, "fills": {}}
        a = self._submit_dollars(broker, "SPY", direction * spy_dollars, "pair_add", uid)
        b = self._submit_dollars(broker, "QQQ", -direction * qqq_dollars, "pair_add", uid)
        if a is None or b is None:
            self.orphan_events += 1
            self.halted = True
            self.kill_reason = "pair_submission_failure"
            self._close_all(broker, "risk")
            return
        self.last_pair_add = self.bar_no

    def on_data(self, timestamp, data, context, broker) -> None:
        self.bar_no += 1
        self._reconcile(broker)
        if not self._risk_check(broker):
            return
        if "SPY" not in data or "QQQ" not in data:
            return
        spy = data["SPY"]
        qqq = data["QQQ"]
        spy_close = context.get("spy_prev")
        qqq_close = context.get("qqq_prev")
        if spy_close is None or qqq_close is None:
            return
        if self.mode == "solo":
            self._step_grid("SPY", 1, float(spy_close), float(spy.get("volume", 0)), broker)
        elif self.mode == "independent":
            self._step_grid("SPY", 1, float(spy_close), float(spy.get("volume", 0)), broker)
            self._step_grid("QQQ", -1, float(qqq_close), float(qqq.get("volume", 0)), broker)
        else:
            z = context.get("zscore")
            if z is not None:
                self._step_pair(float(z), float(spy.get("volume", 0)), float(qqq.get("volume", 0)), broker)

        sp_qty = self._position_qty(broker, "SPY")
        qq_qty = self._position_qty(broker, "QQQ")
        residual = abs(sp_qty * float(spy["close"]) * self.beta + qq_qty * float(qqq["close"]))
        self.max_beta_residual_usdc = max(self.max_beta_residual_usdc, residual)


def load_panel(config: dict):
    root = Path(config["source"]["data_root"])
    def load(symbol: str) -> pl.LazyFrame:
        return pl.scan_parquet(str(root / f"symbol={symbol}" / "**" / "data.parquet")).select(
            "timestamp",
            pl.col("open").alias(f"open_{symbol.lower()}"),
            pl.col("high").alias(f"high_{symbol.lower()}"),
            pl.col("low").alias(f"low_{symbol.lower()}"),
            pl.col("close").alias(f"close_{symbol.lower()}"),
            pl.col("volume").alias(f"volume_{symbol.lower()}"),
        )
    panel = load("SPY").join(load("QQQ"), on="timestamp", how="inner").sort("timestamp").collect()
    if panel["timestamp"].n_unique() != panel.height:
        raise ValueError("duplicate timestamps")
    if (panel["timestamp"].diff().drop_nulls() != timedelta(minutes=1)).sum() > 0:
        raise ValueError("missing timestamps after exchange listing")
    if panel["open_spy"].is_null().any() or panel["open_qqq"].is_null().any():
        raise ValueError("null candles")
    return panel


def estimate_beta(panel: pl.DataFrame, until: datetime) -> tuple[float, float, int]:
    calibration = panel.filter(pl.col("timestamp") < until)
    hourly = (
        calibration.group_by_dynamic("timestamp", every="1h")
        .agg(pl.col("close_spy").last(), pl.col("close_qqq").last())
        .sort("timestamp")
        .with_columns(
            pl.col("close_spy").log().diff().alias("r_spy"),
            pl.col("close_qqq").log().diff().alias("r_qqq"),
        )
        .drop_nulls()
    )
    spy = hourly["r_spy"].to_numpy()
    qqq = hourly["r_qqq"].to_numpy()
    beta = float(np.cov(qqq, spy, ddof=1)[0, 1] / np.var(qqq, ddof=1))
    corr = float(np.corrcoef(qqq, spy)[0, 1])
    if not 0.05 < beta < 2.0 or not np.isfinite(corr):
        raise ValueError(f"unsupported beta: {beta} corr={corr}")
    return beta, corr, hourly.height


def add_causal_signals(panel: pl.DataFrame, beta: float, lookback: int) -> pl.DataFrame:
    return (
        panel.with_columns(
            (pl.col("close_spy").log() - beta * pl.col("close_qqq").log()).alias("spread")
        )
        .with_columns(
            pl.col("spread").rolling_mean(window_size=lookback).shift(1).alias("spread_mean"),
            pl.col("spread").rolling_std(window_size=lookback).shift(1).alias("spread_std"),
            pl.col("spread").shift(1).alias("spread_prev"),
            pl.col("close_spy").shift(1).alias("spy_prev"),
            pl.col("close_qqq").shift(1).alias("qqq_prev"),
        )
        .with_columns(
            pl.when(pl.col("spread_std") > 1e-10)
            .then((pl.col("spread_prev") - pl.col("spread_mean")) / pl.col("spread_std"))
            .otherwise(None)
            .alias("zscore")
        )
    )


def make_feeds(panel: pl.DataFrame):
    assets = []
    for symbol in ("SPY", "QQQ"):
        assets.append(
            panel.select(
                "timestamp",
                pl.lit(symbol).alias("symbol"),
                pl.col(f"open_{symbol.lower()}").alias("open"),
                pl.col(f"high_{symbol.lower()}").alias("high"),
                pl.col(f"low_{symbol.lower()}").alias("low"),
                pl.col(f"close_{symbol.lower()}").alias("close"),
                pl.col(f"volume_{symbol.lower()}").alias("volume"),
            )
        )
    prices_df = pl.concat(assets).sort("timestamp", "symbol")
    context_df = panel.select("timestamp", "spy_prev", "qqq_prev", "zscore")
    return prices_df, context_df


def jsonable(obj):
    if isinstance(obj, (int, float, str, bool)) or obj is None:
        if isinstance(obj, float) and not math.isfinite(obj):
            return str(obj)
        return obj
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, np.generic):
        return obj.item()
    return str(obj)


def run_one(mode: str, prices_df: pl.DataFrame, context_df: pl.DataFrame, params: dict, cost: dict, beta: float):
    feed = DataFeed(prices_df=prices_df, context_df=context_df, entity_col="symbol", timestamp_col="timestamp")
    cfg = BacktestConfig(
        initial_cash=float(params["initial_cash_usdc"]),
        allow_short_selling=True,
        allow_leverage=True,
        share_type=ShareType.FRACTIONAL,
        execution_mode=ExecutionMode.NEXT_BAR,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=float(cost["commission_bps_per_fill"]) / 10_000,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=float(cost["slippage_bps_per_fill"]) / 10_000,
    )
    strategy = GridComparisonStrategy(mode=mode, params=params, beta=beta)
    engine = Engine(feed, strategy, cfg)
    started = time.monotonic()
    result = engine.run()
    elapsed = time.monotonic() - started
    equity = engine.equity_curve
    initial = float(params["initial_cash_usdc"])
    fills = engine.broker.fills
    out = {
        "mode": mode,
        "bars": len(equity),
        "duration_seconds": round(elapsed, 2),
        "initial_cash_usdc": initial,
        "ending_equity_usdc": round(float(equity[-1][1]), 5),
        "net_pnl_usdc": round(float(equity[-1][1]) - initial, 5),
        "metrics": jsonable(result.metrics),
        "fill_count": len(fills),
        "fill_notional_usdc": round(sum(abs(float(f.quantity) * float(f.price)) for f in fills), 3),
        "commission_paid_usdc": round(sum(float(f.commission) for f in fills), 4),
        "max_gross_exposure_usdc": round(max((row[3] for row in engine.portfolio_state), default=0), 3),
        "max_abs_net_dollar_exposure_usdc": round(max((abs(row[4]) for row in engine.portfolio_state), default=0), 3),
        "max_beta_residual_usdc": round(strategy.max_beta_residual_usdc, 3),
        "layer_entries": strategy.layer_entries,
        "layer_exits": strategy.layer_exits,
        "pair_entries": strategy.pair_entries,
        "pair_exits": strategy.pair_exits,
        "pending_orders_at_end": len(strategy.pending),
        "orphan_events": strategy.orphan_events,
        "unknown_fills": strategy.unknown_fills,
        "order_failures": strategy.order_failures,
        "halted": strategy.halted,
        "kill_reason": strategy.kill_reason,
        "end_open_positions": {
            asset: float(engine.broker.get_position(asset).quantity)
            for asset in ("SPY", "QQQ") if engine.broker.get_position(asset)
        },
    }
    print(json.dumps({"completed": mode, "seconds": out["duration_seconds"], "net_usdc": out["net_pnl_usdc"], "fills": out["fill_count"], "halted": out["halted"], "orphan": out["orphan_events"]}), flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, default=CONFIG_PATH)
    ap.add_argument("--phase", choices=("smoke", "development", "test"), default="smoke")
    ap.add_argument("--modes", nargs="+", choices=("solo", "independent", "paired"), default=["solo", "independent", "paired"])
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--cost-bps", type=float, default=None, help="Post-hoc sensitivity: combined fee and slippage bps per fill")
    args = ap.parse_args()
    conf = yaml.safe_load(args.config.read_text())
    data = load_panel(conf)
    ev = conf["evaluation"]
    beta, corr, n_cal = estimate_beta(data, as_utc(ev["calibration_end_exclusive"]))
    lookback = int(ev["spread_zscore_lookback_minutes"])
    enriched = add_causal_signals(data, beta, lookback)
    if args.phase == "smoke":
        start = as_utc(ev["development_start"])
        end = start + timedelta(days=3)
    elif args.phase == "development":
        start, end = as_utc(ev["development_start"]), as_utc(ev["development_end_exclusive"])
    else:
        start, end = as_utc(ev["test_start"]), as_utc(ev["test_end_exclusive"])
    sliced = enriched.filter((pl.col("timestamp") >= start) & (pl.col("timestamp") < end))
    if sliced.height < 1440:
        raise RuntimeError(f"insufficient data in {args.phase}: {sliced.height}")
    if sliced["zscore"].null_count() > 0:
        raise RuntimeError("uncalibrated spread score in run window")
    prices, context = make_feeds(sliced)
    print(json.dumps({"phase": args.phase, "start": start.isoformat(), "end": end.isoformat(), "bars_per_market": sliced.height, "beta_spy_vs_qqq": beta, "calibration_hourly_corr": corr, "calibration_hours": n_cal, "zero_volume_fraction": [float((sliced["volume_spy"]==0).mean()),float((sliced["volume_qqq"]==0).mean())]}), flush=True)
    costs = dict(conf["costs"])
    if args.cost_bps is not None:
        if not 0 <= args.cost_bps <= 20:
            raise ValueError("cost sensitivity must be 0..20 bps per fill")
        costs["commission_bps_per_fill"] = args.cost_bps / 2
        costs["slippage_bps_per_fill"] = args.cost_bps / 2
    report = {
        "effective_costs": costs,
        "post_hoc_cost_sensitivity": args.cost_bps is not None,
        "session_id": conf["session_id"],
        "status": conf["status"],
        "phase": args.phase,
        "start_utc": start.isoformat(),
        "end_utc": end.isoformat(),
        "minute_bars_per_market": sliced.height,
        "warmup_beta": beta,
        "warmup_correlation": corr,
        "warmup_hourly_bars": n_cal,
        "config": conf,
        "results": [run_one(mode, prices, context, conf["execution"], costs, beta) for mode in args.modes],
    }
    if not args.no_save:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        suffix = "_".join(args.modes) if len(args.modes) < 3 else "all"
        cost_suffix = "" if args.cost_bps is None else f"_cost{args.cost_bps:g}bps"
        out = OUTPUT_DIR / f"{args.phase}_{suffix}{cost_suffix}.json"
        out.write_text(json.dumps(jsonable(report), indent=2, sort_keys=True) + "\n")
        print("REPORT", out, flush=True)


if __name__ == "__main__":
    main()
