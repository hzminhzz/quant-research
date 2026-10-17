"""Mechanical Premia D1/H1 feature and native execution research adapter.

This is a CFD price-proxy implementation, not a verified MT5 reproduction.
No custom price/fill/account simulator: ML4T Engineer builds indicators and
ml4t.backtest.Engine owns orders, fills, cash, positions, equity and costs.
Only data before the existing frozen 2025-01-01 holdout can be read.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
from ml4t.engineer import compute_features
from ml4t.backtest import (
    BacktestConfig, DataFeed, Engine, Strategy, OrderType,
    ExecutionMode, CommissionType, StopFillMode,
)
from ml4t.backtest.config import SlippageType, ShareType

ROOT = Path(__file__).resolve().parents[1]
HOLDOUT = datetime(2025, 1, 1, tzinfo=timezone.utc)
FILES = {"ES_PROXY": ROOT / "data/processed/es_1m.parquet",
         "NQ_PROXY": ROOT / "data/processed/nq_1m.parquet"}
NY = "America/New_York"


def load_development(asset: str, *, until: datetime = HOLDOUT) -> pl.DataFrame:
    """Read ONLY the explicitly authorized historical development partition."""
    if until > HOLDOUT:
        raise ValueError("Protected final-test boundary: 2025-01-01 UTC")
    if asset not in FILES:
        raise ValueError(f"Unknown frozen proxy {asset}")
    frame = (pl.scan_parquet(FILES[asset])
             .filter(pl.col("timestamp") < pl.lit(until))
             .sort("timestamp")
             .select("timestamp", "open", "high", "low", "close", "volume")
             .collect())
    if frame.is_empty() or frame["timestamp"].n_unique() != frame.height:
        raise ValueError("Missing/duplicate authorized minute timestamps")
    bad = frame.filter(
        (pl.col("low") > pl.col("high"))
        | (pl.col("open") < pl.col("low"))
        | (pl.col("open") > pl.col("high"))
        | (pl.col("close") < pl.col("low"))
        | (pl.col("close") > pl.col("high"))
        | (pl.col("open") <= 0)
    )
    if bad.height:
        raise ValueError(f"{asset} has {bad.height} malformed OHLC rows")
    return frame.with_columns(asset=pl.lit(asset))


def _aggregate(prices: pl.DataFrame, group: str) -> pl.DataFrame:
    return (prices.group_by(group).agg(
        pl.col("timestamp").max().alias("timestamp"),
        pl.col("open").first(), pl.col("high").max(),
        pl.col("low").min(), pl.col("close").last(),
        pl.col("volume").sum(), pl.len().alias("minutes"))
        .sort("timestamp"))


def build_signals(prices: pl.DataFrame) -> pl.DataFrame:
    """Certified ML4T Engineer ATR/BB/EMA; causal custom median/%B expressions.

    Hourly decision occurs ONLY when all 60 minutes have completed.
    Daily CFD proxy session is 17:00 New York to 17:00 New York.
    Partial calendar sessions are excluded and not silently interpolated.
    Native engine sees the signals after the completed source-minute close,
    fills eligible market orders at the next minute open.
    """
    if prices["asset"].n_unique() != 1:
        raise ValueError("Compute independently per asset to prevent panel leakage")
    src = (prices.sort("timestamp")
           .with_columns(
               hkey=pl.col("timestamp").dt.truncate("1h"),
               ny=pl.col("timestamp").dt.convert_time_zone(NY))
           .with_columns(
               session=pl.when(pl.col("ny").dt.hour() >= 17)
               .then(pl.col("ny").dt.date() + pl.duration(days=1))
               .otherwise(pl.col("ny").dt.date())))

    hourly = _aggregate(src, "hkey").filter(pl.col("minutes") == 60).drop("hkey", "minutes")
    hourly = compute_features(hourly, [
        {"name": "atr", "params": {"period": 14}, "output": "atr14"},
        {"name": "bollinger_bands", "params":
         {"period": 40, "nbdevup": 2.0, "nbdevdn": 2.0}, "output": "bb40"},
    ])
    hourly = (hourly.with_columns(
        pl.col("atr14").rolling_quantile(quantile=0.5, interpolation="higher", window_size=100, min_samples=100).alias("atrmedian100"))
        .select("timestamp",
                pl.col("atr14").alias("h_atr"),
                ((pl.col("atr14") < pl.col("atrmedian100"))
                 & (pl.col("close") > pl.col("bb40").struct.field("upper")))
                .fill_null(False).alias("h_enter")))

    daily = _aggregate(src, "session").filter(pl.col("minutes") >= 1000).drop("session", "minutes")
    daily = compute_features(daily, [
        {"name": "atr", "params": {"period": 20}, "output": "atr20"},
        {"name": "ema", "params": {"period": 100}, "output": "ema100"},
        {"name": "bollinger_bands", "params":
         {"period": 10, "nbdevup": 3.0, "nbdevdn": 3.0}, "output": "bb10"},
    ])
    daily = (daily.with_columns(
        pl.col("atr20").rolling_quantile(quantile=0.5, interpolation="higher", window_size=100, min_samples=100).alias("atrmedian100"))
        .with_columns(
            pl.when(pl.col("bb10").struct.field("upper") >
                    pl.col("bb10").struct.field("lower"))
            .then((pl.col("close") - pl.col("bb10").struct.field("lower")) /
                  (pl.col("bb10").struct.field("upper") - pl.col("bb10").struct.field("lower")))
            .otherwise(None).alias("pctb")))
    daily = daily.select(
        "timestamp", pl.col("atr20").alias("d_atr"),
        ((pl.col("close") > pl.col("ema100"))
         & (pl.col("atr20") < pl.col("atrmedian100"))
         & (pl.col("pctb") < 0.2)).fill_null(False).alias("d_enter"),
        (pl.col("pctb") > 0.8).fill_null(False).alias("d_exit"),
    )
    # Completed higher-timeframe candle is seen on its final minute close.
    # Broker NEXT_BAR executes an entry no earlier than the next minute open.
    output = (prices.sort("timestamp").join(hourly, on="timestamp", how="left")
              .join(daily, on="timestamp", how="left")
              .with_columns(
                  pl.col("h_enter").fill_null(False),
                  pl.col("d_enter").fill_null(False),
                  pl.col("d_exit").fill_null(False),
                  pl.col("h_atr").forward_fill().alias("last_h_atr"),
                  pl.col("d_atr").forward_fill().alias("last_d_atr")))
    return output


@dataclass(frozen=True)
class PortfolioWeights:
    h: float
    d: float


TRIAL_WEIGHTS = {
    "H1-ONLY": PortfolioWeights(1.0, 0.0),
    "D1-ONLY": PortfolioWeights(0.0, 1.0),
    "PORTFOLIO-EQUAL-RISK": PortfolioWeights(0.5, 0.5),
    "PORTFOLIO-SOURCE-RISK": PortfolioWeights(0.2336, 0.7664),
}


class MechanicalPremiaStrategy(Strategy):
    """Native broker orders; custom logic only for generating order instructions.

    A separate stop order is installed after the H1 entry is confirmed by the
    broker. Native rule evaluation on the entry minute is NOT certified here;
    this one-minute protection gap is an explicit qualification blocker.
    """

    def __init__(self, weights: PortfolioWeights, asset_count: int):
        self.weights = weights
        self.per_asset_gross_cap = 1.90 / asset_count
        self.h_pending: dict[str, str] = {}
        self.h_stops: dict[str, str] = {}
        self.h_stop_levels: dict[str, float] = {}
        self.h_entry_count = 0
        self.d_entry_count = 0
        self.intent_rejects = 0
        self.last_h_signals: dict[str, float] = {}
        self.active_sleeve: dict[str, str] = {}
        self.reserved_risk: dict[str, float] = {}

    def on_data(self, timestamp, data, context, broker):
        for asset, bar in data.items():
            sg = bar.get("signals") or {}
            pos = broker.get_position(asset)
            qty = float(pos.quantity) if pos else 0.0
            sleeve = "h" if asset.endswith("_H") else "d"
            h_atr = sg.get("last_h_atr")
            d_atr = sg.get("last_d_atr")
            close = float(bar["close"])
            if not close > 0:
                continue

            if qty > 0 and self.active_sleeve.get(asset) == "h":
                # Native STOP sell, updated monotonically using prior closed H1 ATR.
                # A missing bid/ask series means close is a proxy for live bid.
                if h_atr is not None and h_atr > 0:
                    proposed = close - 2.0 * float(h_atr)
                    previous = self.h_stop_levels.get(asset)
                    existing = self.h_stops.get(asset)
                    if existing and broker.get_order(existing):
                        if (previous is not None and proposed > previous
                                and proposed < close and broker.update_order(
                                    existing, stop_price=proposed)):
                            self.h_stop_levels[asset] = proposed
                    elif proposed < close:
                        order = broker.submit_order(asset, -qty,
                                                    order_type=OrderType.STOP,
                                                    stop_price=proposed)
                        if order:
                            self.h_stops[asset] = order.order_id
                            self.h_stop_levels[asset] = proposed
                continue

            if qty > 0 and self.active_sleeve.get(asset) == "d":
                if bool(sg.get("d_exit", False)):
                    broker.submit_order(asset, -qty)
                continue

            if qty <= 0:
                # Cancel any stale H1 stop after the native stop filled.
                existing = self.h_stops.pop(asset, None)
                if existing:
                    broker.cancel_order(existing)
                self.h_stop_levels.pop(asset, None)
                self.active_sleeve.pop(asset, None)
                self.reserved_risk.pop(asset, None)
                h_go = (sleeve == "h" and bool(sg.get("h_enter", False))
                        and self.weights.h > 0)
                d_go = (sleeve == "d" and bool(sg.get("d_enter", False))
                        and self.weights.d > 0)
                if not h_go and not d_go:
                    continue
                atr = d_atr if sleeve == "d" else h_atr
                allocation = self.weights.d if sleeve == "d" else self.weights.h
                if atr is None or float(atr) <= 0:
                    self.intent_rejects += 1
                    continue
                # Unit multiplier=1 and fractional lots are NOT broker-certified.
                distance = float(atr) * (1 if sleeve == "d" else 2)
                equity = float(broker.equity())
                budget = max(0.0, min(equity * 0.01 * allocation,
                                      equity * 0.01 - sum(self.reserved_risk.values())))
                risk_qty = budget / distance
                # 2x gross-notional cap; cash/margin remains native Broker-owned.
                notional_cap_qty = self.per_asset_gross_cap * equity / close
                quantity = min(risk_qty, notional_cap_qty)
                if quantity <= 0:
                    self.intent_rejects += 1
                    continue
                order = broker.submit_order(asset, quantity)
                if order is not None:
                    self.reserved_risk[asset] = quantity * distance
                    self.active_sleeve[asset] = sleeve
                    if sleeve == "d":
                        self.d_entry_count += 1
                    else:
                        self.h_entry_count += 1


def run_native(frame: pl.DataFrame, trial_id: str,
               *, commission_bps: float = 1.0, slippage_bps: float = 2.0):
    """Run genuine native Engine with costs and real cash/fill/equity ledger."""
    if trial_id not in TRIAL_WEIGHTS:
        raise ValueError(f"Not a frozen trial: {trial_id}")
    if frame["timestamp"].max() >= HOLDOUT:
        raise ValueError("HOLDOUT_FORBIDDEN")
    weights = TRIAL_WEIGHTS[trial_id]
    # MT5 magic numbers permit simultaneous D1/H1 positions on the same index.
    # Distinct native broker instruments preserve those independent positions.
    legs = []
    if weights.h:
        legs.append(frame.with_columns(asset=pl.col("asset") + "_H"))
    if weights.d:
        legs.append(frame.with_columns(asset=pl.col("asset") + "_D"))
    expanded = pl.concat(legs).sort("timestamp", "asset")
    signals = expanded.select("timestamp", "asset", "h_enter", "d_enter", "d_exit",
                              "last_h_atr", "last_d_atr")
    price = expanded.select("timestamp", "asset", "open", "high", "low", "close", "volume")
    config = BacktestConfig(
        initial_cash=100_000.0,
        execution_mode=ExecutionMode.NEXT_BAR,
        stop_fill_mode=StopFillMode.STOP_PRICE,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=commission_bps / 10_000.0,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=slippage_bps / 10_000.0,
        share_type=ShareType.FRACTIONAL,
        allow_leverage=True,
        initial_margin=0.5,
    )
    strategy = MechanicalPremiaStrategy(weights, expanded['asset'].n_unique())
    engine = Engine(DataFeed(prices_df=price, signals_df=signals), strategy, config)
    result = engine.run()
    strategy.native_rejections = [
        (o.asset, o.rejection_reason, o.quantity)
        for o in engine.broker.get_rejected_orders()
    ]
    strategy.end_cash = float(engine.broker.get_cash())
    strategy.end_equity = float(engine.broker.equity())
    strategy.end_positions = {
        symbol: {
            "quantity": float(position.quantity),
            "entry_price": float(position.entry_price),
            "current_price": float(position.current_price),
            "multiplier": float(position.multiplier),
        }
        for symbol, position in engine.broker.get_positions().items()
    }
    return strategy, result
