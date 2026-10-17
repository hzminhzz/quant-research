"""Build the compact evidence ledger from completed native-engine outputs."""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import polars as pl
import statsmodels.api as sm

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "run_log/prop_mvp_20261011"


def finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite(v) for v in value]
    return value


def read_json(path):
    return json.loads(path.read_text())


def summaries():
    studies = {}
    for track in ("a_momentum", "b_price_only_proxy", "c_opening_range_proxy"):
        for metrics_path in sorted((OUT / track).glob("*/*_metrics.json")):
            row = read_json(metrics_path)
            key = f"{row['instrument']}:{row['trial']}"
            studies.setdefault(track, {})[key] = {
                "instrument": row["instrument"], "trial": row["trial"],
                "sample_start": row["sample_start"], "sample_end": row["sample_end"],
                "trades": row["trades"], "win_rate": row["win_rate"],
                "mean_trade_return": row["mean_trade_return"], "profit_factor": row["profit_factor"],
                "total_return": row["total_return"], "daily_sharpe": row["sharpe"],
                "daily_observations": row["daily_observations"], "max_drawdown": row["max_drawdown"],
                "gross_pnl": row["native_metrics"].get("total_gross_pnl"),
                "commission": row["commission"], "slippage": row["slippage"],
                "total_costs": row["total_costs"],
                "cost_assumptions_bps_each_fill": [row.get("commission_bps_each_fill"), row.get("slippage_bps_each_fill")],
                "limitations": [row[k] for k in ("funding_cost", "classification", "resolution_deviation") if row.get(k)],
                "artifact_dir": str(metrics_path.parent.relative_to(ROOT)),
            }
    return studies


def robustness(studies):
    result = {}
    for track in ("a_momentum", "b_price_only_proxy", "c_opening_range_proxy"):
        result[track] = {}
        for instrument in sorted({k.split(":")[0] for k in studies[track]}):
            base_path = OUT / track / instrument / "baseline_trades.parquet"
            trades = pl.read_parquet(base_path)
            lo, hi = trades.select(pl.col("net_return").quantile(.01).alias("lo"),
                                   pl.col("net_return").quantile(.99).alias("hi")).row(0)
            trimmed = trades.filter(pl.col("net_return").is_between(lo, hi, closed="both"))
            daily = pl.read_parquet(OUT / track / instrument / "baseline_daily_returns.parquet")["daily_return"].to_numpy()
            fit = sm.OLS(daily, np.ones((len(daily), 1))).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
            mean, se = float(fit.params[0]), float(fit.bse[0])
            state = pl.read_parquet(OUT / track / instrument / "baseline_portfolio_state.parquet")
            calendar = "1d" if track.startswith(("a_", "b_")) else "1d"
            daily_state = (state.with_columns(pl.col("timestamp").dt.date().alias("date"))
                           .group_by("date").agg(pl.col("equity").last()).sort("date")
                           .with_columns(pl.col("equity").shift(1).alias("prior_equity"))
                           .with_columns((pl.col("equity") / pl.col("prior_equity") - 1).alias("daily_return")))
            years = {}
            for year in daily_state.with_columns(pl.col("date").dt.year().alias("year"))["year"].unique().sort().to_list():
                subset = daily_state.filter(pl.col("date").dt.year() == year)
                tr = trades.filter(pl.col("entry_time").dt.year() == year).height
                vals = subset["daily_return"].drop_nulls().to_numpy()
                years[str(year)] = {"trades_entered": tr,
                    "calendar_year_equity_return": float(np.prod(1 + vals) - 1) if len(vals) else None,
                    "daily_observations": int(len(vals))}
            result[track][instrument] = {
                "trade_return_trim_1_99pct": {"p01": float(lo), "p99": float(hi), "n_raw": trades.height,
                    "n_retained": trimmed.height, "n_removed": trades.height-trimmed.height,
                    "removed_fraction": (trades.height-trimmed.height)/trades.height,
                    "trimmed_mean_net_return": trimmed["net_return"].mean()},
                "daily_mean_hac_lag5": {"mean": mean, "standard_error": se,
                    "ci95": [mean-1.96*se, mean+1.96*se], "n": int(len(daily)),
                    "note": "descriptive HAC interval; daily returns are serially dependent and period is retrospective"},
                "calendar_year_continuous_account": years,
            }
    return result


