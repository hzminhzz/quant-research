"""Run frozen, retrospective prop MVP studies through ml4t.backtest.Engine."""

from __future__ import annotations

import hashlib
import io
import json
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
import exchange_calendars as xcals
from ml4t.backtest import BacktestConfig, DataFeed, Engine, Strategy
from ml4t.backtest.config import CommissionType, ExecutionMode, ShareType, SlippageType
from ml4t.diagnostic.metrics.risk_adjusted import sharpe_ratio


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "run_log/prop_mvp_20261011"
START = pl.datetime(2021, 1, 1, time_zone="UTC")
END = pl.datetime(2026, 8, 1, time_zone="UTC")
CUTOFF = pl.datetime(2026, 8, 1, time_zone="UTC")
INITIAL_CASH = 25_000.0


class TargetSignal(Strategy):
    def __init__(self, weight: float = 0.5):
        self.weight = weight
        self.last_signal = {}

    def on_data(self, timestamp, data, context, broker):
        for symbol, bar in data.items():
            signal = bar["signals"].get("signal")
            if signal is None:
                continue
            previous = self.last_signal.get(symbol)
            self.last_signal[symbol] = signal
            if previous == signal:
                continue
            if signal == 0:
                target = 0.0
            else:
                target = float(signal) * self.weight
            broker.order_target_percent(symbol, target)


class CashHold(Strategy):
    def on_data(self, timestamp, data, context, broker):
        return None


class ReversalProxy(Strategy):
    """One open position per symbol; exit after 12 completed minute bars."""

    def __init__(self):
        self.held = {}

    def on_data(self, timestamp, data, context, broker):
        for symbol, bar in data.items():
            pos = broker.get_position(symbol)
            active = pos is not None and pos.quantity != 0
            if active:
                self.held[symbol] = self.held.get(symbol, 0) + 1
                if self.held[symbol] >= 12:
                    broker.order_target_percent(symbol, 0.0)
                    self.held[symbol] = 0
            elif bar["signals"].get("signal", 0) == 1:
                broker.order_target_percent(symbol, 0.5)
                self.held[symbol] = 0


class OpeningRange(Strategy):
    def __init__(self):
        self.traded = set()
        self.zone = ZoneInfo("America/New_York")

    def on_data(self, timestamp, data, context, broker):
        for symbol, bar in data.items():
            signal = bar["signals"].get("signal")
            session = timestamp.replace(tzinfo=ZoneInfo("UTC")).astimezone(self.zone).date()
            key = (symbol, session)
            pos = broker.get_position(symbol)
            current = 0.0 if pos is None else pos.quantity
            if signal == 0 and current:
                broker.order_target_percent(symbol, 0.0)
            elif signal in (-1, 1) and key not in self.traded and not current:
                broker.order_target_percent(symbol, 0.5 * float(signal))
                self.traded.add(key)


def config(commission_bps: float, slippage_bps: float) -> BacktestConfig:
    return BacktestConfig(
        initial_cash=INITIAL_CASH,
        allow_short_selling=True,
        share_type=ShareType.FRACTIONAL,
        execution_mode=ExecutionMode.NEXT_BAR,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=commission_bps / 10_000,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=slippage_bps / 10_000,
    )


def load_prices(path: str, cutoff: bool = True) -> pl.DataFrame:
    lazy = pl.scan_parquet(ROOT / path)
    if cutoff:
        lazy = lazy.filter(pl.col("timestamp") < CUTOFF)
    frame = lazy.collect()
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        raise ValueError(f"{path}: missing {sorted(required - set(frame.columns))}")
    if frame.schema["timestamp"].time_zone is None:
        raise ValueError(f"{path}: timestamps are timezone-naive")
    frame = frame.sort("timestamp")
    return frame


def metrics(result, track: str) -> dict:
    m = result.metrics
    calendar = "crypto" if track.startswith(("a_", "b_")) else "NYSE"
    daily_returns = result.to_daily_returns(calendar=calendar)
    annualization = 365 if calendar == "crypto" else 252
    return {
        "native_metrics": m,
        "trades": int(m.get("num_trades", 0)),
        "win_rate": m.get("win_rate"),
        "mean_trade_return": m.get("avg_trade"),
        "profit_factor": m.get("profit_factor"),
        "total_return": m.get("total_return"),
        "sharpe": sharpe_ratio(daily_returns, periods_per_year=annualization),
        "sharpe_frequency": "flat-inclusive daily equity returns",
        "daily_observations": len(daily_returns),
        "engine_bar_sharpe": m.get("sharpe"),
        "max_drawdown": m.get("max_drawdown"),
        "commission": m.get("total_commission"),
        "slippage": m.get("total_slippage"),
        "total_costs": m.get("total_costs"),
    }


