"""Seven independent native ML4T backtests on available local 2020-2022 data.

Strict separation: seven native Engine instances, seven results, no Shannon
portfolio optimization, no use of 2023+ data in feature computation.
This is an EXPLORATORY proxy test, not reproduction of archived Yahoo ETF PnL.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import math
import hashlib

import polars as pl
from ml4t.backtest import (
    Strategy, Engine, DataFeed, BacktestConfig, CommissionType,
    ExecutionMode, OrderType,
)
from ml4t.backtest.config import SlippageType, ShareType, StopFillMode
from src.strategies.independent_seven_data import load_daily
from src.strategies.independent_seven_native_features import FEATURE_BUILDERS

CASES = {
    "pivot-breakout-btc": ("BTC", 5.0, 2.0),
    "donchian-btc": ("BTC", 5.0, 2.0),
    "three-red-spy": ("ES", 2.0, 2.0),
    "gold-macd-hook": ("XAU", 3.0, 2.0),
    "slope-hook": ("ES", 2.0, 2.0),
    "fx-timing": ("ES", 2.0, 2.0),
    "rsi-30-50": ("ES", 2.0, 2.0),
}
START = datetime(2020, 1, 1, tzinfo=timezone.utc)
END = datetime(2023, 1, 1, tzinfo=timezone.utc)

def _positive(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(float(x)) and float(x) > 0


def _qty(broker, close: float, gross_fraction: float = .95) -> float:
    return max(0.0, float(broker.equity()) * gross_fraction / close)


class BinaryRule(Strategy):
    """Lifecycle: source entry/exit after complete bar; next open market fill."""
    def __init__(self, asset: str, *, max_bars: int | None = None):
        self.asset = asset
        self.max_bars = max_bars
        self.age = 0
        self.decisions = 0

    def on_data(self, timestamp, data, context, broker):
        bar = data.get(self.asset)
        if not bar:
            return
        sig = bar.get("signals") or {}
        price = float(bar["close"])
        if not _positive(price):
            return
        pos = broker.get_position(self.asset)
        current = float(pos.quantity) if pos else 0.0
        if current > 0:
            self.age += 1
            if bool(sig.get("exit_signal", False)) or (
                self.max_bars is not None and self.age >= self.max_bars
            ):
                broker.submit_order(self.asset, -current)
                self.decisions += 1
            return
        self.age = 0
        if bool(sig.get("entry_signal", False)):
            qty = _qty(broker, price)
            if qty > 0:
                broker.submit_order(self.asset, qty)
                self.decisions += 1


class ExposureRule(Strategy):
    """Native broker performs all long/short sizing, cash, fees and fills."""
    def __init__(self, asset: str):
        self.asset = asset
        self.decisions = 0

    def on_data(self, timestamp, data, context, broker):
        bar = data.get(self.asset)
        if not bar:
            return
        sig = bar.get("signals") or {}
        pct = sig.get("target_exposure")
        if pct is None or not math.isfinite(float(pct)):
            return
        price = float(bar["close"])
        equity = float(broker.equity())
        if not _positive(price) or not _positive(equity):
            return
        position = broker.get_position(self.asset)
        quantity = float(position.quantity) if position else 0.0
        target = equity * float(pct) / price
        delta = target - quantity
        if abs(delta) * price > 1.0:
            broker.submit_order(self.asset, delta)
            self.decisions += 1


class WeeklyProxyRule(Strategy):
    """FX momentum on EURUSD vs DXY; ES proxy or zero-yield cash."""
    def __init__(self, asset: str):
        self.asset = asset
        self.decisions = 0

    def on_data(self, timestamp, data, context, broker):
        bar = data.get(self.asset)
        if not bar:
            return
        sig = bar.get("signals") or {}
        if not bool(sig.get("week_last_session", False)):
            return
        pos = broker.get_position(self.asset)
        quantity = float(pos.quantity) if pos else 0.0
        if bool(sig.get("hold_spy_next_session", False)):
            if quantity == 0:
                broker.submit_order(self.asset, _qty(broker, float(bar["close"])))
                self.decisions += 1
        elif quantity > 0:
            broker.submit_order(self.asset, -quantity)
            self.decisions += 1


class PivotNativeStopRule(Strategy):
    """STOP breakout with broker-owned stop fill and protective exit.

    No assertion of exact archived intrabar execution. Protective stop
    is first installed when engine makes the filled position observable.
    """
    def __init__(self, asset: str):
        self.asset = asset
        self.entry_order: str | None = None
        self.stop_order: str | None = None
        self.stop_level: float | None = None
        self.entry_price: float | None = None
        self.profitable = False
        self.decisions = 0

    def _cancel(self, broker, oid: str | None):
        if oid and broker.get_order(oid):
            broker.cancel_order(oid)

    def on_data(self, timestamp, data, context, broker):
        bar = data.get(self.asset)
        if not bar:
            return
        sig = bar.get("signals") or {}
        close = float(bar["close"])
        pos = broker.get_position(self.asset)
        q = float(pos.quantity) if pos else 0.0
        pivot_h = sig.get("confirmed_pivot_high")
        pivot_l = sig.get("confirmed_pivot_low")
        if q > 0:
            self._cancel(broker, self.entry_order)
            self.entry_order = None
            if self.entry_price is None:
                self.entry_price = float(pos.entry_price)
                self.stop_level = float(pivot_l) if _positive(pivot_l) else None
            if _positive(pivot_l) and float(pivot_l) > self.entry_price:
                self.profitable = True
            if self.profitable and bool(sig.get("below_sma10", False)):
                self.stop_level = max(self.stop_level or 0.0, float(bar["low"]))
            if self.stop_level is None:
                return
            if self.stop_level >= close:
                self._cancel(broker, self.stop_order)
                self.stop_order = None
                broker.submit_order(self.asset, -q)
                self.decisions += 1
                return
            if self.stop_order and broker.get_order(self.stop_order):
                old = broker.get_order(self.stop_order)
                if float(old.stop_price) < self.stop_level:
                    broker.update_order(self.stop_order, stop_price=self.stop_level)
            else:
                order = broker.submit_order(
                    self.asset, -q, order_type=OrderType.STOP, stop_price=self.stop_level
                )
                if order:
                    self.stop_order = order.order_id
                    self.decisions += 1
            return

        self._cancel(broker, self.stop_order)
        self.stop_order = None
        self.stop_level = None
        self.entry_price = None
        self.profitable = False
        self._cancel(broker, self.entry_order)
        self.entry_order = None
        if not (_positive(pivot_h) and _positive(pivot_l)):
            return
        if close >= float(pivot_h) or close <= float(pivot_l):
            return
        sma = sig.get("sma50")
        if not _positive(sma) or close <= float(sma):
            return
        order = broker.submit_order(
            self.asset, _qty(broker, float(pivot_h)),
            order_type=OrderType.STOP, stop_price=float(pivot_h)
        )
        if order:
            self.entry_order = order.order_id
            self.decisions += 1


def _config(commission_bps: float, slippage_bps: float, *, leverage: bool = False) -> BacktestConfig:
    return BacktestConfig(
        initial_cash=100_000.0,
        execution_mode=ExecutionMode.NEXT_BAR,
        stop_fill_mode=StopFillMode.STOP_PRICE,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=commission_bps / 10_000.0,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=slippage_bps / 10_000.0,
        share_type=ShareType.FRACTIONAL,
        allow_short_selling=leverage,
        allow_leverage=leverage,
        initial_margin=0.5 if leverage else 1.0,
    )


def _safe(obj):
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    if isinstance(obj, dict):
        return {str(k): _safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe(x) for x in obj]
    if isinstance(obj, (int, float, str, bool)) or obj is None:
        return obj
    return str(obj)


def _build(case: str, data: dict[str, pl.DataFrame], *, start: datetime = START, end: datetime = END):
    asset, _, _ = CASES[case]
    if case == "fx-timing":
        # Explicit non-replication: EURUSD stands for FXE, DXY for UUP,
        # ES for SPY; BIL missing and modeled as idle zero-yield cash.
        f = FEATURE_BUILDERS[case]({
            "FXE": data["EUR"], "UUP": data["DXY"],
            "SPY": data["ES"], "BIL": data["ES"],
        })
        base = data["ES"].join(
            f.select("timestamp", "week_last_session", "hold_spy_next_session"),
            on="timestamp", how="inner"
        )
        strategy = WeeklyProxyRule(asset)
        fields = ["week_last_session", "hold_spy_next_session"]
    else:
        base = FEATURE_BUILDERS[case](data[asset])
        if case == "pivot-breakout-btc":
            strategy = PivotNativeStopRule(asset)
            fields = ["confirmed_pivot_high", "confirmed_pivot_low", "sma50", "below_sma10"]
        elif case == "donchian-btc":
            strategy = ExposureRule(asset)
            fields = ["target_exposure"]
        else:
            strategy = BinaryRule(asset, max_bars=10 if case == "gold-macd-hook" else None)
            fields = ["entry_signal", "exit_signal"]
    base = base.filter((pl.col("timestamp") >= start) & (pl.col("timestamp") < end))
    # Do not mutate signal values into future price data or vice versa.
    signals = base.select("timestamp", *fields).with_columns(asset=pl.lit(asset))
    prices = base.select("timestamp", "open", "high", "low", "close", "volume").with_columns(asset=pl.lit(asset))
    return prices, signals, strategy


def run_case(case: str, data: dict[str, pl.DataFrame], outroot: Path, manifests: dict):
    asset, commission_bps, slippage_bps = CASES[case]
    price, signals, strategy = _build(case, data)
    if price.height < 400:
        raise ValueError(f"{case}: not enough eligible sessions ({price.height})")
    # All order fills and accounting occur inside a native ML4T Engine.
    config = _config(commission_bps, slippage_bps, leverage=case == "donchian-btc")
    engine = Engine(DataFeed(prices_df=price, signals_df=signals), strategy, config)
    result = engine.run()
    folder = outroot / case
    folder.mkdir(parents=True, exist_ok=True)
    price.write_parquet(folder / "prices.parquet")
    signals.write_parquet(folder / "signals.parquet")
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    frozen = {"prices_sha256": digest(folder / "prices.parquet"),
              "signals_sha256": digest(folder / "signals.parquet")}
    result.to_equity_dataframe().write_csv(folder / "equity.csv")
    result.to_trades_dataframe().write_csv(folder / "trades.csv")
    result.to_fills_dataframe().write_csv(folder / "fills.csv")
    result.to_rejected_orders_dataframe().write_csv(folder / "rejected_orders.csv")
    summary = {
        "case": case, "status": "EXPLORATORY_PROXY",
        "period": ["2020-01-01", "2022-12-31"],
        "native_engine": "ml4t-backtest==0.1.7",
        "native_features": "ml4t-engineer==0.1.4",
        "asset": asset, "observations": price.height,
        "first": str(price["timestamp"].min()), "last": str(price["timestamp"].max()),
        "commission_bps_per_side": commission_bps,
        "slippage_bps_per_side": slippage_bps,
        "fills": len(result.fills), "closed_trades": len(result.trades),
        "rejected_orders": len(result.rejected_orders),
        "submitted_decisions": strategy.decisions,
        "frozen_artifact_hashes": frozen,
        "metrics": _safe(result.metrics),
        "sources": {key: manifests[key] for key in ({"BTC"} if asset == "BTC" else
                   ({"EUR", "DXY", "ES"} if case == "fx-timing" else {asset}))},
        "limitations": [
            "Independent seven strategy, NOT Shannon allocation",
            "No new independent holdout: 2020-2022 is observed historical development",
            "Completed daily OHLC signals, NEXT_BAR orders; original same-close results not replicated",
            "Costs are explicit research assumptions, not verified broker spreads",
            "Underlying ETFs absent from local ML4T-data; substitutes are not trade-equivalent",
            "BTC funding and leverage financing excluded",
            "ETF dividends / risk-free carry excluded",
        ],
    }
    (folder / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: summary[k] for k in ("case", "status", "observations", "fills", "closed_trades", "rejected_orders", "metrics")}, default=str))
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("run_log/independent_seven_2020_2022"))
    parser.add_argument("--case", choices=[*CASES, "all"], default="all")
    args = parser.parse_args()
    chosen = list(CASES) if args.case == "all" else [args.case]
    needed = {CASES[k][0] for k in chosen} | ({"EUR", "DXY", "ES"} if "fx-timing" in chosen else set())
    data, manifests = {}, {}
    for key in sorted(needed):
        data[key], manifests[key] = load_daily(key)
        print("DATA", json.dumps(manifests[key]), flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    reports = []
    for case in chosen:
        try:
            reports.append(run_case(case, data, args.out, manifests))
        except Exception as exc:
            import traceback
            path = args.out / case
            path.mkdir(parents=True, exist_ok=True)
            record = {"case": case, "status": "FAILED", "error": repr(exc), "traceback": traceback.format_exc()}
            (path / "error.json").write_text(json.dumps(record, indent=2))
            print("FAILED", case, str(exc), flush=True)
    (args.out / "manifest.json").write_text(json.dumps({
        "status": "EXPLORATORY", "period": ["2020-01-01", "2022-12-31"],
        "independent_cases": chosen, "completed": [x["case"] for x in reports],
        "data": manifests,
    }, indent=2))
    if len(reports) != len(chosen):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
