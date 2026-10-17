"""Uninterrupted long-SP500/SPY 20-limit-ladder + short-only passive beta hedge.

Two *separate venue experiments*: Hyperliquid HIP-3 index perps (~161 trading
days after warmup), and longer Lighter ETF-referenced perpetuals (~229 days).
Never join a position or continue accounting across different venues.
Uses ml4t.backtest.Engine and the tested 20-level FullLadder strategy.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import timedelta
from pathlib import Path

import polars as pl
import yaml
from ml4t.backtest.types import OrderStatus

from scripts.run_hyperliquid_xyz_full_ladder_ab_20261009 import (
    CFG_PATH,
    FullLadder,
    feed,
    make_panel,
    passive_price,
    prepare_beta,
    trial,
    utc,
)

ROOT = Path(__file__).resolve().parents[1]
CONF = ROOT / "config/research_sessions/continuous_long_grid_short_hedge_20261009.yaml"
REPORT_DIR = ROOT / "run_log/continuous_long_grid_short_hedge_20261009"


def dataset_panel(ds: dict, cfg: dict) -> pl.DataFrame:
    if ds["id"] == "hyperliquid_hip3":
        panel = make_panel(cfg)
    elif ds["id"] == "lighter_spy_qqq":
        root = Path(ds["path"])
        def load(symbol: str, logical: str) -> pl.LazyFrame:
            return pl.scan_parquet(str(root / f"symbol={symbol}" / "**" / "data.parquet")).select(
                "timestamp",
                *[pl.col(field).alias(f"{field}_{logical.lower()}") for field in ("open", "high", "low", "close", "volume")],
            )
        panel = (
            load("SPY", "SP500")
            .join(load("QQQ", "XYZ100"), on="timestamp", how="inner")
            .sort("timestamp")
            .collect()
        )
        panel = panel.with_columns(
            (pl.col("timestamp").diff() > timedelta(minutes=1))
            .fill_null(False)
            .alias("after_gap")
        )
    else:
        raise ValueError("Unknown dataset identity")

    if panel.is_empty() or panel["timestamp"].n_unique() != panel.height:
        raise ValueError("Null/duplicate or absent synchronized timestamps")
    for sym in ("sp500", "xyz100"):
        bad = panel.filter(
            (pl.col(f"high_{sym}") < pl.max_horizontal(f"open_{sym}", f"close_{sym}", f"low_{sym}"))
            | (pl.col(f"low_{sym}") > pl.min_horizontal(f"open_{sym}", f"close_{sym}", f"high_{sym}"))
            | (pl.col(f"close_{sym}") <= 0)
            | (pl.col(f"volume_{sym}") < 0)
            | pl.col(f"close_{sym}").is_null()
        ).height
        if bad:
            raise ValueError(f"OHLCV validation rejected {sym}: {bad} rows")
    return panel


def derive_run_config(base: dict, session: dict, ds: dict, partial: bool) -> dict:
    cfg = deepcopy(base)
    cap = session["portfolio"]
    assert cap["research_margin_usdc"] * cap["leverage_limit"] == cap["max_gross_notional_usdc"]
    assert cap["long_levels"] >= 20 and cap["long_clip_usdc"] == 100
    cfg["source"]["root"] = ds["path"]
    cfg["source"]["symbols"] = ["SP500", "XYZ100"]
    cfg["source"]["contracts_actual"] = ds["exact_contracts"]
    cfg["evaluation"]["calibration_end_utc"] = ds["calibration_end_exclusive"]
    cfg["capital"].update({
        "starting_cash_usdc": cap["research_margin_usdc"],
        "leverage": cap["leverage_limit"],
        "max_gross_usdc": cap["max_gross_notional_usdc"],
        "max_marked_gross_usdc": cap["max_gross_notional_usdc"],
        "max_per_leg_usdc": max(cap["long_max_plus_pending_usdc"], cap["max_short_plus_pending_usdc"]),
        "peak_to_trough_stop_usdc": cap["peak_to_trough_and_starting_loss_stop_usdc"],
        "global_drawdown_usdc": cap["peak_to_trough_and_starting_loss_stop_usdc"],
    })
    cfg["order"].update({
        "n_levels": cap["long_levels"],
        "clip_usdc": cap["long_clip_usdc"],
        "minimum_price_tick": ds["price_tick"],
        "minimum_price_tick_by_asset": ds["price_ticks_by_leg"],
        "quantity_rounding_by_asset": ds["quantity_steps_by_leg"],
        "minimum_order_notional_usdc": ds["minimum_notional_usdc"],
        "hedge_activation_clip_usdc": cap["hedge_clips_usdc"],
    })
    cfg["execution"]["volume_participation"] = session["execution"]["participation_fraction_of_total_1m_volume"]
    cfg["trials"] = [
        {"id": "LONG20_DYNAMIC_SHORT_HEDGE", "arm": "dynamic_hedge", "partial_fills": partial, "subbasket": False}
    ]
    return cfg


class HedgeFirstContinuous(FullLadder):
    """Never leave an independently unhedged short after exiting SP500.

    The short leg is opened ONLY in reaction to already-filled long exposure.
    Overhedged shorts may be reduced passively. Unwind XYZ100/QQQ shorts
    *before* posting final SP500/SPY long exits. A clean completion still
    requires the linked basket's realized cashflow >= modeled break-even.
    """

    def __init__(self, arm, cfg, beta_init, partial, subbasket, carry_bps):
        super().__init__(arm, cfg, beta_init, partial, subbasket, carry_bps)
        if self.arm != "A4":
            raise ValueError("Short-hedge-only design requires A4")
        self.orphan_short_streak = 0
        self.max_orphan_short_minutes = 0

    def _quote_hedge_only(self, marks, broker):
        b = self.baskets["pair"]
        long_qty = b.signed_qty["SP500"]
        short_qty = b.signed_qty["XYZ100"]
        price = marks["XYZ100"]
        target = max(0.0, self.beta * max(0.0, long_qty) * marks["SP500"])
        short_notional = max(0.0, -short_qty * price)
        min_clip = 10.0
        limit = self.o["hedge_activation_clip_usdc"]
        offset = self.o["hedge_quote_offset_bps"] / 10000
        # Remove stale short-making orders if current short exceeds target.
        for label in list(b.orders):
            if label.startswith("hedge:") and label != "hedge:reduce":
                oid = b.orders[label]
                meta = self.orders.get(oid)
                if meta is not None and meta.asset == "XYZ100" and meta.side == -1:
                    pending = sum(
                        abs(float(broker.get_order(other).quantity) * broker.get_order(other).limit_price)
                        for other, ref in self.orders.items()
                        if ref.role == "hedge" and ref.side == -1
                        and broker.get_order(other) is not None
                        and broker.get_order(other).status == OrderStatus.PENDING
                    )
                    if target + min_clip < short_notional + pending:
                        self._cancel(b, label, broker)
        pending_short = sum(
            abs(float(broker.get_order(oid).quantity) * broker.get_order(oid).limit_price)
            for oid, meta in self.orders.items()
            if meta.role == "hedge" and meta.side == -1
            and broker.get_order(oid) is not None and broker.get_order(oid).status == OrderStatus.PENDING
        )
        if short_notional > target + min_clip:
            for label in list(b.orders):
                if label.startswith("hedge:") and label != "hedge:reduce":
                    self._cancel(b, label, broker)
            # Risk-reducing cover, never increasing long XYZ100 exposure.
            clip = min(short_notional - target, limit, short_notional)
            px = passive_price(price * (1 - offset), 1, self.o["minimum_price_tick"])
            self._quote(
                b, "hedge:reduce", "hedge_reduce", "XYZ100",
                clip / px, px, -1, broker, marks,
            )
            return
        self._cancel(b, "hedge:reduce", broker)
        deficit = target - short_notional - pending_short
        if deficit < min_clip:
            self._cancel(b, "hedge:remainder", broker)
            return
        px = passive_price(price * (1 + offset), -1, self.o["minimum_price_tick"])
        desired = min(deficit, limit)
        # Guard the existing remainder as part of the shared hedge budget.
        oldid = b.orders.get("hedge:remainder")
        if oldid is not None:
            old = broker.get_order(oldid)
            if (old is not None and old.status == OrderStatus.PENDING
                    and abs(old.quantity * old.limit_price - desired) < min_clip):
                return
        self._cancel(b, "hedge:remainder", broker)
        self._quote(
            b, "hedge:remainder", "hedge", "XYZ100",
            -desired / px, px, -1, broker, marks,
        )

    def _exit_hedge_first(self, marks, broker):
        b = self.baskets["pair"]
        for label in list(b.orders):
            if label.startswith(("entry:", "hedge:")):
                self._cancel(b, label, broker)
        offset = self.o["maker_exit_offset_bps"] / 10000
        short = b.signed_qty["XYZ100"]
        if short < -1e-7:
            self._cancel(b, "exit:SP500", broker)
            # Keep the same resting passive cover limit until it fills.
            # Repegging it one tick below every new close can make it
            # chase a falling market forever and destroys queue priority.
            existing_id = b.orders.get("exit:XYZ100")
            if existing_id is not None:
                existing = broker.get_order(existing_id)
                if (existing is not None and existing.status == OrderStatus.PENDING
                        and abs(existing.quantity - abs(short)) < self.o["quantity_rounding"] * 2):
                    return
            px = passive_price(
                marks["XYZ100"] * (1 - offset), 1,
                self.o["minimum_price_tick"],
            )
            self._quote(
                b, "exit:XYZ100", "exit", "XYZ100",
                -short, px, -1, broker, marks,
            )
            return
        # No remaining short. Close only the long at the price that
        # recovers every recorded hedge cashflow and accumulated carry.
        self._cancel(b, "exit:XYZ100", broker)
        long = b.signed_qty["SP500"]
        if long > 1e-7:
            break_even = (
                b.carry + self.o["net_breakeven_reserve_usdc"] - b.cashflow
            ) / long
            required_floor = max(b.anchor["SP500"], break_even)
            existing_id = b.orders.get("exit:SP500")
            if existing_id is not None:
                existing = broker.get_order(existing_id)
                if (existing is not None and existing.status == OrderStatus.PENDING
                        and abs(existing.quantity - long) < self.o["quantity_rounding"] * 2
                        and existing.limit_price >= required_floor - 1e-8):
                    return
            px = max(required_floor, marks["SP500"] * (1 + offset))
            self._quote(
                b, "exit:SP500", "exit", "SP500",
                -long, px, -1, broker, marks,
            )

    def _linked(self, marks, context, broker):
        b = self.baskets["pair"]
        if b.phase != "exit":
            super()._linked(marks, context, broker)
        if b.phase == "exit":
            self._exit_hedge_first(marks, broker)
        elif b.signed_qty["SP500"] > 1e-7:
            self._quote_hedge_only(marks, broker)

    def on_data(self, timestamp, data, context, broker):
        super().on_data(timestamp, data, context, broker)
        b = self.baskets["pair"]
        if b.signed_qty["SP500"] < 1e-7 and b.signed_qty["XYZ100"] < -1e-7:
            self.orphan_short_streak += 1
            self.max_orphan_short_minutes = max(
                self.max_orphan_short_minutes, self.orphan_short_streak,
            )
        else:
            self.orphan_short_streak = 0


def consolidate_minutes(panel: pl.DataFrame, minutes: int) -> pl.DataFrame:
    """Coarsen a one-minute price path for a *separate*, clearly labeled test.

    For 5-minute bars, no information from the next 5-minute period enters
    the current bar. The engine still submits orders for the *following* bar.
    Fill/stop resolution is strictly less faithful than native 1m replay.
    """
    if minutes == 1:
        return panel
    if minutes != 5:
        raise ValueError("Only 1m and 5m are supported")
    exprs = [
        pl.len().alias("source_1m_rows"),
        pl.col("after_gap").any().alias("has_source_gap"),
    ]
    for sym in ("sp500", "xyz100"):
        exprs.extend([
            pl.col(f"open_{sym}").first().alias(f"open_{sym}"),
            pl.col(f"high_{sym}").max().alias(f"high_{sym}"),
            pl.col(f"low_{sym}").min().alias(f"low_{sym}"),
            pl.col(f"close_{sym}").last().alias(f"close_{sym}"),
            pl.col(f"volume_{sym}").sum().alias(f"volume_{sym}"),
        ])
    result = panel.group_by_dynamic(
        "timestamp", every=f"{minutes}m", period=f"{minutes}m"
    ).agg(exprs).sort("timestamp")
    return result.with_columns(
        (
            (pl.col("source_1m_rows") != minutes)
            | pl.col("has_source_gap")
            | (pl.col("timestamp").diff() > timedelta(minutes=minutes)).fill_null(False)
        ).alias("after_gap")
    ).drop("source_1m_rows", "has_source_gap")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, default=CONF)
    ap.add_argument("--dataset", choices=("hyperliquid_hip3", "lighter_spy_qqq", "both"), default="both")
    ap.add_argument("--carry-bps-day", type=float, choices=(0.0, 5.0), default=0.0)
    ap.add_argument("--no-partial", action="store_true", help="Sensitivity; baseline permits fills across multiple candles")
    ap.add_argument("--bar-minutes", type=int, choices=(1, 5), default=1, help="5m is only a coarse price-path sensitivity; default preserves 1m fidelity")
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args()
    spec = yaml.safe_load(args.config.read_text())
    base = yaml.safe_load(CFG_PATH.read_text())
    ds_list = [x for x in spec["datasets"] if args.dataset in (x["id"], "both")]
    if not ds_list:
        raise ValueError("No requested dataset")

    for ds in ds_list:
        cfg = derive_run_config(base, spec, ds, partial=not args.no_partial)
        panel = consolidate_minutes(dataset_panel(ds, cfg), args.bar_minutes)
        cfg["order"]["beta_update_minutes"] = max(1, 60 // args.bar_minutes)
        panel, beta, cal_hours = prepare_beta(panel, cfg)
        start, end = utc(ds["trading_start"]), utc(ds["trading_end_exclusive"])
        selection = panel.filter((pl.col("timestamp") >= start) & (pl.col("timestamp") < end))
        if selection.height * args.bar_minutes < 50000:
            raise ValueError("Not enough continuous underlying minutes for long-horizon experiment")
        prices, context = feed(selection, cfg)
        print(json.dumps({
            "event": "start_continuous", "market": ds["id"],
            "long_contract": ds["exact_contracts"][0], "hedge_contract": ds["exact_contracts"][1],
            "start": str(selection["timestamp"][0]), "last": str(selection["timestamp"][-1]),
            "sample_bars": selection.height, "bar_minutes": args.bar_minutes, "calendar_days": round((end-start).total_seconds()/86400, 2),
            "fitted_beta": beta, "calibration_hourly_samples": cal_hours,
            "DD_stop_usdc": cfg["capital"]["peak_to_trough_stop_usdc"],
            "gross_cap_usdc": cfg["capital"]["max_gross_usdc"],
            "long_levels": cfg["order"]["n_levels"], "clip_usdc": cfg["order"]["clip_usdc"],
            "carry_bps_day": args.carry_bps_day,
            "partial_fills": not args.no_partial,
        }), flush=True)
        row = trial(
            cfg, "LONG20_DYNAMIC_SHORT_HEDGE", prices, context, beta,
            carry_bps=args.carry_bps_day, strategy_class=HedgeFirstContinuous,
        )
        if args.bar_minutes > 1:
            basket = row["cycles"]["pair"]
            for metric in ("open_basket_age_minutes_approx", "holding_minutes_median",
                           "holding_minutes_p95", "longest_completed_holding_minutes_approx"):
                if basket.get(metric) is not None:
                    basket[metric] = round(basket[metric] * args.bar_minutes, 2)
        print(json.dumps({
            "event": "completed_continuous", "market": ds["id"],
            "clean_volume": row["completed_volume"], "candidate_volume": row["candidate_maker_volume"],
            "fills": row["maker_fill_events"], "hedge_fills": row["hedge_fill_events"],
            "max_dd": row["max_drawdown_usdc"], "net_pnl": row["net_pnl_ex_points"],
            "halt": row["risk_halt"], "halt_date": row.get("risk_halt_utc"),
            "end_open": row["cycles"]["pair"]["open_inventory_value"],
            "age_minutes": row["cycles"]["pair"]["open_basket_age_minutes_approx"],
            "med_hold_minutes": row["cycles"]["pair"]["holding_minutes_median"],
        }), flush=True)
        record = {
            "session_id": spec["session_id"],
            "status": spec["status"],
            "venue": ds["id"],
            "source_contracts": ds["exact_contracts"],
            "dataset_location": ds["path"],
            "trading_start": start.isoformat(),
            "trading_end_exclusive": end.isoformat(),
            "actual_first_bar": str(selection["timestamp"][0]),
            "actual_last_bar": str(selection["timestamp"][-1]),
            "bars": selection.height,
            "bar_minutes": args.bar_minutes,
            "calendar_days": (end-start).total_seconds() / 86400,
            "rolling_beta_calibrated_on_past": True,
            "initial_beta": beta,
            "calibration_hourly_bars": cal_hours,
            "research_config": spec,
            "full_run_config": cfg,
            "no_calendar_restart": True,
            "partial_fills": not args.no_partial,
            "coarsened_1m_history": args.bar_minutes > 1,
            "lot_size_limited": True,
            "exit_sequence": "HEDGE_FIRST_THEN_LONG_AT_NET_BREAKEVEN",
            "assumed_gross_carry_bps_per_day": args.carry_bps_day,
            "results": row,
            "caveat": "OHLCV limit penetration + shared-volume proxy, not proven maker execution, queue rank, Arcus fill rate or points. No liquidation engine. Two venues are separate experiments.",
        }
        if not args.no_save:
            REPORT_DIR.mkdir(parents=True, exist_ok=True)
            path = REPORT_DIR / (
                f"{ds['id']}_hedge_first_continuous_{'partial' if not args.no_partial else 'all_or_none'}"
                f"_carry{args.carry_bps_day:g}bps_{args.bar_minutes}m_lotaware.json"
            )
            path.write_text(json.dumps(record, indent=2, sort_keys=True, default=str) + "\n")
            print(f"REPORT {path}", flush=True)


if __name__ == "__main__":
    main()