def save_result(track: str, trial: str, instrument: str, result, extra: dict) -> dict:
    directory = OUT / track / instrument
    directory.mkdir(parents=True, exist_ok=True)
    daily_returns = result.to_daily_returns(calendar="crypto" if track.startswith(("a_", "b_")) else "NYSE")
    pl.DataFrame({"daily_return": daily_returns}).write_parquet(directory / f"{trial}_daily_returns.parquet")
    result.to_trades_dataframe().write_parquet(directory / f"{trial}_trades.parquet")
    result.to_fills_dataframe().write_parquet(directory / f"{trial}_fills.parquet")
    result.to_equity_dataframe().write_parquet(directory / f"{trial}_equity.parquet")
    portfolio_state = result.to_portfolio_state_dataframe()
    portfolio_state.write_parquet(directory / f"{trial}_portfolio_state.parquet")
    reconciliation = (portfolio_state.select(
        (pl.col("equity") - pl.col("cash") - pl.col("net_exposure")).abs().max().alias("max_abs_residual")
    ).to_dicts()[0] if portfolio_state.height else {"max_abs_residual": 0.0})
    if reconciliation["max_abs_residual"] > 1e-6:
        raise AssertionError(f"Native portfolio state does not reconcile: {reconciliation}")
    (directory / f"{trial}_reconciliation.json").write_text(json.dumps(reconciliation, indent=2))
    record = {"track": track, "trial": trial, "instrument": instrument,
              "sample_start": str(result.to_equity_dataframe()["timestamp"].min()),
              "sample_end": str(result.to_equity_dataframe()["timestamp"].max()),
              **metrics(result, track), **extra}
    (directory / f"{trial}_metrics.json").write_text(json.dumps(record, indent=2, default=str))
    return record


def run_a() -> list[dict]:
    out = []
    for symbol, path in [("BTCUSDT", "data/processed/btcusdt_1h.parquet"),
                         ("ETHUSDT", "data/processed/ethusdt_1h.parquet")]:
        frame = load_prices(path).filter(pl.col("timestamp") >= START)
        frame = frame.with_columns(
            signal=pl.when(pl.col("close") / pl.col("close").shift(24) - 1 > 0).then(1)
            .when(pl.col("close") / pl.col("close").shift(24) - 1 < 0).then(-1)
            .otherwise(0)
        ).drop_nulls("signal")
        prices = frame.select("timestamp", "open", "high", "low", "close", "volume").with_columns(pl.lit(symbol).alias("symbol"))
        signals = frame.select("timestamp", "signal").with_columns(pl.lit(symbol).alias("symbol"))
        for trial, fee, slip, delay in [("gross", 0.0, 0.0, 0), ("baseline", 4.5, 1.5, 0),
                                        ("cost_2x", 9.0, 3.0, 0), ("extra_bar_delay", 4.5, 1.5, 1),
                                        ("matched_time_placebo_24h", 4.5, 1.5, 24)]:
            s = signals
            if delay:
                s = s.with_columns(pl.col("signal").shift(delay).over("symbol"))
            result = Engine(DataFeed(prices_df=prices, signals_df=s), TargetSignal(0.5), config(fee, slip)).run()
            out.append(save_result("a_momentum", trial, symbol, result, {
                "commission_bps_each_fill": fee, "slippage_bps_each_fill": slip,
                "funding_cost": "not applied; local funding files exist but native Engine has no funding cash-flow API",
                "period_classification": "retrospective; previously explored strategy family",
                "data_path": path,
            }))
        bh = signals.with_columns(pl.lit(1).alias("signal"))
        buy_hold = Engine(DataFeed(prices_df=prices, signals_df=bh), TargetSignal(0.5), config(4.5, 1.5)).run()
        out.append(save_result("a_momentum", "buy_and_hold", symbol, buy_hold, {"control": True, "fees": "same as baseline"}))
        cash = Engine(DataFeed(prices_df=prices, signals_df=signals), CashHold(), config(4.5, 1.5)).run()
        out.append(save_result("a_momentum", "cash", symbol, cash, {"control": True, "fees": "no fills; zero execution costs"}))
    return out


