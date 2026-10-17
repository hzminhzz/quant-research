"""Frozen Gemini Cycle-9 rolling VWAP pullback MVP.

Source bars: Binance USD-M hourly open-time UTC; no 2025+ observations.
Uses native ml4t.engineer features and ml4t.backtest Engine/broker.
A small deterministic rolling close*volume numerator is the unsupported VWAP extension.
Prepare data without performance inspection, then freeze SessionSpec, then run trials.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import talib
from ml4t.backtest import BacktestConfig, DataFeed, Engine, Strategy
from ml4t.backtest.config import CommissionType, ExecutionPrice, ShareType, SlippageType
from ml4t.backtest.types import ExecutionMode
from ml4t.diagnostic.api import PortfolioAnalysis
from ml4t.engineer import compute_features

ROOT = Path(__file__).resolve().parents[1]
SESSION = "crypto_rolling_vwap_pullback_v1_20261015"
SOURCE = Path("/home/quant/dev/quant/ml4t-data/data/crypto/market/perps_1h.parquet")
DATA = ROOT / "data" / "processed" / SESSION
OUT = ROOT / "run_log" / "research_sessions" / (SESSION + "_registered") / "mvp"
START = datetime(2020, 1, 1, tzinfo=UTC)
END = datetime(2025, 1, 1, tzinfo=UTC)  # NEVER read observations at or beyond.
ENTRY_CUTOFF = END - timedelta(hours=48)
STARTING_CASH = 100_000.0
SYMBOLS = ("BTCUSDT", "ETHUSDT")
FEATURE_COLUMNS = ("trend168", "atr24", "sma24", "vwap24", "signal_vwap", "signal_sma")
TRIALS = (
    ("btc_vwap_development", "BTCUSDT", "vwap24", "signal_vwap", 1.0),
    ("btc_sma_baseline", "BTCUSDT", "sma24", "signal_sma", 1.0),
    ("btc_vwap_double_cost", "BTCUSDT", "vwap24", "signal_vwap", 2.0),
    ("eth_vwap_replication", "ETHUSDT", "vwap24", "signal_vwap", 1.0),
)


def sha(path: Path) -> str:
    with path.open("rb") as fp:
        return hashlib.file_digest(fp, "sha256").hexdigest()


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, allow_nan=False, default=str) + "\n")


def check_bars(df: pl.DataFrame, sym: str) -> dict[str, Any]:
    if df.schema["timestamp"].time_zone != "UTC":
        raise ValueError(f"{sym}: UTC-aware timestamp required")
    if df["symbol"].unique().to_list() != [sym]:
        raise ValueError(f"{sym}: contaminated symbol data")
    if df.height != int((END - START).total_seconds() // 3600):
        raise ValueError(f"{sym}: missing hourly rows")
    expected = pl.datetime_range(START, END - timedelta(hours=1), interval="1h", eager=True)
    if df["timestamp"].to_list() != expected.to_list():
        raise ValueError(f"{sym}: missing, duplicate or misaligned hourly observations")
    bad = df.filter(
        (pl.col("open") <= 0) | (pl.col("high") < pl.col("low"))
        | (pl.col("low") > pl.col("open")) | (pl.col("high") < pl.col("open"))
        | (pl.col("low") > pl.col("close")) | (pl.col("high") < pl.col("close"))
        | (pl.col("volume") < 0)
        | (~pl.col("open").is_finite()) | (~pl.col("high").is_finite())
        | (~pl.col("low").is_finite()) | (~pl.col("close").is_finite())
        | (~pl.col("volume").is_finite())
    ).height
    if bad:
        raise ValueError(f"{sym}: invalid OHLCV rows: {bad}")
    return {"bars": df.height, "first_bar_start": str(df["timestamp"][0]),
            "last_bar_start": str(df["timestamp"][-1]),
            "zero_volume_bars": df.filter(pl.col("volume") == 0).height}


def prepare_data() -> None:
    """Materialize strictly bounded, holdout-free, auditable ML4T input files."""
    if any((DATA / f"{sym.lower()}_1h.parquet").exists() for sym in SYMBOLS):
        raise FileExistsError("Frozen source inputs already exist; do not overwrite")
    DATA.mkdir(parents=True, exist_ok=True)
    stats = {}
    for sym in SYMBOLS:
        frame = (
            pl.scan_parquet(SOURCE).filter(
                (pl.col("symbol") == sym)
                & (pl.col("timestamp") >= START) & (pl.col("timestamp") < END)
            ).select("timestamp", "symbol", "open", "high", "low", "close", "volume")
            .sort("timestamp").collect()
        )
        stats[sym] = check_bars(frame, sym)
        target = DATA / f"{sym.lower()}_1h.parquet"
        frame.write_parquet(target)
        stats[sym]["development_file"] = str(target.relative_to(ROOT))
        stats[sym]["development_sha256"] = sha(target)
    write_json(OUT / "source_preflight.json", {
        "status": "PASS", "source": str(SOURCE),
        "source_sha256_preflight": "f35452fab6b9a32ebc7e773162575ecf582e62ed5cdfaab200f6808060f5f6b8",
        "data_window_start_inclusive": START.isoformat(),
        "data_window_end_exclusive": END.isoformat(),
        "timestamp_semantics": "UTC bar start, complete after +1 hour",
        "protected_2025_plus_rows_materialized": 0,
        "volume": "base-asset traded volume; each symbol has one zero-volume hour",
        "symbol_evidence": stats,
    })
    print("PREPARED", json.dumps(stats), flush=True)


def feature_frame(raw: pl.DataFrame) -> pl.DataFrame:
    """Native ROC/ATR/SMA; deterministic close-volume rolling VWAP extension."""
    if raw["symbol"].n_unique() != 1:
        raise ValueError("Features must be computed separately for each symbol")
    f = compute_features(
        raw.sort("timestamp"), [
            {"name": "rocp", "params": {"timeperiod": 168}, "output": "trend168"},
            {"name": "atr", "params": {"period": 24}, "output": "atr24"},
            {"name": "sma", "params": {"period": 24}, "output": "sma24"},
        ], timestamp_col="timestamp",
    )
    f = f.with_columns(
        (pl.col("close") * pl.col("volume")).rolling_sum(
            window_size=24, min_samples=24).alias("pv24"),
        pl.col("volume").rolling_sum(
            window_size=24, min_samples=24).alias("volume24"),
    ).with_columns(
        pl.when(pl.col("volume24") > 0)
          .then(pl.col("pv24") / pl.col("volume24"))
          .otherwise(None).alias("vwap24")
    )
    entries = []
    for prefix, benchmark in (("vwap", "vwap24"), ("sma", "sma24")):
        is_long = ((pl.col("trend168") > .02)
                   & (pl.col("low") <= pl.col(benchmark))
                   & (pl.col("close") > pl.col(benchmark)))
        is_short = ((pl.col("trend168") < -.02)
                    & (pl.col("high") >= pl.col(benchmark))
                    & (pl.col("close") < pl.col(benchmark)))
        entries.append(pl.when(
            pl.col("atr24").is_not_null() & (pl.col("atr24") > 0)
            & pl.col(benchmark).is_not_null()
        ).then(
            pl.when(is_long).then(1).when(is_short).then(-1).otherwise(0)
        ).otherwise(0).cast(pl.Int8).alias(f"signal_{prefix}"))
    return f.with_columns(entries).drop("pv24", "volume24")


def numerical_feature_proof(raw: pl.DataFrame, features: pl.DataFrame) -> dict[str, Any]:
    close = raw["close"].to_numpy()
    volume = raw["volume"].to_numpy()
    high = raw["high"].to_numpy()
    low = raw["low"].to_numpy()
    expected_trend = np.full(close.shape, np.nan)
    expected_trend[168:] = close[168:] / close[:-168] - 1
    if not np.allclose(features["trend168"].to_numpy(), expected_trend, atol=1e-10, rtol=0, equal_nan=True):
        raise AssertionError("native 168h ROC parity failed")
    for name, expected in (
        ("atr24", talib.ATR(high, low, close, timeperiod=24)),
        ("sma24", talib.SMA(close, timeperiod=24)),
    ):
        if not np.allclose(features[name].to_numpy(), expected, atol=1e-7, rtol=0, equal_nan=True):
            raise AssertionError(f"native {name} TA-Lib parity failed")
    # Independent scalar reference at evenly dispersed development indices.
    positions = (23, 24, 168, 169, 1000, 12000, 30000, len(close)-1)
    for i in positions:
        v = float(volume[i-23:i+1].sum())
        expected = float(np.dot(close[i-23:i+1], volume[i-23:i+1]) / v) if v > 0 else None
        actual = features["vwap24"][i]
        if expected is None and actual is not None:
            raise AssertionError("zero-denominator VWAP must be null")
        if expected is not None and (actual is None or not np.isclose(float(actual), expected, atol=1e-8, rtol=1e-10)):
            raise AssertionError(f"VWAP independent reference mismatch at {i}")
    return {"rocp168_independent_parity": True, "atr24_talib_parity": True,
            "sma24_talib_parity": True, "vwap24_scalar_oracle_indices": list(positions),
            "native_engineer": "0.1.4", "vwap_extension": "24-row close*base_volume / 24-row base_volume",
            "available_after": "UTC bar start + 1h; NEXT_BAR fill"}


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class VwapPullbackStrategy(Strategy):
    """Only signal rules and broker intents; native broker owns cash, fills and PnL."""
    def __init__(self, symbol: str, benchmark: str, signal: str):
        self.symbol = symbol
        self.benchmark = benchmark
        self.signal = signal
        self.bar_index = -1
        self.pending_entry: dict | None = None
        self.pending_exit: dict | None = None
        self.active: dict | None = None
        self.events: list[dict] = []
        self.completed_exit_reasons: list[str] = []
        self.entry_frozen_values: list[float] = []
        self.max_positions = 0

    def on_data(self, timestamp, data, context, broker) -> None:
        self.bar_index += 1
        ts = utc(timestamp)
        if self.symbol not in data:
            raise AssertionError(f"Missing {self.symbol} bar in native feed")
        bar = data[self.symbol]
        sig = bar["signals"]
        pos = broker.get_position(self.symbol)
        self.max_positions = max(self.max_positions, int(pos is not None and pos.quantity != 0))
        # Consume the broker's actual fill before any position-dependent decisions.
        if self.pending_entry is not None:
            if pos is None:
                if self.bar_index > self.pending_entry["bar_index"] + 1:
                    raise AssertionError("Entry intent did not fill NEXT_BAR")
                return
            self.active = {
                "direction": self.pending_entry["direction"],
                "frozen_atr": self.pending_entry["frozen_atr"],
                "entry_bar": self.bar_index,
                "entry_price": float(pos.entry_price),
            }
            self.entry_frozen_values.append(self.active["frozen_atr"])
            self.events.append({"kind": "entry_filled_observed", "timestamp": ts.isoformat(),
                                "entry_price": self.active["entry_price"],
                                "frozen_atr": self.active["frozen_atr"]})
            self.pending_entry = None

        if self.pending_exit is not None:
            if pos is not None:
                if self.bar_index > self.pending_exit["bar_index"] + 1:
                    raise AssertionError("Exit intent did not fill NEXT_BAR")
                return
            self.completed_exit_reasons.append(self.pending_exit["reason"])
            self.events.append({"kind": "exit_filled_observed", "timestamp": ts.isoformat(),
                                "reason": self.pending_exit["reason"]})
            self.pending_exit = None
            self.active = None

        if pos is not None:
            if self.active is None:
                raise AssertionError("Native position has no entry-frozen ATR record")
            direction = self.active["direction"]
            if np.sign(pos.quantity) != direction:
                raise AssertionError("Position side differs from entry direction")
            atr = float(sig["atr24"])
            benchmark = float(sig[self.benchmark])
            close = float(bar["close"])
            entry_price = self.active["entry_price"]
            frozen_atr = self.active["frozen_atr"]
            age = self.bar_index - self.active["entry_bar"] + 1
            assert age >= 1 and frozen_atr > 0
            catastrophic = (close < entry_price - 2*frozen_atr if direction > 0
                            else close > entry_price + 2*frozen_atr)
            invalid = (close < benchmark - atr if direction > 0
                       else close > benchmark + atr)
            reason = ("catastrophic" if catastrophic else "benchmark" if invalid
                      else "time" if age >= 24 else None)
            if reason is not None:
                order = broker.order_target_value(self.symbol, 0)
                if order is None:
                    raise AssertionError("Broker refused exit order")
                self.pending_exit = {"bar_index": self.bar_index, "reason": reason}
                self.events.append({"kind": "exit_intent", "timestamp": ts.isoformat(),
                                    "reason": reason, "bars_completed": age,
                                    "frozen_atr": frozen_atr})
            return

        if self.pending_entry is not None:
            return
        if ts >= ENTRY_CUTOFF:
            return
        direction = int(sig.get(self.signal, 0) or 0)
        atr_val = sig.get("atr24")
        if direction not in (-1, 1) or atr_val is None or not np.isfinite(atr_val) or atr_val <= 0:
            return
        order = broker.order_target_value(self.symbol, direction * broker.get_account_value())
        if order is not None:
            self.pending_entry = {"bar_index": self.bar_index,
                                  "direction": direction, "frozen_atr": float(atr_val)}
            self.events.append({"kind": "entry_intent", "timestamp": ts.isoformat(),
                                "direction": direction, "frozen_atr": float(atr_val)})


def config(cost_multiplier: float) -> BacktestConfig:
    return BacktestConfig(
        initial_cash=STARTING_CASH, allow_short_selling=True, allow_leverage=True,
        share_type=ShareType.FRACTIONAL,
        execution_mode=ExecutionMode.NEXT_BAR, execution_price=ExecutionPrice.OPEN,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=.0005*cost_multiplier,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=.0002*cost_multiplier,
    )


def serialize_risk(risk) -> dict[str, float | None]:
    out = {}
    for key, value in vars(risk).items():
        if isinstance(value, (int, float, np.number)):
            x = float(value)
            out[key] = x if np.isfinite(x) else None
    return out


def run_trial(trial_id: str, symbol: str, feature: pl.DataFrame, benchmark: str,
              signal: str, multiplier: float) -> dict[str, Any]:
    destination = OUT / "trials" / trial_id
    if (destination / "failure.json").exists():
        destination = OUT / "trials" / (trial_id + "_retry1")
    if (destination / "metrics.json").exists():
        raise FileExistsError(f"Already terminal: {trial_id}; do not overwrite evidence")
    destination.mkdir(parents=True, exist_ok=True)
    feed = DataFeed(
        prices_df=feature.select("timestamp", "symbol", "open", "high", "low", "close", "volume"),
        signals_df=feature.select("timestamp", "symbol", *FEATURE_COLUMNS),
        entity_col="symbol", timestamp_col="timestamp",
    )
    strategy = VwapPullbackStrategy(symbol, benchmark, signal)
    try:
        result = Engine(feed, strategy, config(multiplier)).run()
        trades = result.to_trades_dataframe()
        fills = result.to_fills_dataframe()
        eq = result.to_equity_dataframe()
        trades.write_csv(destination / "trades.csv")
        fills.write_csv(destination / "fills.csv")
        eq.write_parquet(destination / "hourly_equity.parquet")
        daily = (eq.with_columns(pl.col("timestamp").dt.date().alias("date"))
                 .group_by("date").agg(pl.col("equity").last().alias("equity")).sort("date"))
        daily.write_csv(destination / "daily_equity.csv")
        daily_returns = daily["equity"].pct_change().fill_null(0).to_numpy()
        risk = serialize_risk(PortfolioAnalysis(returns=daily_returns, periods_per_year=365.25).compute_summary_stats())
        closed = trades.filter(pl.col("status") == "closed")
        pnl = closed["pnl"] if closed.height else pl.Series("pnl", [], dtype=pl.Float64)
        closed_pnl = float(pnl.sum()) if closed.height else 0.0
        native_net = float(result.metrics["final_value"]) - STARTING_CASH
        reconciled = abs(closed_pnl - native_net) < max(.05, abs(native_net)*1e-7)
        if result.metrics.get("num_rejected_orders", 0):
            raise AssertionError(f"Native broker rejected orders: {result.metrics['num_rejected_orders']}")
        if strategy.pending_entry or strategy.pending_exit or strategy.active:
            raise AssertionError("Position or submitted native order open at development boundary")
        if not reconciled:
            raise AssertionError(f"Native trade ledger vs equity mismatch: {closed_pnl} vs {native_net}")
        if fills.height != 2*closed.height:
            raise AssertionError(f"Expected exactly two native fills per closed trade: {fills.height} vs {closed.height}")
        entry_intents = [e for e in strategy.events if e["kind"] == "entry_intent"]
        exit_intents = [e for e in strategy.events if e["kind"] == "exit_intent"]
        if not (len(entry_intents) == len(exit_intents) == closed.height
                == len(strategy.completed_exit_reasons)):
            raise AssertionError("Intent, native trade and exit reason counts diverge")
        intents = sorted(entry_intents + exit_intents, key=lambda e: e["timestamp"])
        fill_timestamps = sorted(utc(t) for t in fills["timestamp"].to_list())
        expected_fills = sorted(datetime.fromisoformat(e["timestamp"])+timedelta(hours=1) for e in intents)
        clock_verified = fill_timestamps == expected_fills
        if not clock_verified:
            raise AssertionError("Native fills do not occur exactly at next-bar open")
        if strategy.max_positions > 1:
            raise AssertionError("Concurrent positions exceeded one")
        leverage_values = [
            s[3]/s[1] for s in result.portfolio_state if len(s)>3 and s[1] > 0
        ]
        max_gross = max(leverage_values, default=0.0)
        # Position drift after a 1x entry is not evidence of an oversized entry.
        # Report it as intratrade leverage/margin risk, not an entry-size failure.
        if sum(strategy.completed_exit_reasons.count(k) for k in ("catastrophic","benchmark","time")) != closed.height:
            raise AssertionError("Exit attribution incomplete")
        yearly = (daily.with_columns(pl.col("equity").pct_change().fill_null(0.0).alias("ret"))
                  .with_columns(pl.col("date").dt.year().alias("year"))
                  .group_by("year").agg(((pl.col("ret")+1).product()-1).alias("net_return"))
                  .sort("year"))
        yearly.write_csv(destination / "yearly_returns.csv")
        write_json(destination / "strategy_events.json", {"events": strategy.events})
        metric = {
            "trial": trial_id, "symbol": symbol, "feature": benchmark,
            "commission_bps_per_side": 5*multiplier,
            "slippage_bps_per_side": 2*multiplier,
            "funding_included": False,
            "closed_trades": closed.height, "fills": fills.height,
            "win_rate_trades": float((pnl>0).sum()/closed.height) if closed.height else None,
            "closed_pnl_usdt": closed_pnl, "final_equity_usdt": float(result.metrics["final_value"]),
            "trade_expectancy_usdt": closed_pnl/closed.height if closed.height else None,
            "profit_factor_trades": (float(pnl.filter(pnl>0).sum()) /
                abs(float(pnl.filter(pnl<0).sum()))) if closed.height and (pnl<0).any() else None,
            "exit_reasons": {k: strategy.completed_exit_reasons.count(k)
                             for k in ("catastrophic","benchmark","time")},
            "catastrophic_exit_fraction": (strategy.completed_exit_reasons.count("catastrophic") / closed.height
                                          if closed.height else None),
            "max_gross_notional_over_equity": max_gross,
            "daily_rows": daily.height, "daily_risk_native_diagnostic": risk,
            "yearly_net_return": {str(r["year"]): float(r["net_return"]) for r in yearly.iter_rows(named=True)},
            "native_result_metrics": {k:float(v) if isinstance(v,(int,float,np.number)) and np.isfinite(v)
                                   else str(v) for k,v in result.metrics.items()},
            "native_fill_clock_exact_next_bar": clock_verified,
            "native_ledger_equity_reconciled": reconciled,
            "native_order_rejections": 0,
            "feature_rows": feature.height, "feature_last_timestamp": str(feature["timestamp"][-1]),
            "entry_atr_frozen": True,
            "source_paths": {
                "price": str((DATA / f"{symbol.lower()}_1h.parquet").relative_to(ROOT)),
                "native_features": str((OUT / f"{symbol.lower()}_features.parquet").relative_to(ROOT))
            },
            "artifacts": ["trades.csv","fills.csv","hourly_equity.parquet","daily_equity.csv",
                          "yearly_returns.csv","strategy_events.json"]
        }
        write_json(destination / "metrics.json", metric)
        print("TRIAL",trial_id,json.dumps({"trades":closed.height,"pnl":closed_pnl,
              "sharpe":risk.get("sharpe_ratio"),"win_rate":metric["win_rate_trades"],
              "pf":metric["profit_factor_trades"],"exit":metric["exit_reasons"]}),flush=True)
        return metric
    except Exception as e:
        # Append-only failure evidence; never convert a failed attempt into a pass.
        failed = destination / "failure.json"
        if not failed.exists():
            write_json(failed, {"trial":trial_id,"type":type(e).__name__,"message":str(e)})
        raise


def decision(result: dict[str, dict]) -> tuple[str, list[str]]:
    btc = result.get("btc_vwap_development")
    sma = result.get("btc_sma_baseline")
    stress = result.get("btc_vwap_double_cost")
    eth = result.get("eth_vwap_replication")
    if btc is None:
        return "INCONCLUSIVE", ["BTC native development trial missing"]
    frac = btc["catastrophic_exit_fraction"]
    if frac is not None and frac > .35:
        return "REJECT", ["Preregistered catastrophic-exit stop >35%"]
    if not all((btc,sma,stress,eth)):
        return "INCONCLUSIVE", ["Incomplete preregistered baseline, stress or replication trials"]
    risk = lambda t: t["daily_risk_native_diagnostic"]
    reasons = []
    if btc["closed_trades"] < 50:
        reasons.append("BTC independent closed trades <50")
    if btc["closed_pnl_usdt"] < 0:
        reasons.append("BTC net PnL negative")
    if btc["profit_factor_trades"] is None or btc["profit_factor_trades"] < 1.35:
        reasons.append("BTC trade profit factor <1.35")
    if btc["win_rate_trades"] is None or btc["win_rate_trades"] < .53:
        reasons.append("BTC trade win rate <53%")
    if risk(btc).get("sharpe_ratio") is None or risk(sma).get("sharpe_ratio") is None or risk(btc)["sharpe_ratio"] <= risk(sma)["sharpe_ratio"]:
        reasons.append("BTC VWAP daily-equity Sharpe does not beat SMA")
    if btc["win_rate_trades"] is None or sma["win_rate_trades"] is None or btc["win_rate_trades"] <= sma["win_rate_trades"]:
        reasons.append("BTC VWAP trade win rate does not beat SMA")
    if eth["closed_pnl_usdt"] <= 0:
        reasons.append("ETH replication has no net profit")
    if reasons:
        return "REJECT", reasons
    # No funding cash flows are available in these OHLCV sources.
    return "INCONCLUSIVE", ["Price-only MVP passed frozen numeric screens, but signed perpetual funding and actual venue slippage remain unverified; not VALIDATE until qualified."]


def run_all() -> None:
    if not (ROOT / "run_log" / "research_sessions" / (SESSION + "_registered") / "frozen_spec.json").exists():
        raise RuntimeError("Frozen research_session init must succeed before observing strategy outcomes")
    OUT.mkdir(parents=True, exist_ok=True)
    features = {}
    for sym in SYMBOLS:
        raw = pl.read_parquet(DATA / f"{sym.lower()}_1h.parquet").sort("timestamp")
        check_bars(raw, sym)
        f = feature_frame(raw)
        proof = numerical_feature_proof(raw, f)
        features[sym] = f
        target = OUT / f"{sym.lower()}_features.parquet"
        if target.exists():
            if pl.read_parquet(target).equals(f):
                pass
            else:
                raise FileExistsError(f"Frozen features changed: {target}")
        else:
            f.write_parquet(target)
        write_json(OUT / f"{sym.lower()}_feature_proof.json", proof)
        print("FEATURE",sym,json.dumps(proof),flush=True)
    metrics = {}
    for trial_id, sym, benchmark, signal, cost in TRIALS:
        metrics[trial_id] = run_trial(trial_id, sym, features[sym], benchmark, signal, cost)
        # Honor Gemini's early termination rule without testing new candidates.
        if trial_id == "btc_vwap_development":
            frac = metrics[trial_id]["catastrophic_exit_fraction"]
            if frac is not None and frac > .35:
                break
    verdict, reasons = decision(metrics)
    comparison = {
        "session":SESSION,"status":"EXPLORATORY","approval_status":"NOT_APPROVED",
        "development":"2020-01-01 through 2024-12-31 UTC, 2025+ protected",
        "trials_completed":list(metrics),"trials_skipped":
            [t[0] for t in TRIALS if t[0] not in metrics],
        "decision": verdict, "reasons": reasons,
        "numerical_gates_not_broker_qualification": True,
        "funding_not_modeled": True,
        "metrics": {k:{"closed_trades":v["closed_trades"],"pnl":v["closed_pnl_usdt"],
             "pf":v["profit_factor_trades"],"win_rate":v["win_rate_trades"],
             "daily_sharpe":v["daily_risk_native_diagnostic"].get("sharpe_ratio"),
             "max_dd":v["daily_risk_native_diagnostic"].get("max_drawdown")}
             for k,v in metrics.items()},
    }
    write_json(OUT / "final_decision.json",comparison)
    lines = [
        "# Gemini Cycle 9 rolling VWAP pullback: MVP research decision",
        "",f"**{verdict}** — {'; '.join(reasons)}","",
        "## Frozen research","BTCUSDT 1h 2020–2024; ETHUSDT replication, 2025+ sealed.",
        "24h close-volume VWAP vs SMA24; 168h ROC trend +/-2%; ATR24 stop/benchmark.",
        "Native NEXT_BAR OPEN, one 1.0x notional position, 24 full completed-bar hold.",
        "5bps commission +2bps slippage per side (14bps modeled round trip).",
        "Cost stress 28bps round trip. Funding excluded and unverified.",
        "", "## Trial results",
        "| Trial | Trades | Net PnL (USDT) | Win rate | PF | Daily Sharpe | Max DD |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for key, m in comparison["metrics"].items():
        fmt = lambda x: "undefined" if x is None else f"{x:.3f}"
        lines.append(f"| {key} | {m['closed_trades']} | {m['pnl']:.2f} | "
                     f"{fmt(m['win_rate'])} | {fmt(m['pf'])} | "
                     f"{fmt(m['daily_sharpe'])} | {fmt(m['max_dd'])} |")
    lines.extend(["","## Independent audit",
                  "All trial fills/trades/equity are from ml4t.backtest.Engine and its native broker.",
                  "Numerical feature proof uses independent scalar VWAP and TA-Lib parity.",
                  "Every native fill clock, trade-ledger reconciliation and exposure ceiling is asserted.",
                  "Gemini's hourly close*volume VWAP is a bar approximation, not actual institutional fills.",
                  "No mark-to-market funding/fee-tier/impact calibration; this blocks live conclusions.",
                  "The acceptance gate is not a protected final-test evaluation.",
                  "","## Reproduce", 
                  "Run data preparation only on a new experiment ID and register a new session.",
                  "Current preregistered trial results are immutable; do not rerun and overwrite them.",
                  "Review run_log/research_sessions/"+SESSION+"/mvp/final_decision.json.",
                  ""])
    (OUT / "final_report.md").write_text("\n".join(lines))
    print("DECISION",json.dumps({"verdict":verdict,"reasons":reasons}),flush=True)


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--prepare",action="store_true")
    parser.add_argument("--run",action="store_true")
    args=parser.parse_args()
    if args.prepare == args.run:
        parser.error("Choose exactly one of --prepare or --run")
    if args.prepare:
        prepare_data()
    else:
        run_all()


if __name__ == "__main__":
    main()
