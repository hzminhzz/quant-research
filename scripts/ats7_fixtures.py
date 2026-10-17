"""Credential-free, explicitly synthetic ATS-7 engineering fixtures."""
from __future__ import annotations

import hashlib
import inspect
import json
import platform
import sqlite3
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path

from connectors.bybit import broker, client, config, feed, journal
from ml4t.live import engine, safety

from src.release_contracts import ReleaseManifest
from src.release_probe import SyntheticCycle
from src.research_control.action_authorization import canonical_json

ROOT = Path(__file__).resolve().parents[1]


def local_manifest(*, name="ats7-synthetic-local-v1", domain="ats7-local", now=None, public_feed=False):
    now = now or datetime.now(UTC)
    entries = [
        ("strategy", Path(inspect.getfile(SyntheticCycle))),
        ("dependencies", ROOT / "uv.lock"),
        ("native_live", Path(safety.__file__)),
        ("native_engine", Path(engine.__file__)),
        ("connector", Path(broker.__file__)),
        ("connector_client", Path(client.__file__)),
        ("connector_config", Path(config.__file__)),
        ("connector_journal", Path(journal.__file__)),
        ("connector_feed", Path(feed.__file__)),
        ("release_contracts", ROOT / "src/release_contracts.py"),
        ("release_journal", ROOT / "src/release_journal.py"),
        ("release_runtime", ROOT / "src/release_runtime.py"),
        ("native_audit_wrapper", ROOT / "src/research_control/ats3_audit_broker.py"),
        ("terms", ROOT / "docs/architecture/trading_system/ats7_qualification_plan.md"),
    ]
    sources = [{"role": role, "path": str(path.resolve()),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for role, path in entries]
    plan_hash = sources[-1]["sha256"]
    for path in sorted(Path(safety.__file__).parent.glob("*.py")):
        if str(path.resolve()) not in {s["path"] for s in sources}:
            sources.append({"role": "native_component", "path": str(path.resolve()),
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    sources.append({"role": "fixture_definition", "path": str(Path(__file__).resolve()),
                    "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    obj = {
        "name": name, "environment": "LOCAL_PAPER", "account_ref": "local:ats7-engineering",
        "risk_domain": domain, "provider": "ml4t-native",
        "endpoint": "local://ml4t-virtual-portfolio",
        "strategy": {"module": SyntheticCycle.__module__, "class_name": SyntheticCycle.__name__,
                     "parameters_json": canonical_json({"asset": "BTC/USDT:USDT", "quantity": 0.001}).decode(),
                     "signal_timing": "completed UTC bar; even-minute open, odd-minute close; SYNTHETIC ONLY",
                     "scientific_status": "SYNTHETIC_ENGINEERING", "research_evidence_sha256": plan_hash},
        "portfolio_json": canonical_json({"members": [name], "allocation": "fixed 0.001 synthetic BTC",
                                          "single_account_single_risk_owner": True}).decode(),
        "products": [{"asset": "BTC/USDT:USDT", "venue_symbol": "BTCUSDT", "kind": "synthetic",
                      "quantity_step": "0.001", "price_tick": "0.1", "minimum_quantity": "0.001",
                      "minimum_notional": "5", "position_mode": "one_way", "margin_mode": "native_cash_simulation",
                      "specification_sha256": plan_hash}],
        "risk": {"capital": 100000.0, "max_order_shares": 0.01, "max_order_value": 1000.0,
                 "max_position_shares": 0.02, "max_position_value": 2000.0, "max_total_exposure": 2000.0,
                 "max_positions": 1, "max_orders_per_minute": 4, "max_daily_loss": 100.0,
                 "max_drawdown_pct": 0.01, "max_price_deviation_pct": 0.10,
                 "max_data_staleness_seconds": 300.0, "dedup_window_seconds": 0.001},
        "operations": {"bar_seconds": 60, "max_clock_skew_seconds": 5.0, "max_account_age_seconds": 15.0,
                       "feed_silence_seconds": 130.0, "observation_days": 28, "minimum_cycles": 1,
                       "minimum_bar_coverage": 0.99, "owner": "ATS7 operator",
                       "rollback_procedure": "halt, preserve both journals and exposure, restore exact bound code; separately authorize resume",
                       "monitoring_requirements": ["supervised_process", "fresh_bars", "reconciliation", "halt_state", "delivered_alert"],
                       "halt_policy": "latch_no_new_risk", "recovery_policy": "reconcile_then_separate_resume",
                       "expiry_policy": "block_open_preserve_obligations"},
        "account_terms_sha256": plan_hash, "account_terms_source": str(entries[-1][1]),
        "account_terms_effective_at": (now - timedelta(days=1)).isoformat(),
        "data_cost_calendar_execution_json": canonical_json({
            "feed": "public Bybit completed 1m bars" if public_feed else "frozen synthetic OHLCV fixture",
            "feed_class": "connectors.bybit.feed.BybitKlineFeed" if public_feed else "scripts.ats7_fixtures.FixtureFeed",
            "feed_parameters": {"asset": "BTC/USDT:USDT", "symbol": "BTC/USDT:USDT", "timeframe": "1m",
                                "max_age_seconds": 120.0, "silence_seconds": 130.0} if public_feed else {},
            "calendar": "UTC 24/7",
            "matching": "native VirtualPortfolio immediate simulated fill at observed reference",
            "commission": "native shadow simulator does not model commissions",
            "financing": "not modeled; no provider funding claim", "live_money": False,
            "purpose": "engineering only, not strategy economics or realistic backtest parity",
            "deployment": {"python": platform.python_version(), "machine": platform.machine(),
                           "sqlite": sqlite3.sqlite_version}}).decode(),
        "native_versions_json": canonical_json({k: version(k) for k in
                                                ("ml4t-live", "ml4t-backtest", "ml4t-engineer", "ml4t-diagnostic", "ccxt", "cryptography")}).decode(),
        "sources": sources, "qualification_evidence": [],
        "not_before": (now - timedelta(hours=1)).isoformat(),
        "expires_at": (now + timedelta(days=35)).isoformat(),
    }
    return ReleaseManifest.model_validate_json(json.dumps(obj))


def bar(price=80000.0):
    return {"BTC/USDT:USDT": {"open": price, "high": price + 10, "low": price - 10,
                              "close": price, "volume": 1.0}}


class FixtureFeed:
    """Finite raw observations, not a fill simulator."""
    def __init__(self, rows):
        self.rows = list(rows)
        self.started = False

    async def start(self):
        self.started = True

    def stop(self):
        self.started = False

    async def close(self):
        self.started = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.rows:
            raise StopAsyncIteration
        return self.rows.pop(0)


def cycle_rows():
    start = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(minutes=3)
    if start.minute % 2:
        start -= timedelta(minutes=1)
    return [(start + timedelta(minutes=i), bar(80000.0 + i * 100), {}) for i in range(4)]
