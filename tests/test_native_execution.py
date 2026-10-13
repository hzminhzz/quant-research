"""Native engine audit regressions. No market data or real order access."""
import json
from datetime import UTC, datetime, timedelta

import polars as pl
from ml4t.backtest import BacktestConfig, run_backtest
from ml4t.backtest.config import CommissionType, SlippageType
from ml4t.backtest.types import OrderStatus

from src.research_control.execution import (
    StopFirstBracket,
    execute_permitted_native,
    independent_fill_audit,
)
from tests.test_run_permit import intent, setup_trial


def synthetic_both_hit():
    start = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    opens = [100.0, 100.0, 101.0, 103.0, 102.0, 102.0, 101.0]
    highs = [101.0, 101.0, 102.0, 115.0, 103.0, 103.0, 102.0]
    lows = [99.0, 99.0, 100.0, 90.0, 101.0, 101.0, 100.0]
    return pl.DataFrame({
        "timestamp": [start + timedelta(days=i) for i in range(len(opens))],
        "symbol": ["SYN"] * len(opens),
        "open": opens,
        "high": highs,
        "low": lows,
        "close": opens,
        "volume": [100.0] * len(opens),
    })


def config():
    return BacktestConfig(
        initial_cash=1000.0, commission_type=CommissionType.PERCENTAGE,
        commission_rate=0.0, slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=0.0,
    )


def test_native_stop_first_order_and_independent_cash_audit():
    bars = synthetic_both_hit()
    strategy = StopFirstBracket(
        "SYN", signal_at=bars["timestamp"][1], quantity=1,
        stop_price=95.0, limit_price=110.0
    )
    result = run_backtest(bars, strategy, config=config())
    assert strategy.orders is not None
    entry, stop, limit = strategy.orders
    assert entry.status == stop.status == OrderStatus.FILLED
    assert limit.status == OrderStatus.CANCELLED
    assert result.to_fills_dataframe()["order_id"].to_list() == [
        entry.order_id, stop.order_id
    ]
    assert result.to_trades_dataframe().height == 1
    assert float(result.to_equity_dataframe()["equity"][-1]) == 994.0
    audit = independent_fill_audit(result, strategy, bars, initial_cash=1000.0)
    assert audit.status == "PASS"
    assert audit.reason_code == "NATIVE_EXECUTION_AUDITED"
    assert audit.evidence["stop_first"] is True
    assert audit.evidence["cash_final"] == 994.0


class UnsafeNativeBracket(StopFirstBracket):
    """Intentionally wrong native bracket order: limit before stop."""

    def on_data(self, timestamp, data, context, broker):
        if timestamp == self.signal_at and not self.submitted:
            self.submitted = True
            self.orders = broker.submit_bracket(
                self.symbol, self.quantity,
                take_profit=self.limit_price, stop_loss=self.stop_price
            )


def test_native_default_bracket_is_rejected_when_both_levels_touch():
    bars = synthetic_both_hit()
    strategy = UnsafeNativeBracket(
        "SYN", signal_at=bars["timestamp"][1], quantity=1,
        stop_price=95.0, limit_price=110.0
    )
    result = run_backtest(bars, strategy, config=config())
    assert float(result.to_equity_dataframe()["equity"][-1]) == 1009.0
    assert independent_fill_audit(result, strategy, bars, initial_cash=1000.0).reason_code == "ENGINE_EXECUTION_INVALID"


def test_independent_audit_detects_wrong_cash_and_unlinked_oco():
    bars = synthetic_both_hit()
    strategy = StopFirstBracket("SYN", signal_at=bars["timestamp"][1],
                                quantity=1, stop_price=95.0, limit_price=110.0)
    result = run_backtest(bars, strategy, config=config())
    assert independent_fill_audit(result, strategy, bars, initial_cash=1001.0).status == "BLOCKED"
    strategy.orders[2].parent_id = None
    assert independent_fill_audit(result, strategy, bars, initial_cash=1000.0).status == "BLOCKED"


def test_permit_binds_native_run_and_rejects_stale_frozen_data(tmp_path):
    bars, contract, computation, evidence = setup_trial(tmp_path)
    request = intent(bars, evidence)
    # Native one-position round-trip on local frozen research fixture only.
    audit = execute_permitted_native(
        str(tmp_path), request, computation, bars, contract,
        signal_at=bars["timestamp"][1], quantity=1,
        stop_price=99.0, limit_price=101.4, initial_cash=1_000_000.0,
        artifact_dir="run_log/synthetic/native-run-1"
    )
    assert audit.status == "PASS", audit
    assert audit.live_execution_qualified is False
    assert audit.evidence["trade_count"] == 1
    recorded = json.loads((tmp_path / "run_log/synthetic/native-run-1/execution_audit.json").read_text())
    assert recorded["permit_sha256"] and recorded["qualification"] == "HISTORICAL_SIMULATION_ONLY"
    assert (tmp_path / "run_log/synthetic/native-run-1/native/manifest.json").is_file()

    (tmp_path / "src/strategy.py").write_text("RULE_VERSION = 999\n", encoding="utf-8")
    blocked = execute_permitted_native(
        str(tmp_path), request, computation, bars, contract,
        signal_at=bars["timestamp"][1], quantity=1,
        stop_price=99.0, limit_price=101.4, initial_cash=1_000_000.0
    )
    assert blocked.status == "BLOCKED"
    assert blocked.reason_code == "IDENTITY_DRIFT"


def test_permit_rejects_future_signal_and_bad_source(tmp_path):
    bars, contract, computation, evidence = setup_trial(tmp_path)
    request = intent(bars, evidence)
    audit = execute_permitted_native(
        str(tmp_path), request, computation, bars, contract,
        signal_at=bars["timestamp"][-1] + timedelta(days=1),
        quantity=1, stop_price=99, limit_price=101
    )
    assert audit.reason_code == "FEATURE_CAUSALITY_FAIL"
    request["expected_source_symbol"] = "NQ.F"
    denied = execute_permitted_native(
        str(tmp_path), request, computation, bars, contract,
        signal_at=bars["timestamp"][1], quantity=1, stop_price=99,
        limit_price=101
    )
    assert denied.reason_code == "SOURCE_IDENTITY_CONFLICT"