def build_b_event_study():
    frames = []
    event_summary = {}
    for symbol in ("BTCUSDT", "ETHUSDT"):
        source = "btc_1m.parquet" if symbol == "BTCUSDT" else "eth_1m.parquet"
        frame = pl.scan_parquet(ROOT / "data/processed" / source).filter(
            pl.col("timestamp") < pl.datetime(2025, 6, 1, time_zone="UTC")
        ).collect().sort("timestamp")
        frame = frame.with_columns(
            prev_close=pl.col("close").shift(1),
            prev_tr=pl.max_horizontal(pl.col("high") - pl.col("low"),
                (pl.col("high") - pl.col("close").shift(1)).abs(),
                (pl.col("low") - pl.col("close").shift(1)).abs()),
        ).with_columns(atr=pl.col("prev_tr").rolling_mean(14).shift(1))
        frame = frame.with_columns(
            signal=pl.when((pl.col("close") - pl.col("prev_close")) <= -3 * pl.col("atr")).then(1).otherwise(0),
            forward_12=pl.col("close").shift(-12) / pl.col("close") - 1,
            ret_1=pl.col("close") / pl.col("prev_close") - 1,
        ).drop_nulls(["signal", "atr", "forward_12", "ret_1"]).with_columns(pl.lit(symbol).alias("symbol"))
        frames.append(frame.select("timestamp", "signal", "atr", "ret_1", "forward_12", "symbol"))
        sig = frame.filter(pl.col("signal") == 1)
        threshold = frame["ret_1"].abs().quantile(.90)
        controls = frame.filter((pl.col("signal") == 0) & (pl.col("ret_1").abs() >= threshold))
        event_summary[symbol] = {
            "proxy_events": sig.height, "proxy_mean_forward_12m_return": sig["forward_12"].mean(),
            "proxy_median_forward_12m_return": sig["forward_12"].median(),
            "high_vol_control_n": controls.height, "high_vol_control_mean_forward_12m_return": controls["forward_12"].mean(),
            "forward_12m_histogram": sig.select(pl.col("forward_12").cut([-0.01, -0.005, 0, 0.005, 0.01]).alias("bin"))
                .group_by("bin").len().to_dicts(),
            "control_threshold": float(threshold),
            "note": "top-decile absolute one-minute return control is descriptive, full-sample and not a liquidation match",
        }
    events = pl.concat(frames).sort(["symbol", "timestamp"])
    events.write_parquet(OUT / "b_price_only_proxy/event_study.parquet")
    (OUT / "b_event_study_summary.json").write_text(json.dumps(event_summary, indent=2, default=str))
    return event_summary


