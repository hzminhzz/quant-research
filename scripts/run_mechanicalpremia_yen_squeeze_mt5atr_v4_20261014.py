"""Run the six frozen native Engine trials after preregistered gates pass."""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from ml4t.diagnostic.api import PortfolioAnalysis

from scripts.mechanicalpremia_yen_squeeze_mt5atr_proxy_v4_20261014 import (
    DEV_END, GBPJPY, ROOT, SESSION, USDJPY, load_prices, run_engine,
)

SESSION_DIR = ROOT / "run_log/research_sessions" / SESSION
TRIAL_DIR = ROOT / "run_log/mechanicalpremia_yen_squeeze_mt5atr_v4_20261014"


def _clean(value: Any) -> Any:
    if isinstance(value, np.generic):
        return _clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_clean(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _risk(returns: pl.Series) -> dict[str, Any]:
    if returns.is_empty():
        return {"observations": 0, "status": "INCONCLUSIVE_EMPTY_DAILY_RETURNS"}
    metrics = PortfolioAnalysis(
        returns=returns.to_numpy(), periods_per_year=252,
    ).compute_summary_stats()
    return {k: _clean(v) for k, v in vars(metrics).items()
            if isinstance(v, (str, int, float, np.generic, type(None)))}


def _periods(daily: pl.DataFrame) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for name, keys in (("year", ["year"]), ("quarter", ["year", "quarter"])):
        keyed = daily.with_columns(
            pl.col("date").dt.year().alias("year"),
            pl.col("date").dt.quarter().alias("quarter"),
        )
        rows = []
        for key, frame in keyed.partition_by(keys, as_dict=True, maintain_order=True).items():
            key_values = key if isinstance(key, tuple) else (key,)
            returns = frame["return_pct"]
            rows.append({
                **dict(zip(keys, key_values)),
                "days": frame.height,
                "start": str(frame["date"].min()),
                "end": str(frame["date"].max()),
                "first_close_equity": float(frame["close_equity"][0]),
                "last_close_equity": float(frame["close_equity"][-1]),
                "native_diagnostic_metrics": _risk(returns),
            })
        result[name] = rows
    return result


def _write_trial(lookback: int, pips: int, minutes: pl.DataFrame) -> dict[str, Any]:
    strategy, engine, native = run_engine(minutes, lookback=lookback, roundtrip_jpy=pips * 0.01)
    name = f"PORTFOLIO-{lookback}-{pips}PIP"
    out = TRIAL_DIR / name
    out.mkdir(parents=True, exist_ok=False)
    fills = native.to_fills_dataframe()
    trades = native.to_trades_dataframe()
    daily = native.to_daily_pnl(session_aligned=False)
    dual_fill_groups = (
        fills.group_by("asset", "timestamp").agg(pl.col("side").n_unique().alias("sides"), pl.len().alias("fills"))
        .filter(pl.col("sides") > 1)
        if fills.height else pl.DataFrame()
    )
    fills.write_parquet(out / "native_fills.parquet")
    trades.write_parquet(out / "native_trades.parquet")
    daily.write_parquet(out / "native_daily_equity.parquet")

    closed = trades.filter(pl.col("status") == "closed") if trades.height else trades
    open_trades = trades.filter(pl.col("status") == "open") if trades.height else trades
    per_pair = {}
    for symbol in ("USDJPY", "GBPJPY", "CADJPY"):
        part = trades.filter(pl.col("symbol") == symbol) if trades.height else trades
        done = part.filter(pl.col("status") == "closed") if part.height else part
        per_pair[symbol] = {
            "trades": part.height,
            "closed_trades": done.height,
            "open_trades": part.filter(pl.col("status") == "open").height if part.height else 0,
            "net_pnl_native_trade_ledger_usd": float(part["pnl"].sum()) if part.height else 0.0,
            "closed_win_rate": float((done["pnl"] > 0).mean()) if done.height else None,
            "closed_expectancy_usd": float(done["pnl"].mean()) if done.height else None,
        }

    returns = native.to_daily_returns(session_aligned=False)
    diagnostic = _risk(returns)
    state = native.portfolio_state[-1] if native.portfolio_state else None
    summary = {
        "schema_version": 1,
        "session_id": SESSION,
        "trial_id": name,
        "classification": "EXPLORATORY",
        "approval_status": "NOT_APPROVED",
        "status": "completed",
        "lookback_h1": lookback,
        "roundtrip_cost_jpy": pips * 0.01,
        "per_fill_slippage_jpy": pips * 0.005,
        "per_fill_slippage_usd": pips * 0.005 / 150,
        "input_symbols": ["USDJPY", "GBPJPY", "CADJPY"],
        "input_timestamps_max_exclusive": str(DEV_END),
        "native_engine": "ml4t.backtest.Engine",
        "native_feature_library": "ml4t-engineer",
        "native_metrics": _clean(native.metrics),
        "daily_equity_diagnostic_metrics": diagnostic,
        "native_trade_counts": {
            "total": trades.height,
            "closed": closed.height,
            "open": open_trades.height,
            "win_rate_closed": float((closed["pnl"] > 0).mean()) if closed.height else None,
            "expectancy_closed_usd": float(closed["pnl"].mean()) if closed.height else None,
        },
        "native_end_equity_usd": float(native.metrics["final_value"]),
        "native_net_profit_usd": float(native.metrics["final_value"] - native.metrics["initial_cash"]),
        "native_daily_equity": {
            "rows": daily.height,
            "start": str(daily["date"].min()) if daily.height else None,
            "end": str(daily["date"].max()) if daily.height else None,
            "period_breakdown": _periods(daily),
        },
        "pair_attribution_from_native_trade_ledger": per_pair,
        "entry_protection_gap_bars": len(strategy.entry_gap_bars),
        "unprotected_entry_bar_stop_breaches": len(strategy.gap_breaches),
        "entry_protection_gap_evidence": strategy.entry_gap_bars,
        "unprotected_breach_evidence": strategy.gap_breaches,
        "pending_order_expirations_cancelled_natively": len(strategy.expired),
        "decision_bar_spans_both_channel_count": len(strategy.ambiguous_minutes),
        "same_minute_opposite_native_fill_groups": dual_fill_groups.to_dicts(),
        "same_minute_opposite_native_fill_count": dual_fill_groups.height,
        "native_rejected_orders": [str(x) for x in native.rejected_orders],
        "native_account_state_final": _clean(state),
        "native_artifacts": {
            "fills": "native_fills.parquet",
            "trades": "native_trades.parquet",
            "daily_equity": "native_daily_equity.parquet",
        },
        "limitations": [
            "CADJPY is Dukascopy bid-only staging, not canonical data; no exact session acceptance manifest exists.",
            "GBPJPY source timestamps were localized to UTC under an unverified assumption.",
            "Fixed 150 JPY/USD is an invariant proxy numeraire, not historical conversion.",
            "No historical bid/ask, financing, swap, broker contract or margin evidence.",
            "MT5-style iATR uses registered ML4T TRANGE -> SMA14, upper-median certified registry extension; original MT5 tester parity is unverified.",
            "Engine protective stop is installed after entry-bar callback; breached entry bars are delayed to the next eligible native order fill and counted.",
            "Native Engine dual pending-stop sequencing is retained and ambiguity is counted; no OCO is assumed.",
            "This is development evidence only, not broker equivalence or approval.",
        ],
    }
    (out / "summary.json").write_text(json.dumps(_clean(summary), indent=2, sort_keys=True) + "\n")
    for filename in ("summary.json", "native_fills.parquet", "native_trades.parquet", "native_daily_equity.parquet"):
        path = out / filename
        summary.setdefault("artifact_sha256", {})[filename] = hashlib.sha256(path.read_bytes()).hexdigest()
    (out / "manifest.json").write_text(json.dumps(_clean({
        "session_id": SESSION, "trial_id": name, "artifacts": summary["artifact_sha256"],
    }), indent=2, sort_keys=True) + "\n")
    del native, engine, strategy, fills, trades, daily, returns
    gc.collect()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lookback", type=int, choices=(20, 500), required=True)
    parser.add_argument("--pips", type=int, choices=(2, 4, 6), required=True)
    args = parser.parse_args()
    minutes = load_prices()
    summary = _write_trial(args.lookback, args.pips, minutes)
    print(json.dumps({
        "trial_id": summary["trial_id"],
        "status": summary["status"],
        "native_trade_counts": summary["native_trade_counts"],
        "net_profit_usd": summary["native_net_profit_usd"],
        "daily_equity_diagnostic_metrics": summary["daily_equity_diagnostic_metrics"],
        "entry_protection_gap_bars": summary["entry_protection_gap_bars"],
        "unprotected_entry_bar_stop_breaches": summary["unprotected_entry_bar_stop_breaches"],
    }, indent=2, default=str), flush=True)


if __name__ == "__main__":
    main()
