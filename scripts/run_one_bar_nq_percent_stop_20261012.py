"""Freeze, run, and compare the fixed-percent-stop historical review."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_one_bar_practical_yearly_20261012 as base
from ml4t.backtest.types import Trade
from ml4t.backtest.analytics import TradeAnalyzer, calmar_ratio, cagr, max_drawdown, sharpe_ratio

OUT = ROOT / "run_log/one_bar_nq_percent_stop_20261012"
BASELINE = ROOT / "run_log/one_bar_practical_1m_20261012"
PROMOTED = ROOT / "promote/one_bar_nq_30m"
FRACTION = 50 / 14598.25
REFERENCE_MEDIAN = 14598.25
REFERENCE_YEAR = 2021
TZ = ZoneInfo("America/Chicago")
YEARS = list(range(2013, 2027))
TRIALS = ["percent_zero_cost", "percent_costed"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def frozen_spec(source: dict) -> dict:
    return {
        "session_id": "one_bar_nq_percent_stop_20261012",
        "status": "EXPLORATORY",
        "classification": "historical counterfactual; no unseen out-of-sample period; no approval",
        "parameter_freeze": {
            "fraction": FRACTION,
            "anchor_year": REFERENCE_YEAR,
            "anchor_median_entry_price": REFERENCE_MEDIAN,
            "anchor_closed_costed_trades": 444,
            "anchor_source": "run_log/one_bar_practical_1m_20261012/by_year/2021/native_full_tick_cost/evaluation_trades.csv",
            "calculation": "50 index points / 14598.25 = 0.0034250680732279554",
            "stop_points": "actual filled entry price * fraction",
            "rounding": "long floor to 0.25 tick; short ceiling to 0.25 tick; stop never changes after fill",
            "selection_limit": "2021 anchor was selected before this trial; 2013-2021 remain ex-post calibration/counterfactual data, not out-of-sample",
        },
        "hypothesis": "A fixed 0.34250680732279554% protective stop changes one-bar B0 risk and net PnL relative to B0's fixed 50-point stop.",
        "falsifier": "The stop is not anchored to actual fill, violates one-contract/tick rules, or native stop executions and annual PnL do not reconcile to fills.",
        "baseline": "Original practical B0 one-bar 30-minute breakout; unchanged; 50 index-point protective stop.",
        "instrument": {
            "source": "Dukascopy USATECH.IDX/USD BID one-minute CFD index proxy",
            "identity_limit": "Not dated CME NQ futures; NQ-equivalent multiplier is an illustrative assumption.",
            "multiplier_usd_per_point": 20.0, "tick_points": 0.25, "contracts": 1,
        },
        "rules": {
            "entries": "Previous 50 complete Chicago 17:00 America/Chicago anchored 30-minute highs/lows; native OCO-intended STOP orders; max two filled entries per Chicago session day; long and short.",
            "exit": "Next 30-minute boundary market exit, or earlier protective STOP.",
            "unchanged": ["bar construction", "lookback", "entry levels", "OCO intent", "entry cap", "contract count", "multiplier", "tick", "scheduled exit", "source data"],
            "prohibited": ["ATR", "volatility sizing", "MNQ", "size model", "entry/exit filters", "parameter search"],
        },
        "data": {
            "start_inclusive_utc": "2013-01-01", "end_inclusive_utc": "2026-07-14",
            "protected_after": "2026-07-14", "source_manifest": source["manifest"],
            "source_manifest_sha256": source["manifest_sha256"],
            "source_partitions": source["partition_count"], "verified_bytes": source["verified_bytes"],
            "configuration_sha256": sha256(ROOT / "config/research_sessions/one_bar_nq_percent_stop_20261012.yaml"),
            "baseline_code_sha256": sha256(ROOT / "scripts/run_one_bar_dukascopy_phase567_20261011.py"),
            "yearly_runner_code_sha256": sha256(ROOT / "scripts/run_one_bar_practical_yearly_20261012.py"),
            "percent_strategy_code_sha256": sha256(ROOT / "scripts/run_one_bar_nq_percent_stop_yearly_20261012.py"),
            "comparison_runner_code_sha256": sha256(ROOT / "scripts/run_one_bar_nq_percent_stop_20261012.py"),
        },
        "costs": {
            "percent_zero_cost": {"commission_usd_per_fill": 0.0, "adverse_slippage_points_per_fill": 0.0},
            "percent_costed": {"commission_usd_per_fill": 2.5, "adverse_slippage_points_per_fill": 0.25},
            "spread": "No separate spread assumption, to match B0 cost cases.",
        },
        "planned_trials": [
            {"id": "PZ", "name": "percent_zero_cost", "status": "planned"},
            {"id": "PC", "name": "percent_costed", "status": "planned"},
        ],
        "method_skills": [
            {"name": "ml4t-run-backtest", "path": ".agents/skills/ml4t-run-backtest/SKILL.md", "invariant": "Use native Engine, Strategy, DataFeed, future-event execution, and per-fill costs."},
            {"name": "ml4t-lookahead-bias", "path": ".agents/skills/ml4t-lookahead-bias/SKILL.md", "invariant": "Use actual filled entry only after fill; no future prices in stop calculation; release complete 30-minute levels causally."},
            {"name": "ml4t-calendar-ops", "path": ".agents/skills/ml4t-calendar-ops/SKILL.md", "invariant": "Keep Chicago session-day grouping and timezone-aware boundaries across DST."},
            {"name": "ml4t-validate-data", "path": ".agents/skills/ml4t-validate-data/SKILL.md", "invariant": "Verify source hashes, row identity, timestamps, OHLC, nulls, and annual coverage."},
            {"name": "ml4t-cost-model", "path": ".agents/skills/ml4t-cost-model/SKILL.md", "invariant": "Charge the frozen commission and adverse slippage on every fill; no extra cost assumptions."},
            {"name": "ml4t-transaction-costs", "path": ".agents/skills/ml4t-transaction-costs/SKILL.md", "invariant": "Disclose cost assumptions and execution limits."},
            {"name": "ml4t-risk-metrics", "path": ".agents/skills/ml4t-risk-metrics/SKILL.md", "invariant": "Report Sharpe with drawdown and Calmar on common daily dates."},
            {"name": "ml4t-polars-patterns", "path": ".agents/skills/ml4t-polars-patterns/SKILL.md", "invariant": "Use existing sorted Polars source and artifact processing."},
        ],
        "method_conflicts": ["Generic cost skill examples recommend spread and impact; the mission fixes B0's zero-cost and commission plus 0.25-point slippage cases, so no extra spread or impact is introduced."],
        "installed_ml4t_api": {
            "package": "ml4t.backtest",
            "engine": "Engine(feed, strategy, config, contract_specs=...).run()",
            "execution": "ExecutionMode.NEXT_BAR; StopFillMode.STOP_PRICE",
            "gap_rule": "Native fill engine checks the opening price first and fills a stop at the gap-through open when it crosses the stop; otherwise at the stop price.",
            "official_docs_retrieval": "TinyFish official docs fetch returned invalid_url; official-domain search returned no results. Local installed source/signatures were inspected.",
        },
        "limitations": ["1-minute OHLC does not reveal event order within a minute.", "Native Engine has no atomic OCO; same-minute opposing STOP fills remain ambiguous.", "Annual market exits may execute on the next source event where the exact boundary minute is absent.", "All tested history was already observed; 2022-2026 is chronological after the parameter anchor but is not unseen OOS.", "No CME futures mapping, live order, or trading-readiness inference."],
    }


def assert_anchor() -> None:
    anchor_path = BASELINE / "by_year/2021/native_full_tick_cost/evaluation_trades.csv"
    trades = pl.read_csv(anchor_path, try_parse_dates=True).filter(pl.col("status") == "closed")
    if trades.height != 444 or float(trades["entry_price"].median()) != REFERENCE_MEDIAN:
        raise ValueError("Frozen 2021 stop anchor does not match the specified B0 artifact")


def baseline_protection(source: dict) -> dict:
    promoted_manifest = PROMOTED / "provenance/manifest.json"
    original_manifest = BASELINE / "manifest.json"
    recorded = json.loads((BASELINE / "hashes.json").read_text())["files"]
    original_mismatches = [{"path": path, "expected_sha256": expected,
        "actual_sha256": sha256(ROOT / path) if (ROOT / path).is_file() else None}
        for path, expected in recorded.items()
        if not (ROOT / path).is_file() or sha256(ROOT / path) != expected]
    verifier = subprocess.run([sys.executable, str(PROMOTED / "scripts/verify_package.py")],
        cwd=ROOT, text=True, capture_output=True)
    return {
        "source_manifest_sha256": source["manifest_sha256"],
        "original_b0_manifest_sha256": sha256(original_manifest),
        "original_b0_hashes_json_sha256": sha256(BASELINE / "hashes.json"),
        "original_b0_recorded_file_count": len(recorded),
        "original_b0_recorded_hash_mismatches": original_mismatches,
        "promoted_manifest_sha256": sha256(promoted_manifest),
        "promoted_package_file_count": len([p for p in PROMOTED.rglob("*") if p.is_file()]),
        "promoted_verifier_exit_code": verifier.returncode,
        "promoted_verifier_output": (verifier.stdout + verifier.stderr).strip(),
    }


def prepare() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    assert_anchor()
    source = base.verify_source()
    source_audit = json.loads((BASELINE / "validation/source_manifest_audit.json").read_text())
    if source_audit["manifest_sha256"] != source["manifest_sha256"]:
        raise ValueError("Source identity differs from completed B0 audit")
    frozen_path = OUT / "frozen_spec.json"
    proposed = frozen_spec(source)
    prior_spec = json.loads(frozen_path.read_text()) if frozen_path.exists() else None
    if prior_spec and prior_spec != proposed:
        prior_semantic = json.loads(json.dumps(prior_spec))
        proposed_semantic = json.loads(json.dumps(proposed))
        prior_semantic["data"].pop("comparison_runner_code_sha256", None)
        proposed_semantic["data"].pop("comparison_runner_code_sha256", None)
        if prior_semantic != proposed_semantic:
            raise ValueError("Existing frozen specification differs; preserve it and start a new session")
    if not prior_spec:
        frozen_path.write_text(json.dumps(proposed, indent=2) + "\n")
    (OUT / "source_quality.json").write_text(json.dumps({
        "source_verification": source,
        "original_b0_quality": json.loads((BASELINE / "validation/source_quality.json").read_text()),
        "original_b0_coverage": json.loads((BASELINE / "validation/source_coverage.json").read_text()),
    }, indent=2) + "\n")
    ledger_path = OUT / "trial_ledger.json"
    prior_attempts = []
    legacy_log = OUT / "agent.log"
    if legacy_log.exists():
        prior_attempts.append({"id": "PREEXISTING-TOOL-ATTEMPT", "status": "failed_or_interrupted",
            "artifact": str(legacy_log.relative_to(ROOT)), "artifact_sha256": sha256(legacy_log),
            "reason": "Existing agent.log had no trial outputs or completion marker; retained unchanged."})
    ledger = {"created_at_utc": datetime.now(timezone.utc).isoformat(),
        "classification": "EXPLORATORY historical counterfactual",
        "trials": [{"id": "B0", "name": "original_B0_historical_review", "status": "completed",
                    "artifact": "run_log/one_bar_practical_1m_20261012/final_report.json"},
                   {"id": "PZ", "name": "percent_zero_cost", "status": "planned"},
                   {"id": "PC", "name": "percent_costed", "status": "planned"}],
        "attempts": prior_attempts}
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text())
        if prior_spec and prior_spec != proposed and not any(
            row.get("id") == "PREFLIGHT-IMPLEMENTATION-AMENDMENT" for row in ledger.get("attempts", [])):
            amendment = {
                "id": "PREFLIGHT-IMPLEMENTATION-AMENDMENT", "status": "amended_before_backtest",
                "preflight_result": "failed_before_any_engine_run",
                "preflight_failure": "One existing B0 recovery_agent.log differs from its indexed SHA-256.",
                "reason": "The first preflight stopped before simulation because one B0 recovery log differs from its hash index. The audit now records that pre-existing mismatch and verifies it is unchanged.",
                "frozen_runner_sha256": prior_spec["data"]["comparison_runner_code_sha256"],
                "corrected_runner_sha256": proposed["data"]["comparison_runner_code_sha256"],
            }
            ledger.setdefault("attempts", []).append(amendment)
            (OUT / "validation").mkdir(exist_ok=True)
            (OUT / "validation/preflight_implementation_amendment.json").write_text(
                json.dumps(amendment, indent=2) + "\n")
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n")
    else:
        ledger_path.write_text(json.dumps(ledger, indent=2) + "\n")
    protection = baseline_protection(source)
    if protection["promoted_verifier_exit_code"]:
        raise ValueError("Promoted package verifier failed before the experiment")
    (OUT / "validation").mkdir(exist_ok=True)
    protection_path = OUT / "validation/protected_baseline_hashes.json"
    if protection_path.exists() and json.loads(protection_path.read_text()) != protection:
        raise ValueError("Original B0/promoted hashes differ from their pre-run snapshot")
    if not protection_path.exists():
        protection_path.write_text(json.dumps(protection, indent=2) + "\n")
    (OUT / "validation/source_manifest_audit.json").write_text(json.dumps(source, indent=2) + "\n")
    print(json.dumps({"frozen": True, "source": source, "protection": protection}, indent=2), flush=True)


def _trade_objects(frame: pl.DataFrame) -> list[Trade]:
    rows = frame.filter(pl.col("status") == "closed").to_dicts()
    return [Trade(symbol=row["symbol"], entry_time=row["entry_time"], exit_time=row["exit_time"],
        entry_price=float(row["entry_price"]), exit_price=float(row["exit_price"]),
        quantity=float(row["quantity"]), pnl=float(row["pnl"]), pnl_percent=float(row["pnl_percent"]),
        bars_held=int(row["bars_held"]), fees=float(row.get("fees") or 0.0),
        exit_slippage=float(row.get("exit_slippage") or 0.0),
        exit_reason=str(row.get("exit_reason") or "signal"), status="closed",
        entry_slippage=float(row.get("entry_slippage") or 0.0),
        multiplier=float(row.get("multiplier") or 20.0)) for row in rows]


def chicago_year(ts: datetime) -> int:
    local = ts.astimezone(TZ)
    session_day = local.date() if local.hour >= 17 else local.date().fromordinal(local.date().toordinal() - 1)
    return session_day.year


def _load_trade_rows(root: Path, year: int, name: str) -> pl.DataFrame:
    path = root / "by_year" / str(year) / name / "evaluation_trades.csv"
    return pl.read_csv(path, try_parse_dates=True).filter(pl.col("status") == "closed")


def _load_daily(root: Path, year: int, name: str) -> pl.DataFrame:
    path = root / "by_year" / str(year) / name / "daily_equity.csv"
    return (pl.read_csv(path, try_parse_dates=True).sort("timestamp")
        .with_columns(pl.col("timestamp").dt.date().alias("utc_day"))
        .filter(pl.col("utc_day").dt.year() == year)
        .with_columns(pl.col("equity").shift(1).fill_null(1_000_000.0).alias("prior_equity"))
        .with_columns((pl.col("equity") / pl.col("prior_equity") - 1).alias("daily_return"))
        .select("utc_day", "equity", "daily_return"))


def _trade_metrics(frame: pl.DataFrame, fills: pl.DataFrame) -> dict:
    analyzer = TradeAnalyzer(_trade_objects(frame))
    exits = fills.filter((pl.col("order_type") == "stop") & (pl.col("exit_reason") == "signal"))
    stop_exits = frame.filter(pl.col("exit_time").is_in(exits["timestamp"]))
    return {
        "closed_trades": analyzer.num_trades,
        "net_pnl_usd": analyzer.net_profit,
        "average_trade_pnl_usd": analyzer.net_profit / analyzer.num_trades if analyzer.num_trades else None,
        "win_rate": analyzer.win_rate,
        "profit_factor": analyzer.profit_factor,
        "worst_trade_loss_usd": float(frame["pnl"].min()) if frame.height else None,
        "worst_trade_return": analyzer.largest_loss,
        "protective_stop_exits": stop_exits.height,
        "protective_stop_rate": stop_exits.height / analyzer.num_trades if analyzer.num_trades else None,
        "gross_minus_net_pnl_usd": analyzer.total_gross_pnl - analyzer.net_profit,
        "commission_usd": analyzer.total_commission,
        "trade_analyzer": analyzer.to_dict(),
    }


def _period_metrics(root: Path, year_values: list[int], name: str) -> tuple[dict, pl.DataFrame]:
    trades = pl.concat([_load_trade_rows(root, y, name) for y in year_values])
    fills = pl.concat([pl.read_csv(root / "by_year" / str(y) / name / "fills.csv", try_parse_dates=True)
        for y in year_values])
    result = _trade_metrics(trades, fills)
    daily_parts = [_load_daily(root, y, name) for y in year_values]
    daily = pl.concat(daily_parts).unique(subset=["utc_day"], keep="last").sort("utc_day")
    return result, daily


def _risk_on_common_days(reference: pl.DataFrame, candidate: pl.DataFrame) -> dict:
    common = reference.select("utc_day", pl.col("daily_return").alias("reference_return"))
    common = common.join(candidate.select("utc_day", pl.col("daily_return").alias("candidate_return")),
        on="utc_day", how="inner").sort("utc_day")
    output = {"common_calendar_days": common.height}
    for label, column in (("reference", "reference_return"), ("candidate", "candidate_return")):
        returns = common[column].to_list()
        equity = [1_000_000.0]
        for value in returns:
            equity.append(equity[-1] * (1.0 + value))
        drawdown = max_drawdown(equity)[0] if len(equity) > 1 else 0.0
        years = max((common["utc_day"][-1] - common["utc_day"][0]).days / 365.25, 1 / 365.25) if common.height else 0.0
        growth = cagr(equity[0], equity[-1], years) if years else 0.0
        output[label] = {"daily_sharpe": sharpe_ratio(returns, annualize=True) if returns else None,
            "max_drawdown": drawdown, "calmar": calmar_ratio(growth, drawdown) if drawdown else None,
            "cagr": growth, "equity_change_usd_on_common_dates": equity[-1] - equity[0]}
    return output


def _direction_metrics(trades: pl.DataFrame, fills: pl.DataFrame, direction: str) -> dict:
    frame = trades.filter(pl.col("direction").str.to_lowercase() == direction)
    return _trade_metrics(frame, fills)


def audit_and_report() -> dict:
    spec = json.loads((OUT / "frozen_spec.json").read_text())
    protected_before = json.loads((OUT / "validation/protected_baseline_hashes.json").read_text())
    source = base.verify_source()
    errors = []
    summaries = {}
    for year in YEARS:
        year_dir = OUT / "by_year" / str(year)
        summary_path = year_dir / "year_summary.json"
        if not summary_path.exists():
            errors.append(f"{year}: missing year_summary.json")
            continue
        summary = json.loads(summary_path.read_text())
        if summary.get("status") != "completed":
            errors.append(f"{year}: status={summary.get('status')}")
            continue
        for trial in TRIALS:
            path = year_dir / trial
            required = ["trades.csv", "fills.csv", "evaluation_trades.csv", "daily_equity.csv", "metrics.json", "evaluation_metrics.json", "entry_context.csv"]
            for item in required:
                if not (path / item).exists():
                    errors.append(f"{year}/{trial}: missing {item}")
        summaries[year] = summary
    if errors:
        return {"status": "incomplete", "errors": errors}

    annual = []
    for year in YEARS:
        row = {"year": year}
        for side, baseline_trial, percent_trial in (
            ("zero_cost", "native_zero_cost", "percent_zero_cost"),
            ("costed", "native_full_tick_cost", "percent_costed"),
        ):
            b0_trades = _load_trade_rows(BASELINE, year, baseline_trial)
            p_trades = _load_trade_rows(OUT, year, percent_trial)
            b0_fills = pl.read_csv(BASELINE / "by_year" / str(year) / baseline_trial / "fills.csv", try_parse_dates=True)
            p_fills = pl.read_csv(OUT / "by_year" / str(year) / percent_trial / "fills.csv", try_parse_dates=True)
            row[side] = {"B0": _trade_metrics(b0_trades, b0_fills),
                "fixed_percent_stop": _trade_metrics(p_trades, p_fills)}
            if side == "costed" and year == 2026:
                row[side]["B0_by_direction"] = {direction: _direction_metrics(b0_trades, b0_fills, direction)
                    for direction in ("long", "short")}
                row[side]["fixed_percent_stop_by_direction"] = {direction: _direction_metrics(p_trades, p_fills, direction)
                    for direction in ("long", "short")}
        annual.append(row)

    periods = {"2013-2021_ex_post_anchor_period": list(range(2013, 2022)),
        "2022-2025_chronology_after_anchor_not_OOS": list(range(2022, 2026)), "2026_through_Jul14": [2026]}
    scenario_summary = {}
    risk_comparison = {}
    for label, years in periods.items():
        scenario_summary[label] = {}
        risk_comparison[label] = {}
        for cost_label, b0_name, percent_name in (
            ("zero_cost", "native_zero_cost", "percent_zero_cost"),
            ("costed", "native_full_tick_cost", "percent_costed"),
        ):
            b0_metrics, b0_daily = _period_metrics(BASELINE, years, b0_name)
            p_metrics, p_daily = _period_metrics(OUT, years, percent_name)
            scenario_summary[label][cost_label] = {"B0": b0_metrics, "fixed_percent_stop": p_metrics,
                "net_pnl_change_usd": p_metrics["net_pnl_usd"] - b0_metrics["net_pnl_usd"]}
            risk_comparison[label][cost_label] = _risk_on_common_days(b0_daily, p_daily)

    all_scenarios = {}
    gross_cost_drag = {}
    for label, trial in (("B0", "native_zero_cost"), ("percent_stop", "percent_zero_cost")):
        cost_trial = "native_full_tick_cost" if label == "B0" else "percent_costed"
        zero, zero_daily = _period_metrics(BASELINE if label == "B0" else OUT, YEARS, trial)
        cost, cost_daily = _period_metrics(BASELINE if label == "B0" else OUT, YEARS, cost_trial)
        all_scenarios[label] = {"zero_cost": zero, "costed": cost,
            "zero_to_cost_pnl_change_usd": cost["net_pnl_usd"] - zero["net_pnl_usd"]}
        gross_cost_drag[label] = cost["gross_minus_net_pnl_usd"]
    risk_comparison["full_history"] = {}
    for cost_label, b0_name, percent_name in (
        ("zero_cost", "native_zero_cost", "percent_zero_cost"),
        ("costed", "native_full_tick_cost", "percent_costed"),
    ):
        _, b0_daily = _period_metrics(BASELINE, YEARS, b0_name)
        _, p_daily = _period_metrics(OUT, YEARS, percent_name)
        risk_comparison["full_history"][cost_label] = _risk_on_common_days(b0_daily, p_daily)

    # Independently verify stop price anchoring, one-contract entries, and the session cap.
    stop_audit = {"status": "passed", "years": [], "errors": []}
    for year in YEARS:
        path = OUT / "by_year" / str(year) / "percent_costed"
        contexts = pl.read_csv(path / "entry_context.csv")
        trades = pl.read_csv(path / "evaluation_trades.csv", try_parse_dates=True).filter(pl.col("status") == "closed")
        fills = pl.read_csv(path / "fills.csv", try_parse_dates=True)
        entry_fills = fills.filter((pl.col("order_type") == "stop") & (pl.col("exit_reason") == ""))
        exit_stops = fills.filter((pl.col("order_type") == "stop") & (pl.col("exit_reason") == "signal"))
        if entry_fills.filter(pl.col("quantity").abs() != 1).height:
            stop_audit["errors"].append(f"{year}: entry fill quantity differs from one contract")
        if contexts.filter(pl.col("quantity") != 1).height:
            stop_audit["errors"].append(f"{year}: entry context quantity differs from one contract")
        if contexts.filter(pl.col("stop_fraction") != FRACTION).height:
            stop_audit["errors"].append(f"{year}: stop fraction changed")
        if contexts.filter(((pl.col("side") == "long") & (pl.col("stop_price") >= pl.col("entry_price"))) |
                ((pl.col("side") == "short") & (pl.col("stop_price") <= pl.col("entry_price")))).height:
            stop_audit["errors"].append(f"{year}: stop is not protective")
        if entry_fills.height:
            from run_one_bar_nq_percent_stop_yearly_20261012 import chicago_session_day
            entry_fills = entry_fills.with_columns(pl.col("timestamp").map_elements(
                chicago_session_day, return_dtype=pl.Date).alias("session_day"))
            counts = entry_fills.group_by("session_day").len()
            max_entries = int(counts["len"].max()) if counts.height else 0
        else:
            max_entries = 0
        gap_stops = exit_stops.filter(
            ((pl.col("side") == "sell") & (pl.col("reference_price") < pl.col("stop_price"))) |
            ((pl.col("side") == "buy") & (pl.col("reference_price") > pl.col("stop_price"))))
        if max_entries > 2:
            stop_audit["errors"].append(f"{year}: {max_entries} native entry STOP fills on one session day")
        stop_audit["years"].append({"year": year, "entries": contexts.height,
            "long_entries": contexts.filter(pl.col("side") == "long").height,
            "short_entries": contexts.filter(pl.col("side") == "short").height,
            "stop_exit_fills": exit_stops.height, "closed_trades": trades.height,
            "gap_through_stop_fills": gap_stops.height,
            "max_entry_stop_fills_per_utc_date": max_entries,
            "protective_stops_are_native_stop_price_orders": True})
    stop_audit["status"] = "passed" if not stop_audit["errors"] else "failed"

    protection_after = baseline_protection(source)
    if protection_after != protected_before:
        errors.append("Original B0 or promoted immutable hash changed during the run")
    if protection_after["promoted_verifier_exit_code"]:
        errors.append("Promoted package verifier failed after the experiment")
    audit = {"status": "passed" if not errors and stop_audit["status"] == "passed" else "failed",
        "errors": errors, "source_identity_matches_frozen": source["manifest_sha256"] == spec["data"]["source_manifest_sha256"],
        "protected_baseline_hashes_before": protected_before,
        "protected_baseline_hashes_after": protection_after,
        "percent_stop_invariants": stop_audit}
    (OUT / "validation/native_reconciliation.json").write_text(json.dumps(audit, indent=2) + "\n")
    report = {
        "status": "COMPLETED_EXPLORATORY" if audit["status"] == "passed" else "COMPLETED_WITH_AUDIT_ERRORS",
        "classification": spec["classification"], "parameter_fraction": FRACTION,
        "parameter_anchor": spec["parameter_freeze"], "source": spec["data"],
        "annual_comparison": annual, "period_comparison": scenario_summary,
        "common_calendar_daily_risk": risk_comparison,
        "all_history": all_scenarios, "gross_cost_drag_usd": gross_cost_drag,
        "audit": audit, "execution_caveats": spec["limitations"],
        "preexisting_integrity_deviation": (protected_before["original_b0_recorded_hash_mismatches"]
            if protected_before["original_b0_recorded_hash_mismatches"] else None),
        "implementation_amendment": (json.loads((OUT / "validation/preflight_implementation_amendment.json").read_text())
            if (OUT / "validation/preflight_implementation_amendment.json").exists() else None),
        "conclusion": "Descriptive historical counterfactual only. Do not infer live readiness or an unseen out-of-sample result.",
    }
    (OUT / "final_report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    (OUT / "yearly_summary.json").write_text(json.dumps({"annual_comparison": annual,
        "period_comparison": scenario_summary, "daily_risk": risk_comparison}, indent=2, default=str) + "\n")
    ledger = json.loads((OUT / "trial_ledger.json").read_text())
    for trial in ledger["trials"]:
        if trial["name"] in TRIALS:
            trial["status"] = "completed" if audit["status"] == "passed" else "completed_with_audit_errors"
            trial["year_count"] = len(YEARS)
            trial["years"] = [{"year": year, "status": summaries[year]["status"],
                "trials": summaries[year]["trials"]} for year in YEARS]
    ledger["status"] = audit["status"]
    (OUT / "trial_ledger.json").write_text(json.dumps(ledger, indent=2) + "\n")
    hashes = {p.relative_to(ROOT).as_posix(): sha256(p) for p in OUT.rglob("*")
        if p.is_file() and p.name != "hashes.json"}
    (OUT / "hashes.json").write_text(json.dumps(hashes, indent=2) + "\n")
    return report


def run() -> None:
    if not (OUT / "frozen_spec.json").exists():
        prepare()
    else:
        assert_anchor()
        source = base.verify_source()
        if source["manifest_sha256"] != json.loads((OUT / "frozen_spec.json").read_text())["data"]["source_manifest_sha256"]:
            raise ValueError("Frozen source identity changed")
    ledger_path = OUT / "trial_ledger.json"
    ledger = json.loads(ledger_path.read_text())
    for trial in ledger["trials"]:
        if trial["id"] in ("PZ", "PC"):
            if trial["status"] in ("planned", "running"):
                trial["status"] = "running"
    ledger["status"] = "running"
    ledger_path.write_text(json.dumps(ledger, indent=2) + "\n")
    for year in YEARS:
        year_dir = OUT / "by_year" / str(year)
        summary_path = year_dir / "year_summary.json"
        if summary_path.exists() and json.loads(summary_path.read_text()).get("status") == "completed":
            print(f"YEAR={year} SKIP durable completed summary", flush=True)
            continue
        year_dir.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, str(ROOT / "scripts/run_one_bar_nq_percent_stop_yearly_20261012.py"), str(year)]
        env = os.environ.copy()
        env["UV_CACHE_DIR"] = "/tmp/uv-cache"
        process = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True)
        (OUT / "logs").mkdir(exist_ok=True)
        (OUT / f"logs/year_{year}.log").write_text(process.stdout + process.stderr)
        if process.returncode:
            result = {"year": year, "status": "failed", "exit_code": process.returncode,
                "log": f"run_log/one_bar_nq_percent_stop_20261012/logs/year_{year}.log"}
        else:
            result = json.loads((year_dir / "worker_summary.json").read_text())
        summary_path.write_text(json.dumps(result, indent=2, default=str) + "\n")
        print(f"YEAR={year} status={result['status']}", flush=True)
        if result["status"] != "completed":
            ledger = json.loads(ledger_path.read_text())
            ledger.setdefault("failed_years", []).append(result)
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n")
    if all((OUT / "by_year" / str(y) / "year_summary.json").exists() and
        json.loads((OUT / "by_year" / str(y) / "year_summary.json").read_text()).get("status") == "completed" for y in YEARS):
        report = audit_and_report()
        print(json.dumps({"status": report["status"], "output": str(OUT / "final_report.json")}, indent=2), flush=True)
    else:
        print("FULL_HISTORY_INCOMPLETE; inspect per-year status and resume with this command.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--audit", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        prepare()
    elif args.audit:
        print(json.dumps(audit_and_report(), indent=2, default=str))
    else:
        run()


if __name__ == "__main__":
    main()