def main():
    studies = summaries()
    robustness_results = robustness(studies)
    b_events = build_b_event_study()
    source = {
        "formal_track_status": "BLOCKED",
        "reason": "No local timestamped liquidation/force-order records were found or loaded. A documented commercial archive is a candidate only; no credentials or records were available to verify coverage or event data.",
        "candidate": {"name": "CryptoHFTData Binance liquidation dataset", "url": "https://www.cryptohftdata.com/datasets/binance-liquidation-data", "documented_claims": ["Binance Futures public !forceOrder@arr feed normalized to Parquet", "first history date claimed as 2025-06-28", "at most one latest event per symbol per second; sampled/lower-bound event stream"], "verification": "Documentation only; no records loaded; not accepted as evidence."},
        "local_inventory": {"liquidation_or_force_order_records": 0, "funding_records": "present; used only for availability audit, not applied to Engine PnL"},
        "proxy_status": "Separate OHLCV-only extreme-dislocation reversal diagnostic; not liquidation evidence and does not validate the liquidation mechanism.",
    }
    (OUT / "liquidation_source_audit.json").write_text(json.dumps(source, indent=2))
    (OUT / "robustness_metrics.json").write_text(json.dumps(robustness_results, indent=2, default=str))
    (OUT / "a_results.json").write_text(json.dumps(list(studies["a_momentum"].values()), indent=2))
    (OUT / "b_results.json").write_text(json.dumps({"results": list(studies["b_price_only_proxy"].values()), "event_study": "event_study.parquet"}, indent=2))
    for symbol in ("NAS100", "SPX500"):
        records = [v for v in studies["c_opening_range_proxy"].values() if v["instrument"] == symbol]
        (OUT / f"c_{symbol}_results.json").write_text(json.dumps(records, indent=2))
    summary = {
        "mission": "prop_mvp_20261011", "status": "EXPLORATORY", "approval_status": "NOT_APPROVED",
        "head_at_freeze": "c095faab89835c49f4cd6fd66d1a9ed922709039",
        "cutoff_utc_exclusive": "2026-08-01T00:00:00Z",
        "protected_window": "2026-08-01 onward; excluded by timestamp predicate before collection",
        "decisions": {"A": "REJECT current 24h sign rule for further validation", "B": "BLOCKED liquidation mechanism; reject OHLCV proxy as a liquidation claim", "C": "REJECT OR proxy under assumed costs; broker/venue parity BLOCKED"},
        "seven_phase_status": {
            "A": ["complete: specification and prior-exposure boundary frozen", "complete: local prices/funding inventoried", "complete: causal event study", "complete: native Engine gross/cost/stress/control runs", "complete: retrospective chronological regimes and HAC diagnostics", "complete: costs, delay, placebo and outlier diagnostics", "complete: tests, reconciliation and rejection"],
            "B": ["complete: mechanism and proxy separated", "complete: price data qualified; liquidation records absent", "complete: descriptive event study and high-volatility control", "complete: native Engine proxy runs", "complete: retrospective only; no untouched OOS", "complete: cost, delay and outlier diagnostics", "complete: source audit; mechanism BLOCKED"],
            "C": ["complete: specification and venue boundary frozen", "complete: XNYS calendar and data cadence audited", "complete: opening-range signal counts and placebo", "complete: native Engine runs", "complete: retrospective calendar-year and HAC diagnostics", "complete: cost, delay, placebo and outlier diagnostics", "complete: tests, cash/equity reconciliation, no overnight baseline/placebo trades"],
        },
        "spec_schema_note": "The frozen YAML files are evidence-specs, not validated research_session.py v1 session objects.",
        "studies": studies, "robustness": "robustness_metrics.json",
        "event_study": "b_price_only_proxy/event_study.parquet",
        "event_study_summary": "b_event_study_summary.json",
        "source_audit": "liquidation_source_audit.json",
        "artifact_hashes": "artifact_hashes.json",
        "frozen_manifest": "frozen_manifest.json", "data_hashes": "data_hashes.json",
        "trial_amendments": "trial_amendments.json", "implementation_corrections": "implementation_corrections.json",
        "tests": {"command": "uv run python -m pytest tests/test_prop_mvp_20261011.py -q", "result": "3 passed"},
        "limitations": ["A net results exclude funding despite local funding records because native Engine has no funding cash-flow API.", "C index aliases are not mapped to Vest/Propr instruments or broker fees; SPX500 data is 15m fallback.", "DSR/PBO are unreproducible because legacy trial history is incomplete.", "All studied windows are retrospective; no untouched OOS claim."],
    }
    (OUT / "summary.json").write_text(json.dumps(finite(summary), indent=2, default=str, allow_nan=False))
    hashed = {}
    targets = [ROOT / "scripts/run_prop_mvp_20261011.py", ROOT / "scripts/finalize_prop_mvp_20261011.py",
               ROOT / "tests/test_prop_mvp_20261011.py", ROOT / "docs/audit/prop_mvp_20261011.md",
               *sorted((ROOT / "config/research_sessions").glob("prop_mvp_20261011_*.yaml"))]
    for directory in (OUT / "a_momentum", OUT / "b_price_only_proxy", OUT / "c_opening_range_proxy"):
        targets.extend(sorted(p for p in directory.rglob("*") if p.is_file()))
    targets.extend([OUT / "preflight_data_quality.json", OUT / "frozen_manifest.json", OUT / "data_hashes.json",
                    OUT / "implementation_corrections.json", OUT / "trial_amendments.json", OUT / "summary.json",
                    OUT / "robustness_metrics.json", OUT / "liquidation_source_audit.json", OUT / "b_event_study_summary.json"])
    for path in targets:
        hashed[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    (OUT / "artifact_hashes.json").write_text(json.dumps(hashed, indent=2))

if __name__ == "__main__":
    main()