def run_b(symbols: set[str] | None = None, trials: set[str] | None = None) -> tuple[list[dict], dict]:
    out = []
    event_rows = []
    for symbol, path in [("BTCUSDT", "data/processed/btc_1m.parquet"),
                         ("ETHUSDT", "data/processed/eth_1m.parquet")]:
        if symbols is not None and symbol not in symbols:
            continue
        frame = load_prices(path).filter(pl.col("timestamp") < pl.datetime(2025, 6, 1, time_zone="UTC"))
        frame = frame.with_columns(
            prev_close=pl.col("close").shift(1),
            prev_tr=pl.max_horizontal(pl.col("high") - pl.col("low"),
                                     (pl.col("high") - pl.col("close").shift(1)).abs(),
                                     (pl.col("low") - pl.col("close").shift(1)).abs()),
        ).with_columns(atr=pl.col("prev_tr").rolling_mean(14).shift(1))
        frame = frame.with_columns(
            signal=pl.when((pl.col("close") - pl.col("prev_close")) <= -3 * pl.col("atr")).then(1).otherwise(0)
        ).drop_nulls(["signal", "atr"])
        price_cols = [c for c in ["timestamp", "open", "high", "low", "close", "volume"] if c in frame.columns]
        prices = frame.select(price_cols).with_columns(pl.lit(symbol).alias("symbol"))
        signals = frame.select("timestamp", "signal").with_columns(pl.lit(symbol).alias("symbol"))
        for trial, fee, slip, delay in [("gross", 0.0, 0.0, 0), ("baseline", 4.5, 5.0, 0),
                                        ("cost_2x", 9.0, 10.0, 0), ("extra_bar_delay", 4.5, 5.0, 1)]:
            if trials is not None and trial not in trials:
                continue
            s = signals.with_columns(pl.col("signal").shift(delay).over("symbol").fill_null(0)) if delay else signals
            result = Engine(DataFeed(prices_df=prices, signals_df=s), ReversalProxy(), config(fee, slip)).run()
            out.append(save_result("b_price_only_proxy", trial, symbol, result, {
                "classification": "OHLCV-only extreme price dislocation proxy; not liquidation evidence",
                "commission_bps_each_fill": fee, "slippage_bps_each_fill": slip,
                "funding": "excluded", "data_path": path,
            }))
        ev = frame.with_columns(
            forward_12=pl.col("close").shift(-12) / pl.col("close") - 1,
            ret_1=pl.col("close") / pl.col("prev_close") - 1,
        ).filter(pl.col("forward_12").is_not_null())
        event_rows.append(ev.select("timestamp", "signal", "atr", "ret_1", "forward_12").with_columns(pl.lit(symbol).alias("symbol")))
    events = pl.concat(event_rows)
    summary = {}
    for symbol in ["BTCUSDT", "ETHUSDT"]:
        sub = events.filter(pl.col("symbol") == symbol)
        sig = sub.filter(pl.col("signal") == 1)
        controls = sub.filter((pl.col("signal") == 0) & (pl.col("ret_1").abs() >= pl.col("ret_1").abs().quantile(0.90)))
        summary[symbol] = {"proxy_events": sig.height,
                           "proxy_mean_forward_12m_return": sig["forward_12"].mean(),
                           "proxy_median_forward_12m_return": sig["forward_12"].median(),
                           "high_vol_control_n": controls.height,
                           "high_vol_control_mean_forward_12m_return": controls["forward_12"].mean(),
                           "note": "control is a descriptive top-decile absolute one-minute return proxy; not matched by venue liquidations"}
    events.write_parquet(OUT / "b_price_only_proxy" / "event_study.parquet")
    return out, summary


def add_opening_signals(frame: pl.DataFrame, cadence_minutes: int) -> pl.DataFrame:
    et = pl.col("timestamp").dt.convert_time_zone("America/New_York")
    frame = frame.with_columns(local_date=et.dt.date(), local_time=et.dt.time())
    calendar = xcals.get_calendar("XNYS")
    start_date = frame["local_date"].min()
    end_date = frame["local_date"].max()
    sessions = {value.date() for value in calendar.sessions_in_range(str(start_date), str(end_date)).to_list()}
    frame = frame.filter(pl.col("local_date").is_in(sessions))
    or_bars = 15 // cadence_minutes
    ranges = (frame.filter(pl.col("local_time") >= time(9, 30))
              .filter(pl.col("local_time") < time(9, 30 + 15))
              .group_by("local_date").agg(pl.col("high").max().alias("or_high"), pl.col("low").min().alias("or_low"), pl.len().alias("n_or")))
    close_decision = time(15, 50) if cadence_minutes == 5 else time(15, 30)
    fill_time = time(15, 55) if cadence_minutes == 5 else time(15, 45)
    exit_days = frame.filter(pl.col("local_time") == close_decision).select("local_date").unique()
    fill_days = frame.filter(pl.col("local_time") == fill_time).select("local_date").unique()
    close_rows = exit_days.join(fill_days, on="local_date", how="inner").with_columns(pl.lit(True).alias("has_close"))
    frame = frame.join(ranges, on="local_date", how="left").join(close_rows, on="local_date", how="left")
    # Decision uses the current bar's open, which is available at its timestamp.
    frame = frame.with_columns(
        signal=pl.when((pl.col("has_close") == True) & (pl.col("n_or") == or_bars) & (pl.col("local_time") >= time(9, 45)) & (pl.col("local_time") < close_decision) & (pl.col("open") > pl.col("or_high"))).then(1)
        .when((pl.col("has_close") == True) & (pl.col("n_or") == or_bars) & (pl.col("local_time") >= time(9, 45)) & (pl.col("local_time") < close_decision) & (pl.col("open") < pl.col("or_low"))).then(-1)
        .when((pl.col("has_close") == True) & (pl.col("local_time") >= close_decision)).then(0)
        .otherwise(None)
    )
    return frame


