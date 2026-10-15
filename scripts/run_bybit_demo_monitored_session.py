# pyright: reportMissingImports=false, reportUnknownParameterType=false, reportUnknownMemberType=false
"""Issue #51: 1-hour monitored Bybit Demo continuous paper execution session.

Drives the approved donchian_btc strategy (nine-lookback close channels and 60-bar volatility target)
via native LiveEngine -> SafeBroker -> BybitLiveBroker, exporting Prometheus metrics
on port 19147 for ml4t-prometheus and ml4t-grafana.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
from connectors.bybit.broker import BybitLiveBroker
from connectors.bybit.client import BybitClient
from connectors.bybit.config import BybitConfig, Environment, Mode
from connectors.bybit.feed import BybitKlineFeed
from connectors.bybit.journal import BybitIntentJournal
from dotenv import dotenv_values
from ml4t.backtest.strategy import Strategy

from promote.donchian_btc.src.independent_seven_native_features import donchian_btc
from src.bybit_paper_runtime import ReviewedPaperAccount, build_native_paper_engine
from src.ml4t_native_metrics import create_readonly_metrics_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bybit_demo_session")


def _positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value) and value > 0


class ExposureRule(Strategy):
    """Native broker performs all long/short sizing, cash, fees and fills."""

    def __init__(self, asset: str) -> None:
        super().__init__()
        self.asset = asset
        self.decisions = 0

    def on_data(
        self,
        timestamp: datetime,
        data: dict[str, Any],
        context: dict[str, Any],
        broker: Any,
    ) -> None:
        bar = data.get(self.asset)
        if not bar or not isinstance(bar, dict):
            return
        sig = bar.get("signals") or {}
        pct = sig.get("target_exposure")
        if pct is None or not math.isfinite(float(pct)):
            return
        price = float(bar["close"])
        equity = float(broker.equity() if hasattr(broker, "equity") else broker.get_account_value())
        if not _positive(price) or not _positive(equity):
            return
        pos = broker.get_position(self.asset)
        quantity = float(pos.quantity) if pos else 0.0
        # Bound target position to confirmed paper limits (max 0.02 BTC)
        target = min(0.02, max(-0.02, equity * float(pct) / price))
        delta = target - quantity
        # Bound single order size to max_order_shares (0.01 BTC)
        if abs(delta) > 0.01:
            delta = math.copysign(0.01, delta)
        delta = round(delta, 3)
        if abs(delta) * price > 1.0 and abs(delta) >= 0.001:
            logger.info(
                "ExposureRule: target_pct=%.3f, target_qty=%.4f, current=%.4f, delta=%.4f",
                pct,
                target,
                quantity,
                delta,
            )
            try:
                broker.submit_order(self.asset, delta)
                self.decisions += 1
            except Exception as err:  # noqa: BLE001
                logger.warning("Order submission rejected by broker/risk: %s", err)


class DonchianBTCStrategy(ExposureRule):
    """Exact donchian_btc research strategy with 9 lookbacks and volatility targeting."""

    def __init__(self, asset: str = "BTC/USDT:USDT", history_df: pl.DataFrame | None = None) -> None:
        super().__init__(asset)
        self.history: list[dict[str, Any]] = []
        if history_df is not None:
            self.history = history_df.to_dicts()
        self.bars_received = 0

    def on_data(
        self,
        timestamp: datetime,
        data: dict[str, Any],
        context: dict[str, Any],
        broker: Any,
    ) -> None:
        bar = data.get(self.asset)
        if not bar or not isinstance(bar, dict):
            return

        self.bars_received += 1
        record = {
            "timestamp": timestamp,
            "open": float(bar["open"]),
            "high": float(bar["high"]),
            "low": float(bar["low"]),
            "close": float(bar["close"]),
            "volume": float(bar["volume"]),
        }
        self.history.append(record)
        if len(self.history) > 300:
            self.history = self.history[-300:]

        logger.info(
            "Bar #%d @ %s | Close: %.1f High: %.1f Low: %.1f | History: %d bars",
            self.bars_received,
            timestamp.isoformat(),
            record["close"],
            record["high"],
            record["low"],
            len(self.history),
        )

        if len(self.history) >= 201:
            df = pl.DataFrame(self.history)
            features = donchian_btc(df)
            target_exposure = float(features["target_exposure"][-1])
            avg_dir = float(features["average_direction"][-1])
            vol_lev = float(features["vol_leverage"][-1])
            logger.info(
                "Donchian 9-channel features: target_exposure=%.4f, avg_dir=%.3f, vol_lev=%.2f",
                target_exposure,
                avg_dir,
                vol_lev,
            )
            bar_with_signal = dict(bar)
            bar_with_signal["signals"] = {"target_exposure": target_exposure}
            data_with_signal = {**data, self.asset: bar_with_signal}
            super().on_data(timestamp, data_with_signal, context, broker)


async def run_session(
    duration_minutes: float,
    metrics_port: int,
    evidence_path: Path,
) -> dict[str, Any]:
    demo_env = dotenv_values(Path.home() / ".config" / "trading-connector" / "bybit-demo.env")
    for k, v in demo_env.items():
        if v:
            os.environ[k] = v

    uid = os.environ["BYBIT_DEMO_EXPECTED_UID"]
    cfg = BybitConfig(
        environment=Environment.DEMO,
        mode=Mode.EXECUTION,
        api_key=os.environ["BYBIT_DEMO_API_KEY"],
        api_secret=os.environ["BYBIT_DEMO_API_SECRET"],
        expected_demo_uid=uid,
    )

    state_dir = Path("/home/quant/.local/state/quant-research")
    journal_file = state_dir / f"bybit-demo-account-{uid}-intents.sqlite"

    account = ReviewedPaperAccount(
        account_uid=uid,
        strategy_id="donchian_btc",
        allowed_assets=frozenset({"BTC/USDT:USDT"}),
        max_order_shares=0.01,
        max_order_value=1000.0,
        max_position_shares=0.02,
        max_position_value=2000.0,
        max_total_exposure=5000.0,
        max_positions=1,
        max_orders_per_minute=4,
        max_daily_loss=100.0,
        max_drawdown_pct=0.05,
        max_price_deviation_pct=0.50,
        max_data_staleness_seconds=300.0,
        dedup_window_seconds=1.0,
        feed_silence_seconds=130.0,
        max_event_age_seconds=300.0,
        max_recovery_attempts=3,
        recovery_cooldown_seconds=5.0,
        state_dir=state_dir,
        reviewed=True,
    )

    journal = BybitIntentJournal(journal_file)
    client = BybitClient(cfg)
    raw_broker = BybitLiveBroker(client=client, journal=journal)

    # Fetch initial 250 historical candles for strategy warm-start
    logger.info("Connecting BybitClient to fetch 250 historical candles for warm-start...")
    await client.connect()
    raw_candles = await client.fetch_ohlcv("BTC/USDT:USDT", timeframe="1m", limit=250)
    history_df = pl.DataFrame({
        "timestamp": [datetime.fromtimestamp(c[0] / 1000, UTC) for c in raw_candles],
        "open": [float(c[1]) for c in raw_candles],
        "high": [float(c[2]) for c in raw_candles],
        "low": [float(c[3]) for c in raw_candles],
        "close": [float(c[4]) for c in raw_candles],
        "volume": [float(c[5]) for c in raw_candles],
    })
    logger.info("Warm-start history loaded: %d bars", history_df.height)

    feed = BybitKlineFeed(
        asset="BTC/USDT:USDT",
        symbol="BTC/USDT:USDT",
        timeframe="1m",
        silence_seconds=130.0,
    )
    strategy = DonchianBTCStrategy(asset="BTC/USDT:USDT", history_df=history_df)
    engine = build_native_paper_engine(strategy, raw_broker, feed, account)
    safe_broker = engine.broker

    # Start loopback-only Prometheus metrics HTTP server on port 19147
    metrics_server = create_readonly_metrics_server(engine, safe_broker, port=metrics_port)
    server_thread = threading.Thread(target=metrics_server.serve_forever, daemon=True)
    server_thread.start()
    logger.info("Prometheus metrics server started at http://127.0.0.1:%d/metrics", metrics_port)

    session_start = datetime.now(UTC)
    planned_end = session_start + timedelta(minutes=duration_minutes)
    record: dict[str, Any] = {
        "issue": "hzminhzz/quant-research#51",
        "started_at": session_start.isoformat(),
        "planned_end_at": planned_end.isoformat(),
        "environment": "demo",
        "strategy_id": "donchian_btc",
        "symbol": "BTC/USDT:USDT",
        "duration_minutes_target": duration_minutes,
        "metrics_port": metrics_port,
        "status": "IN_PROGRESS",
    }

    try:
        logger.info("Connecting native LiveEngine to Bybit Demo...")
        await engine.connect()
        logger.info("Engine connected! Launching background run loop...")

        engine_task = asyncio.create_task(engine.run())
        check_interval = 30.0
        while datetime.now(UTC) < planned_end:
            if engine_task.done():
                exc = engine_task.exception()
                if exc:
                    logger.error("Engine terminated unexpectedly: %s", exc)
                break

            status = engine.runtime_status()
            logger.info(
                "Runtime status: state=%s, health=%s, bars=%d, decisions=%d, remaining=%.1f min",
                status.get("runtime_state"),
                status.get("health"),
                strategy.bars_received,
                strategy.decisions,
                (planned_end - datetime.now(UTC)).total_seconds() / 60.0,
            )
            await asyncio.sleep(check_interval)

        logger.info("Stopping native engine...")
        await engine.stop()
        await engine_task
        session_end = datetime.now(UTC)

        reconciliation = safe_broker.reconciliation_report or await safe_broker.preview_reconciliation_async()
        runtime_status = engine.runtime_status()

        record.update({
            "ended_at": session_end.isoformat(),
            "elapsed_minutes": (session_end - session_start).total_seconds() / 60.0,
            "status": "COMPLETED",
            "bars_received": strategy.bars_received,
            "decisions_made": strategy.decisions,
            "runtime_state": runtime_status.get("runtime_state"),
            "health": runtime_status.get("health"),
            "reconciliation_clean": bool(reconciliation.get("clean")),
            "reconciliation": reconciliation,
            "operational_events_count": len(engine.operational_events),
            "paper_qualified": bool(reconciliation.get("clean") and strategy.bars_received > 0),
            "live_money_authorized": False,
        })
    finally:
        metrics_server.shutdown()
        metrics_server.server_close()
        if safe_broker.is_connected:
            await safe_broker.disconnect()
        else:
            safe_broker.close_persistence()
        journal.close()

    evidence_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(evidence_path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2)
    logger.info("Session complete! Redacted evidence saved to %s", evidence_path)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-minutes", type=float, default=60.0, help="Observation duration in minutes")
    parser.add_argument("--metrics-port", type=int, default=19147, help="Prometheus metrics port")
    parser.add_argument(
        "--evidence-file",
        type=Path,
        default=Path("/home/quant/.local/state/quant-research/bybit-demo-monitored-session-evidence.json"),
        help="Path for session evidence JSON",
    )
    args = parser.parse_args()

    result = asyncio.run(run_session(args.duration_minutes, args.metrics_port, args.evidence_file))
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
