"""Independent raw numerical audit of saved ATS-2 native artifacts.

Reads actual saved native Parquet files (fills, trades, equity, portfolio
state, daily PnL, metrics) and validates them against the raw input bars and
the action parameters. Does not trust the worker manifest status, audit
evidence hash, or checkpoint checksums. The same arithmetic is used by
verify_result and the outside judge.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
import yaml

INITIAL_CASH = 1_000_000.0
TOL = 1e-7
REQUIRED_NATIVE = (
    "config.yaml", "daily_pnl.parquet", "equity.parquet", "fills.parquet",
    "manifest.json", "metrics.json", "portfolio_state.parquet",
    "rejected_orders.parquet", "spec.yaml", "trades.parquet",
)


class AuditReject(ValueError):
    """Raised when saved native evidence contradicts independent arithmetic."""
    def __init__(self, reason_code: str, detail: str = ""):
        self.reason_code = reason_code.split(":", 1)[0]
        self.detail = detail or reason_code
        super().__init__(f"{self.reason_code}:{self.detail}")


def _check(condition: bool, reason: str) -> None:
    if not condition:
        raise AuditReject(reason)


def _close(actual: Any, expected: float, reason: str, tol: float = TOL) -> None:
    try:
        value = float(actual)
    except (TypeError, ValueError):
        raise AuditReject(reason) from None
    _check(math.isfinite(value) and math.isclose(value, expected, rel_tol=0, abs_tol=tol), reason)


def _ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo is not None else value
    parsed = datetime.fromisoformat(str(value))
    return parsed.astimezone(UTC).replace(tzinfo=None) if parsed.tzinfo is not None else parsed

def _file_hash(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
        raise AuditReject(f"UNSAFE_OR_OVERSIZE_FILE:{path.name}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def expected_trades(bars: pl.DataFrame, action: dict[str, Any]) -> tuple[list[dict[str, Any]], float]:
    """Independently compute the expected bracket fills from raw bars + action."""
    params = action["parameters"]
    signal = _ts(params["signal_at"])
    quantity = float(params["quantity"])
    stop, target = float(params["stop_price"]), float(params["limit_price"])
    _check(quantity > 0 and quantity.is_integer(), "QUANTITY_OUT_OF_SUPPORTED_SCOPE")
    _check(0 < stop < target, "BRACKET_LEVELS_INVALID")
    rows = bars.to_dicts()
    signal_indices = [i for i, row in enumerate(rows) if _ts(row["timestamp"]) == signal]
    _check(len(signal_indices) == 1 and signal_indices[0] + 1 < len(rows), "SIGNAL_BAR_INVALID")
    entry_i = signal_indices[0] + 1
    entry = rows[entry_i]
    symbol = str(entry["symbol"])
    _check(all(str(row["symbol"]) == symbol for row in rows), "MULTI_SYMBOL_OUT_OF_SCOPE")
    fills = [{"side": "buy", "quantity": quantity, "price": float(entry["open"]),
              "time": _ts(entry["timestamp"]), "kind": "market"}]
    for row in rows[entry_i + 1:]:
        open_price, low, high = map(float, (row["open"], row["low"], row["high"]))
        stop_hit = open_price <= stop or low <= stop
        target_hit = high >= target
        if stop_hit:
            fills.append({"side": "sell", "quantity": quantity,
                          "price": min(open_price, stop),
                          "time": _ts(row["timestamp"]), "kind": "stop"})
            break
        if target_hit:
            fills.append({"side": "sell", "quantity": quantity, "price": target,
                          "time": _ts(row["timestamp"]), "kind": "limit"})
            break
    _check(len(fills) == 2, "NO_BRACKET_EXIT_IN_RAW_WINDOW")
    return fills, float(rows[-1]["close"])


def audit_native_outputs(
    root: Path, native_dir: Path, bars: pl.DataFrame,
    action: dict[str, Any] | Any, contract_doc: dict[str, Any],
) -> dict[str, Any]:
    """Independently reconcile saved native artifacts against raw bars + action.

    Returns a dict with the expected numerical values. Raises AuditReject on
    any mismatch. Does not trust the manifest or checkpoint.
    """
    if hasattr(action, "model_dump"):
        action = action.model_dump(mode="json")
    _check(native_dir.is_dir() and not native_dir.is_symlink(), "NATIVE_OUTPUT_MISSING")
    names = {item.name for item in native_dir.iterdir()}
    missing = set(REQUIRED_NATIVE) - names
    _check(not missing, f"NATIVE_COMPONENT_MISSING:{sorted(missing)}")
    # Validate manifest completeness.
    manifest_path = native_dir / "manifest.json"
    _check(manifest_path.is_file() and not manifest_path.is_symlink(), "NATIVE_MANIFEST_MISSING")
    if manifest_path.stat().st_size > 10 * 1024 * 1024:
        raise AuditReject("UNSAFE_OR_OVERSIZE_FILE:manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _check(isinstance(manifest, dict), "NATIVE_MANIFEST_INVALID")
    _check(manifest.get("complete") is True, "NATIVE_MANIFEST_INCOMPLETE")

    # Validate config execution mode.
    config_path = native_dir / "config.yaml"
    _check(config_path.is_file() and not config_path.is_symlink(), "NATIVE_CONFIG_MISSING")
    if config_path.stat().st_size > 10 * 1024 * 1024:
        raise AuditReject("UNSAFE_OR_OVERSIZE_FILE:config.yaml")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    _check(isinstance(config, dict), "NATIVE_CONFIG_INVALID")
    exec_cfg = config.get("execution", {})
    _check(exec_cfg.get("execution_mode") == "next_bar", "CONFIG_EXECUTION_DRIFT")

    # Validate spec.yaml consistency with config.yaml.
    spec_path = native_dir / "spec.yaml"
    _check(spec_path.is_file() and not spec_path.is_symlink(), "NATIVE_SPEC_MISSING")
    if spec_path.stat().st_size > 10 * 1024 * 1024:
        raise AuditReject("UNSAFE_OR_OVERSIZE_FILE:spec.yaml")
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    _check(isinstance(spec, dict), "NATIVE_SPEC_INVALID")
    spec_cash = spec.get("config", {}).get("cash", {}).get("initial")
    cfg_cash = config.get("cash", {}).get("initial")
    _check(spec_cash == cfg_cash == INITIAL_CASH, "SPEC_CONFIG_MISMATCH")

    # Validate rejected orders (must be empty for clean execution).
    rejected_path = native_dir / "rejected_orders.parquet"
    _check(rejected_path.is_file() and not rejected_path.is_symlink(), "NATIVE_REJECTED_ORDERS_MISSING")
    rejected = pl.read_parquet(rejected_path)
    _check(rejected.height == 0, "UNEXPECTED_REJECTED_ORDERS")

    expected, last_close = expected_trades(bars, action)

    # Validate fills against saved native fills.
    fills_path = native_dir / "fills.parquet"
    _check(fills_path.is_file() and not fills_path.is_symlink(), "NATIVE_FILLS_MISSING")
    fills = pl.read_parquet(fills_path)
    _check(fills.height == 2, "FILL_COUNT_MISMATCH")
    for index, exp in enumerate(expected):
        actual = fills.row(index, named=True)
        _check(actual["side"] == exp["side"] and actual["order_type"] == exp["kind"],
               "FILL_SIDE_OR_TYPE_MISMATCH")
        _check(actual["asset"] == contract_doc["dataset"]["source_symbol"], "FILL_SYMBOL_MISMATCH")
        _check(_ts(actual["timestamp"]) == exp["time"], "FILL_TIME_MISMATCH")
        _close(actual["quantity"], exp["quantity"], "FILL_QUANTITY_MISMATCH")
        _close(actual["price"], exp["price"], "FILL_PRICE_MISMATCH", 1e-8)
        _close(actual["commission"], 0.0, "FILL_COMMISSION_MISMATCH")
        _close(actual["slippage"], 0.0, "FILL_SLIPPAGE_MISMATCH")

    # Independent cash/position arithmetic from saved fills.
    cash = INITIAL_CASH
    shares = 0.0
    for exp in expected:
        signed = exp["quantity"] if exp["side"] == "buy" else -exp["quantity"]
        cash -= signed * exp["price"]
        shares += signed
    _check(abs(shares) <= TOL, "OPEN_POSITION_AFTER_BRACKET")
    final_equity = cash + shares * last_close
    gross_pnl = expected[1]["quantity"] * (expected[1]["price"] - expected[0]["price"])

    # Validate trades.
    trades_path = native_dir / "trades.parquet"
    _check(trades_path.is_file() and not trades_path.is_symlink(), "NATIVE_TRADES_MISSING")
    trades = pl.read_parquet(trades_path)
    _check(trades.height == 1, "TRADE_COUNT_MISMATCH")
    trade = trades.row(0, named=True)
    _check(trade["symbol"] == contract_doc["dataset"]["source_symbol"]
           and trade["direction"] == "long" and trade["status"] == "closed", "TRADE_IDENTITY_MISMATCH")
    _check(_ts(trade["entry_time"]) == expected[0]["time"]
           and _ts(trade["exit_time"]) == expected[1]["time"], "TRADE_CLOCK_MISMATCH")
    _close(trade["entry_price"], expected[0]["price"], "TRADE_ENTRY_PRICE_MISMATCH", 1e-8)
    _close(trade["exit_price"], expected[1]["price"], "TRADE_EXIT_PRICE_MISMATCH", 1e-8)
    _close(trade["quantity"], expected[0]["quantity"], "TRADE_QUANTITY_MISMATCH")
    _close(trade["gross_pnl"], gross_pnl, "TRADE_GROSS_PNL_MISMATCH")
    _close(trade["pnl"], gross_pnl, "TRADE_NET_PNL_MISMATCH")
    _close(trade["fees"], 0, "TRADE_FEES_MISMATCH")

    # Validate portfolio state and equity bar-by-bar.
    portfolio_path = native_dir / "portfolio_state.parquet"
    equity_path = native_dir / "equity.parquet"
    _check(portfolio_path.is_file() and not portfolio_path.is_symlink(), "NATIVE_PORTFOLIO_MISSING")
    _check(equity_path.is_file() and not equity_path.is_symlink(), "NATIVE_EQUITY_MISSING")
    portfolio = pl.read_parquet(portfolio_path)
    equity = pl.read_parquet(equity_path)
    _check(portfolio.height == bars.height and equity.height == bars.height,
           "EQUITY_SERIES_LENGTH_MISMATCH")
    fill_at = {row["time"]: row for row in expected}
    cash_now, shares_now, high_water = INITIAL_CASH, 0.0, INITIAL_CASH
    prev_equity = INITIAL_CASH
    for index, bar in enumerate(bars.to_dicts()):
        moment = _ts(bar["timestamp"])
        fill = fill_at.get(moment)
        if fill:
            signed = fill["quantity"] if fill["side"] == "buy" else -fill["quantity"]
            cash_now -= signed * fill["price"]
            shares_now += signed
        mark = float(bar["close"])
        expected_equity = cash_now + shares_now * mark
        p = portfolio.row(index, named=True)
        e = equity.row(index, named=True)
        _check(_ts(p["timestamp"]) == moment and _ts(e["timestamp"]) == moment,
               "EQUITY_CLOCK_MISMATCH")
        _close(p["cash"], cash_now, "PORTFOLIO_CASH_MISMATCH")
        _close(p["equity"], expected_equity, "PORTFOLIO_EQUITY_MISMATCH")
        _close(p["gross_exposure"], abs(shares_now * mark), "PORTFOLIO_GROSS_EXPOSURE_MISMATCH")
        _close(p["net_exposure"], shares_now * mark, "PORTFOLIO_NET_EXPOSURE_MISMATCH")
        _check(p["open_positions"] == (1 if abs(shares_now) > TOL else 0),
               "PORTFOLIO_POSITION_COUNT_MISMATCH")
        _close(e["equity"], expected_equity, "EQUITY_MARK_MISMATCH")
        _close(e["return"], expected_equity / prev_equity - 1, "EQUITY_RETURN_MISMATCH", 1e-10)
        high_water = max(high_water, expected_equity)
        _close(e["high_water_mark"], high_water, "EQUITY_HWM_MISMATCH")
        _close(e["drawdown"], expected_equity / high_water - 1, "EQUITY_DRAWDOWN_MISMATCH", 1e-10)
        prev_equity = expected_equity

    # Validate metrics.
    metrics_path = native_dir / "metrics.json"
    _check(metrics_path.is_file() and not metrics_path.is_symlink(), "NATIVE_METRICS_MISSING")
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    _close(metrics["initial_cash"], INITIAL_CASH, "METRICS_INITIAL_CASH_MISMATCH")
    _close(metrics["final_value"], final_equity, "METRICS_FINAL_VALUE_MISMATCH")
    _close(metrics["total_gross_pnl"], gross_pnl, "METRICS_GROSS_PNL_MISMATCH")
    _check(metrics["num_trades"] == 1 and metrics["num_fills"] == 2,
           "METRICS_ACTIVITY_MISMATCH")

    # Validate daily PnL.
    daily_path = native_dir / "daily_pnl.parquet"
    _check(daily_path.is_file() and not daily_path.is_symlink(), "NATIVE_DAILY_PNL_MISSING")
    daily = pl.read_parquet(daily_path)
    _check(daily.height == 1, "DAILY_PNL_ROW_COUNT_MISMATCH")
    _close(daily["close_equity"][0], final_equity, "DAILY_FINAL_EQUITY_MISMATCH")
    _close(daily["pnl"][0], gross_pnl, "DAILY_PNL_MISMATCH")

    return {
        "attempt_id": action.get("trial_id", "unknown"),
        "expected": {"fills": expected, "ending_cash": cash, "ending_equity": final_equity,
                     "gross_pnl": gross_pnl},
        "input_hashes": {
            "fills": _file_hash(fills_path),
            "equity": _file_hash(equity_path),
            "trades": _file_hash(trades_path),
            "portfolio": _file_hash(portfolio_path),
            "metrics": _file_hash(metrics_path),
            "daily_pnl": _file_hash(daily_path),
        },
    }