def run_c(symbols: set[str] | None = None, trial_filter: set[str] | None = None) -> list[dict]:
    out = []
    for symbol, path, cadence in [("NAS100", "data/processed/NAS100_5m_2017_2026.parquet", 5),
                                  ("SPX500", "data/processed/SPX500_USD_15m_2017_2026.parquet", 15)]:
        if symbols is not None and symbol not in symbols:
            continue
        frame = add_opening_signals(load_prices(path), cadence)
        prices = frame.select("timestamp", "symbol", "open", "high", "low", "close", "volume")
        signals = frame.select("timestamp", "symbol", "local_time", "has_close", "signal")
        trial_specs = [("gross", 0.0, 0.0, "gross"), ("baseline", 2.0, 3.0, "baseline"),
                       ("cost_2x", 4.0, 6.0, "cost_2x"), ("extra_bar_delay", 2.0, 3.0, "delay"),
                       ("matched_time_placebo", 2.0, 3.0, "placebo")]
        for trial, fee, slip, mode in trial_specs:
            if trial_filter is not None and trial not in trial_filter:
                continue
            s = signals
            if mode == "delay":
                s = s.with_columns(pl.when(pl.col("signal") == 0).then(0)
                                   .when(pl.col("signal").is_null()).then(None)
                                   .otherwise(pl.col("signal").shift(1).over("symbol")).fill_null(0).alias("signal"))
            elif mode == "placebo":
                s = (s.with_columns(pl.col("signal").shift(1).over("local_time").alias("signal"))
                     .with_columns(pl.when(pl.col("has_close") == True)
                                   .then(pl.col("signal")).otherwise(None).alias("signal")))
            result = Engine(DataFeed(prices_df=prices, signals_df=s), OpeningRange(), config(fee, slip)).run()
            out.append(save_result("c_opening_range_proxy", trial, symbol, result, {
                "cadence_minutes": cadence,
                "classification": "retrospective vendor index/CFD proxy; not mapped to Vest/Propr contract",
                "commission_bps_each_fill": fee, "slippage_bps_each_fill": slip,
                "resolution_deviation": "15m fallback; cannot satisfy requested next-5m execution" if cadence == 15 else None,
                "data_path": path,
            }))
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # Freeze source hashes and code identity before result recording.
    sources = [ROOT / p for p in ["data/processed/btcusdt_1h.parquet", "data/processed/ethusdt_1h.parquet",
        "data/processed/btc_1m.parquet", "data/processed/eth_1m.parquet", "data/processed/btc_funding.parquet",
        "data/processed/eth_funding.parquet", "data/processed/NAS100_5m_2017_2026.parquet",
        "data/processed/SPX500_USD_15m_2017_2026.parquet"]]
    manifest = {}
    for p in sources:
        if not p.exists():
            continue
        eligible = pl.scan_parquet(p).filter(pl.col("timestamp") < CUTOFF).collect().sort("timestamp")
        buffer = io.BytesIO()
        eligible.write_ipc(buffer)
        manifest[str(p.relative_to(ROOT))] = hashlib.sha256(buffer.getvalue()).hexdigest()
    (OUT / "data_hashes.json").write_text(json.dumps(manifest, indent=2))
    a = run_a()
    b, b_events = run_b()
    c = run_c()
    summary = {
        "head": __import__("subprocess").check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "cutoff_utc_exclusive": "2026-08-01T00:00:00Z",
        "status": "EXPLORATORY",
        "approval_status": "NOT_APPROVED",
        "tracks": {
            "A": {"decision": "INCONCLUSIVE", "results": a, "funding": "not applied; funding exists but native Engine has no cash-flow callback"},
            "B": {"decision": "BLOCKED", "blocker": "No timestamped liquidation/force-order source or verified coverage found in local data inventory.", "proxy_decision": "INCONCLUSIVE", "results": b, "event_study": b_events},
            "C": {"decision": "INCONCLUSIVE", "venue_parity": "BLOCKED", "results": c},
        },
        "source_hashes": manifest,
        "multiple_testing": "No DSR/PBO: historical trial ledger is incomplete.",
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
