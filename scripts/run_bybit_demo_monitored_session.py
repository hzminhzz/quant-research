# pyright: reportMissingImports=false, reportUnknownParameterType=false, reportUnknownMemberType=false
"""Issue #51: 1-hour monitored Bybit Demo continuous paper execution session.

Drives the confirmed Donchian BTC strategy on BTC/USDT:USDT (1m Bybit completed bars)
via native LiveEngine -> SafeBroker -> BybitLiveBroker, exporting Prometheus metrics
on port 19147 for ml4t-prometheus and ml4t-grafana.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from connectors.bybit.broker import BybitLiveBroker
from connectors.bybit.client import BybitClient
from connectors.bybit.config import BybitConfig, Environment, Mode
from connectors.bybit.feed import BybitKlineFeed
from connectors.bybit.journal import BybitIntentJournal
from dotenv import dotenv_values
from ml4t.backtest.strategy import Strategy
from ml4t.backtest.types import OrderType

from src.bybit_paper_runtime import ReviewedPaperAccount, build_native_paper_engine
from src.ml4t_native_metrics import create_readonly_metrics_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bybit_demo_session")


class DonchianPaperStrategy(Strategy):
    """Native ML4T Strategy implementing 20-bar Donchian trend following on BTC/USDT:USDT."""

    def __init__(self, asset: str = "BTC/USDT:USDT", lookback: int = 20) -> None:
        super().__init__()
        self.asset = asset
        self.lookback = lookback
        self.highs: list[float] = []
        self.lows: list[float] = []
        self.closes: list[float] = []
        self.bars_received: int = 0
        self.orders_placed: int = 0

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
        high = float(bar["high"])
        low = float(bar["low"])
        close = float(bar["close"])
        self.highs.append(high)
        self.lows.append(low)
        self.closes.append(close)

        logger.info(
            "Bar #%d @ %s | Close: %.1f High: %.1f Low: %.1f",
            self.bars_received,
            timestamp.isoformat(),
            close,
            high,
            low,
        )

        if len(self.closes) <= self.lookback:
            return

        # Donchian channel over previous lookback bars (excluding current bar)
        upper = max(self.highs[-self.lookback - 1 : -1])
        lower = min(self.lows[-self.lookback - 1 : -1])

        pos = broker.get_position(self.asset)
        qty = float(pos.quantity) if pos else 0.0

        if close > upper and qty <= 0:
            target = 0.001
            delta = target - qty
            logger.info("Donchian Upper Breakout (%.1f > %.1f): ordering +%.3f BTC", close, upper, delta)
            broker.submit_order(self.asset, delta, order_type=OrderType.LIMIT, limit_price=close)
            self.orders_placed += 1
        elif close < lower and qty >= 0:
            if qty > 0:
                logger.info("Donchian Lower Breakdown (%.1f < %.1f): closing position -%.3f BTC", close, lower, qty)
                broker.submit_order(self.asset, -qty, order_type=OrderType.MARKET, reduce_only=True)
                self.orders_placed += 1


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
        max_price_deviation_pct=0.05,
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
    feed = BybitKlineFeed(
        asset="BTC/USDT:USDT",
        symbol="BTC/USDT:USDT",
        timeframe="1m",
        silence_seconds=130.0,
    )
    strategy = DonchianPaperStrategy(asset="BTC/USDT:USDT", lookback=20)
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
                "Runtime status: state=%s, health=%s, bars=%d, orders=%d, remaining=%.1f min",
                status.get("runtime_state"),
                status.get("health"),
                strategy.bars_received,
                strategy.orders_placed,
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
            "orders_placed": strategy.orders_placed,
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
