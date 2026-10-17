"""Run three preregistered attribution filters on the frozen BTC reversal baseline."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path

import polars as pl
import yaml

import scripts.run_btc_structure_reversal as parent_runner
from src.btc_structure_reversal import build_signal_frame, simulate_period
from src.btc_structure_reversal_attribution import add_attribution_features, with_trial_signal


ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "btc_structure_reversal_attribution_20261006.yaml"
PARENT_CFG = ROOT / "config" / "btc_structure_reversal_20261006.yaml"
PARENT_RESULT = ROOT / "run_log" / "btc_structure_reversal_20261006" / "result.json"
OUT = ROOT / "run_log" / "btc_structure_reversal_attribution_20261006"


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def _periods():
    return {
        "development_2024": (
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2025, 1, 1, tzinfo=timezone.utc),
        ),
        "retrospective_2025": (
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
    }


def _run(frame: pl.DataFrame, funding: pl.DataFrame, signal_col: str):
    trial = frame if signal_col == "entry_signal" else with_trial_signal(frame, signal_col)
    result = {}
    artifacts = {}
    for label, (start, end) in _periods().items():
        metrics, trades, equity = simulate_period(
            trial,
            funding,
            start=start,
            end_exclusive=end,
            execution_bps_per_side=5.0,
            target_r=2.0,
            max_holding_bars=120,
        )
        result[label] = metrics
        artifacts[label] = (trades, equity)
    return result, artifacts


def _promising(child: dict, parent: dict) -> dict[str, object]:
    details = {}
    ok = True
    for period in ("development_2024", "retrospective_2025"):
        cm = child[period]
        pm = parent[period]
        retention = cm["trades"] / pm["trades"] if pm["trades"] else 0.0
        details[f"{period}_trade_retention"] = retention
        mean_r_better = cm["mean_trade_r"] > pm["mean_trade_r"]
        pf_better = cm["profit_factor_net"] > pm["profit_factor_net"]
        details[f"{period}_mean_r_better"] = mean_r_better
        details[f"{period}_pf_better"] = pf_better
        ok = ok and retention >= 0.40 and mean_r_better and pf_better
    dd_ok = child["development_2024"]["max_drawdown"] >= parent["development_2024"]["max_drawdown"]
    oos_positive = child["retrospective_2025"]["net_return"] > 0
    details["development_2024_drawdown_no_worse"] = dd_ok
    details["retrospective_2025_net_positive"] = oos_positive
    ok = ok and dd_ok and oos_positive
    return {"promising": bool(ok), "checks": details}


def main() -> None:
    spec = yaml.safe_load(CFG.read_text())
    parent_spec = yaml.safe_load(PARENT_CFG.read_text())
    start = _parse_utc(parent_spec["data"]["start"])
    end = _parse_utc(parent_spec["data"]["end_exclusive"])

    prices, price_audit = parent_runner._load_prices(Path(parent_spec["data"]["price_path"]), start, end)
    funding, funding_audit = parent_runner._load_funding(Path(parent_spec["data"]["funding_path"]), start, end)
    signal_frame, pivots = build_signal_frame(
        prices,
        atr_period=int(parent_spec["signal"]["atr"]["period"]),
        buffer_atr=float(parent_spec["signal"]["entry"]["buffer_atr"]),
    )
    frame = add_attribution_features(signal_frame, pivots)

    trial_columns = {
        "PARENT": "entry_signal",
        "R1_EMA": "r1_ema_signal",
        "R2_AVWAP": "r2_avwap_signal",
        "R3_REGIME": "r3_regime_signal",
    }
    results = {}
    all_artifacts = {}
    for trial_id, signal_col in trial_columns.items():
        results[trial_id], all_artifacts[trial_id] = _run(frame, funding, signal_col)

    # Guard against silently changing the already-observed parent baseline.
    old = json.loads(PARENT_RESULT.read_text())
    parent_now = results["PARENT"]
    for period, old_key in (
        ("development_2024", "development_2024"),
        ("retrospective_2025", "oos_2025"),
    ):
        for metric in ("trades", "net_return", "mean_trade_r", "profit_factor_net", "max_drawdown"):
            if abs(float(parent_now[period][metric]) - float(old[old_key][metric])) > 1e-12:
                raise RuntimeError(f"parent reproduction mismatch: {period} {metric}")

    promotion = {
        trial_id: _promising(results[trial_id], results["PARENT"])
        for trial_id in ("R1_EMA", "R2_AVWAP", "R3_REGIME")
    }

    OUT.mkdir(parents=True, exist_ok=True)
    for trial_id, period_artifacts in all_artifacts.items():
        slug = trial_id.lower()
        for period, (trades, equity) in period_artifacts.items():
            trades.write_parquet(OUT / f"{slug}_{period}_trades.parquet")
            equity.write_parquet(OUT / f"{slug}_{period}_equity.parquet")

    event_frame = frame.filter(pl.col("entry_signal")).select(
        "timestamp",
        "close",
        "atr14",
        "latest_confirmed_swing_high",
        "latest_confirmed_swing_low",
        "ema20",
        "ema20_slope3",
        "anchored_vwap",
        "adx14",
        "adx14_delta3",
        "r1_ema_signal",
        "r2_avwap_signal",
        "r3_regime_signal",
    )
    event_frame.write_parquet(OUT / "baseline_event_features.parquet")

    result = {
        "schema_version": "btc_structure_reversal_attribution/v1",
        "session_id": spec["session_id"],
        "status": "EXPLORATORY",
        "approval_status": "NOT_APPROVED",
        "parent_session": spec["parent_session"],
        "parent_config_sha256": sha256(PARENT_CFG.read_bytes()).hexdigest(),
        "attribution_config_sha256": sha256(CFG.read_bytes()).hexdigest(),
        "trial_accounting": {
            "parent_trials": int(spec["parent_trial_count"]),
            "new_trials": int(spec["new_trial_count"]),
            "total_trials": int(spec["total_trial_count"]),
            "new_trial_ids": ["R1_EMA", "R2_AVWAP", "R3_REGIME"],
        },
        "holdout_status": "NO_PRISTINE_HOLDOUT_2025_PARENT_RESULT_ALREADY_OBSERVED",
        "data_audit": {"prices": price_audit, "funding": funding_audit},
        "results": results,
        "promotion_checks": promotion,
        "promising_trials": [k for k, v in promotion.items() if v["promising"]],
        "interpretation": {
            "R1_EMA": "positive 3-hour EMA20 slope",
            "R2_AVWAP": "close above anchored VWAP from latest confirmed swing low",
            "R3_REGIME": "ADX14 >= 20 and ADX14 falling versus 3 hours earlier",
        },
        "limitations": [
            "2025 is a retrospective chronological comparison, not a pristine holdout.",
            "Only three preregistered filters were tested; they are independent attribution trials, not a parameter search.",
            "Execution and funding conventions are inherited unchanged from the parent exploratory baseline.",
            "No filter combination or machine-learning model is tested in this stage.",
        ],
    }
    (OUT / "result.json").write_text(json.dumps(_json_safe(result), indent=2, sort_keys=True) + "\n")
    print(json.dumps(_json_safe({
        "results": results,
        "promotion_checks": promotion,
        "promising_trials": result["promising_trials"],
    }), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
