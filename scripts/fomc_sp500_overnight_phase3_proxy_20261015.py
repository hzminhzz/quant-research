"""FOMC overnight price-proxy Phase 3 screen, separate from executable CFD/perps.

prepare -> freeze via research_session init -> evaluate -> record trial.
No trading orders, no homemade PnL engine, no protected 2025+ data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import numpy as np
import polars as pl
import scipy.stats as st
import statsmodels.api as sm
from statsmodels.stats.sandwich_covariance import cov_hac

ROOT = Path(__file__).resolve().parents[1]
SESSION = "fomc_sp500_overnight_gross_phase3_20261015_v1"
ORIGINAL = "fomc_overnight_uncertainty_premium_us500_cfd_20261015_v1"
AUDIT = ROOT / "docs/audit" / (ORIGINAL + "_source_preflight_v2.json")
SPEC = ROOT / "config/research_sessions" / (SESSION + ".yaml")
SOURCE = Path("/home/quant/dev/quant/ml4t-data/.data/store/index_minute_ES")
DATA = ROOT / "data/processed" / SESSION / "endpoint_bids.parquet"
RUN = ROOT / "run_log/diagnostics" / SESSION
REPORT = ROOT / "docs/audit" / (SESSION + ".md")
HOLDOUT = datetime(2025, 1, 1, tzinfo=UTC)
HAC_LAG = 2
EXPECTED_PAIRS = 53
ROLES = (
    ("fomc", "entry", "fomc_entry"),
    ("fomc", "exit", "fomc_exit"),
    ("control", "entry", "control_entry"),
    ("control", "exit", "control_exit"),
)


def _json_read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _hash(path: Path) -> str:
    with path.open("rb") as fp:
        return hashlib.file_digest(fp, "sha256").hexdigest()


def eligible_events() -> list[dict]:
    evidence = _json_read(AUDIT)
    assert evidence["candidate_statement_count"] == 63
    assert evidence["terminal_preflight_status"] == "BLOCKED_DATA"
    assert not evidence["signal_returns_inspected"]
    events = [e for e in evidence["events"] if e.get("source_coverage_complete")]
    assert len(events) == EXPECTED_PAIRS
    assert len({e["statement_date"] for e in events}) == EXPECTED_PAIRS
    assert {int(e["statement_date"][:4]) for e in events} == set(range(2018, 2025))
    assert all(e["calendar_eligibility"] for e in events)
    return events


@lru_cache(maxsize=270)
def _day_bars(day) -> pl.DataFrame:
    if not (2017 <= day.year < 2025):
        raise ValueError("Protected holdout or unsupported UTC date requested")
    path = SOURCE / f"year={day.year}/month={day.month}/day={day.day}/data.parquet"
    if not path.is_file():
        raise FileNotFoundError(path)
    # Only trusted predeclared endpoint partitions, no unrestricted scan.
    df = pl.read_parquet(
        path, columns=["timestamp", "symbol", "open", "high", "low", "close"]
    )
    if df["timestamp"].dtype.time_zone != "UTC":
        raise AssertionError("Non-UTC historical quote timestamps")
    if df["symbol"].unique().to_list() != ["ES"]:
        raise AssertionError("Instrument contamination")
    return df


def extract_endpoint(ts: datetime) -> dict:
    if not (datetime(2017, 1, 1, tzinfo=UTC) <= ts < HOLDOUT):
        raise ValueError("Holdout/invalid bar timestamp")
    frame = _day_bars(ts.date()).filter(pl.col("timestamp") == ts)
    if frame.height != 1:
        raise AssertionError(f"Exactly one source bar required at {ts}: {frame.height}")
    row = frame.row(0, named=True)
    if not (0 < row["low"] <= row["open"] <= row["high"]):
        raise AssertionError("Unusable endpoint price")
    return row


def prepare() -> None:
    """Store endpoints only. Do NOT compute any gross returns before the freeze."""
    if DATA.exists():
        raise FileExistsError(f"Immutable research input already exists: {DATA}")
    if not SPEC.is_file():
        raise FileNotFoundError("Missing predeclared research YAML")
    events = eligible_events()
    rows = []
    for event in events:
        for leg, action, source_key in ROLES:
            original = event["quote_checks"][source_key]["required_fill_bar"]
            assert original["available"], source_key
            ts = datetime.fromisoformat(original["timestamp_utc"])
            assert ts < HOLDOUT
            quote = extract_endpoint(ts)
            rows.append(
                {
                    "timestamp": ts,
                    "symbol": "ES",
                    "statement_date": event["statement_date"],
                    "control_statement_date": event["control_statement_date"],
                    "leg": leg,
                    "action": action,
                    "quote_side": "historical_bid_only",
                    "open": float(quote["open"]),
                    "high": float(quote["high"]),
                    "low": float(quote["low"]),
                    "close": float(quote["close"]),
                }
            )
    frame = pl.DataFrame(rows).sort("statement_date", "leg", "action")
    assert frame.height == 4 * EXPECTED_PAIRS
    assert frame["timestamp"].max() < HOLDOUT
    assert frame.group_by("statement_date", "leg", "action").len()["len"].max() == 1
    DATA.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(DATA)
    print(
        json.dumps(
            {
                "stage": "PREPARED_SOURCE_INPUT_ONLY_NO_RETURNS",
                "eligible_events": len(events),
                "endpoints": frame.height,
                "sha256": _hash(DATA),
                "path": str(DATA.relative_to(ROOT)),
                "frozen_session": False,
            },
            indent=2,
        ),
        flush=True,
    )


def gross_return(entry: float, exit_: float) -> float:
    """Bid-to-bid *price change*, not executable long-position PnL."""
    if not (np.isfinite(entry) and np.isfinite(exit_) and entry > 0 and exit_ > 0):
        raise ValueError("Invalid price proxy")
    return float(exit_ / entry - 1)


def hac_stats(x: np.ndarray) -> dict:
    """Preregistered mean, corrected Newey-West HAC(2) 95% t interval."""
    x = np.asarray(x, dtype=float)
    if len(x) < 3 or not np.all(np.isfinite(x)):
        raise ValueError("Insufficient or nonfinite event returns")
    fit = sm.OLS(x, np.ones((len(x), 1))).fit()
    var = float(cov_hac(fit, nlags=HAC_LAG, use_correction=True)[0, 0])
    if var < 0:
        raise AssertionError("Invalid HAC variance")
    se = float(np.sqrt(var))
    mean = float(x.mean())
    crit = float(st.t.ppf(0.975, len(x) - 1))
    lower, upper = mean - crit * se, mean + crit * se
    t = mean / se if se > 0 else None
    p = float(2 * st.t.sf(abs(t), len(x) - 1)) if t is not None else None
    return {
        "mean_fraction": mean,
        "mean_bps": mean * 10000,
        "standard_error_bps": se * 10000,
        "lower_95_bps": lower * 10000,
        "upper_95_bps": upper * 10000,
        "t_statistic": t,
        "two_sided_p_value": p,
        "n_events": len(x),
        "hac_lags_frozen": HAC_LAG,
        "critical_t_df": len(x) - 1,
        "method": "OLS intercept, cov_hac nlags=2 correction=True, t critical df=n-1",
    }


def _paired_frame(frame: pl.DataFrame) -> pl.DataFrame:
    assert frame.height == EXPECTED_PAIRS * 4
    assert frame["timestamp"].max() < HOLDOUT
    keys = {}
    for r in frame.iter_rows(named=True):
        key = (r["statement_date"], r["leg"], r["action"])
        if key in keys:
            raise AssertionError(f"Repeated event action: {key}")
        keys[key] = r
    rows = []
    for e in eligible_events():
        d = e["statement_date"]
        record = {
            "statement_date": d,
            "control_statement_date": e["control_statement_date"],
        }
        for leg in ("fomc", "control"):
            start = keys[(d, leg, "entry")]
            end = keys[(d, leg, "exit")]
            source_entry_key = leg + "_entry"
            source_exit_key = leg + "_exit"
            for action, row, source_key in (
                ("entry", start, source_entry_key),
                ("exit", end, source_exit_key),
            ):
                expected = e["quote_checks"][source_key]["required_fill_bar"][
                    "timestamp_utc"
                ]
                actual = row["timestamp"].isoformat()
                if datetime.fromisoformat(expected) != row["timestamp"]:
                    raise AssertionError(
                        f"Event {d}: corrupted {leg} {action} time {actual}"
                    )
                assert row["quote_side"] == "historical_bid_only"
                assert row["symbol"] == "ES"
            if not start["timestamp"] < end["timestamp"]:
                raise AssertionError(f"Invalid event holding clock {d} {leg}")
            record[leg + "_entry_bid_open"] = start["open"]
            record[leg + "_exit_bid_open"] = end["open"]
            record[leg + "_gross_return"] = gross_return(start["open"], end["open"])
            record[leg + "_entry_time_utc"] = start["timestamp"]
            record[leg + "_exit_time_utc"] = end["timestamp"]
        record["paired_gross_excess"] = (
            record["fomc_gross_return"] - record["control_gross_return"]
        )
        rows.append(record)
    df = pl.DataFrame(rows).sort("statement_date")
    assert df.height == EXPECTED_PAIRS
    return df


def evaluate() -> None:
    """Evaluate ONLY after immutable SessionSpecV1 registration."""
    session_path = ROOT / "run_log/research_sessions" / SESSION / "frozen_spec.json"
    if not session_path.is_file():
        raise RuntimeError("Must freeze Phase 3 session before computing returns")
    frozen = _json_read(session_path)
    if frozen["status"] != "FROZEN" or frozen["session_id"] != SESSION:
        raise RuntimeError("Frozen session identity mismatch")
    if frozen["spec"]["trials"] != [
        {
            "id": "phase3_signal_screen",
            "kind": "diagnostic",
            "description": frozen["spec"]["trials"][0]["description"],
        }
    ]:
        raise AssertionError("Unexpected declared trial")
    if REPORT.exists() or (RUN / "metrics.json").exists():
        raise FileExistsError("Do not overwrite terminal trial results")

    frame = pl.read_parquet(DATA)
    ledger = _paired_frame(frame)
    if frame["timestamp"].dtype.time_zone != "UTC":
        raise AssertionError("UTC timing not preserved")
    event = ledger["fomc_gross_return"].to_numpy()
    control = ledger["control_gross_return"].to_numpy()
    paired = ledger["paired_gross_excess"].to_numpy()
    if not np.allclose(paired, event - control, atol=1e-13, rtol=0):
        raise AssertionError("Independent paired return identity fails")
    candidate_stats, control_stats, paired_stats = (
        hac_stats(event),
        hac_stats(control),
        hac_stats(paired),
    )
    years = []
    for year, ydf in ledger.with_columns(
        pl.col("statement_date").str.slice(0, 4).cast(pl.Int16).alias("year")
    ).group_by("year", maintain_order=True):
        val = int(year[0])
        years.append(
            {
                "year": val,
                "n": ydf.height,
                "fomc_gross_mean_bps": float(ydf["fomc_gross_return"].mean() * 10000),
                "control_gross_mean_bps": float(
                    ydf["control_gross_return"].mean() * 10000
                ),
                "paired_gross_mean_bps": float(
                    ydf["paired_gross_excess"].mean() * 10000
                ),
            }
        )
    years.sort(key=lambda x: x["year"])
    if len(years) < 6:
        raise AssertionError("Chronological coverage below preregistered floor")

    # The proxy screen cannot establish venue-specific after-cost return.
    if (
        candidate_stats["mean_fraction"] > 0
        and paired_stats["mean_fraction"] > 0
        and paired_stats["lower_95_bps"] > 0
    ):
        decision = "PASS"
        reason = (
            "Gross proxy returns pass preregistered direction and paired HAC bound."
        )
    elif candidate_stats["upper_95_bps"] < 0 or paired_stats["upper_95_bps"] < 0:
        decision = "FAIL"
        reason = "Gross proxy returns show strongly negative candidate or paired mean."
    else:
        decision = "INCONCLUSIVE"
        reason = "Gross proxy result does not meet positive evidence or robust negative falsification."

    def acf(arr, k):
        a = arr[:-k]
        b = arr[k:]
        if np.std(a) <= 0 or np.std(b) <= 0:
            return None
        return float(np.corrcoef(a, b)[0, 1])

    metrics = {
        "session_id": SESSION,
        "phase3_signal_decision": decision,
        "phase3_reason": reason,
        "recorded_strategy_returns": False,
        "recorded_historical_hyperliquid_returns": False,
        "instrument": "Dukascopy ES bid-only price series: US500 quote proxy",
        "hypothesis": "FOMC overnight risk compensation in US500 prices",
        "original_cfd_after_cost_status": "BLOCKED_DATA_UNCHANGED",
        "events": len(paired),
        "event_years": len(years),
        "fomc_bid_proxy_gross": candidate_stats,
        "control_bid_proxy_gross": control_stats,
        "paired_bid_proxy_gross_increment": paired_stats,
        "candidate_positive_fraction": float((event > 0).mean()),
        "control_positive_fraction": float((control > 0).mean()),
        "paired_positive_fraction": float((paired > 0).mean()),
        "paired_serial_correlation_lag1": acf(paired, 1),
        "paired_serial_correlation_lag2": acf(paired, 2),
        "predeclared_positive_net_cost_budget_bps": (
            candidate_stats["mean_bps"] if candidate_stats["mean_bps"] > 0 else 0.0
        ),
        "net_cost_budget_interpretation": (
            "Mean candidate gross bid-to-bid price change is not net tradable "
            "PnL. Any nonnegative all-in friction above that amount would erase "
            "a positive gross mean. Perp funding may be signed."
        ),
        "by_year": years,
        "source_sha256": _hash(DATA),
        "preflight_sha256": _hash(AUDIT),
        "frozen_spec_sha256": frozen["spec_sha256"],
        "scope": "pre-2025, originally public literature overlap; not independent OOS",
        "venue_cost_model": "NONE - zero friction strictly for price proxy diagnostics",
        "prohibited_interpretation": (
            "Never call these bid-quote changes exchange or CFD executions, "
            "actual fill PnL, Hyperliquid historical perps, or a deployment pass"
        ),
    }
    RUN.mkdir(parents=True, exist_ok=True)
    # Output ledgers and terminal metrics to previously unpopulated unique paths.
    ledger.write_csv(RUN / "event_pairs_gross_proxy.csv")
    (RUN / "metrics.json").write_text(
        json.dumps(metrics, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    lines = [
        "# Phase 3: FOMC overnight price-only event screen",
        "",
        f"**Decision: {decision} (signal-only; not backtest)**",
        "",
        f"**Reason:** {reason}",
        "",
        f"- Retrospective events: **{len(paired)}**, in **{len(years)}** years (2018–2024).",
        "- Exact frozen entry/exit: 16:06 ET preceding statement day; 09:36 ET statement day.",
        "- Baseline: exactly one D−7 matched ordinary overnight.",
        "- All prices are Dukascopy bid-only minute BAR OPENS, not executed asks/bids.",
        "- No spreads, fees, swaps, dividends, market impact, funding or live orders.",
        "- This is a new exploratory adaptation. The original CFD BLOCKED_DATA decision remains intact.",
        "",
        "## Prespecified gross price results",
        "",
        "| Series | Mean (bps) | 95% HAC(2) CI (bps) | Positive events |",
        "|---|---:|---:|---:|",
    ]
    for name, s, hit in (
        ("FOMC overnight", candidate_stats, metrics["candidate_positive_fraction"]),
        ("Ordinary D-7 control", control_stats, metrics["control_positive_fraction"]),
        ("Matched increment", paired_stats, metrics["paired_positive_fraction"]),
    ):
        lines.append(
            f"| {name} | {s['mean_bps']:.3f} | "
            f"[{s['lower_95_bps']:.3f}, {s['upper_95_bps']:.3f}] | {hit:.1%} |"
        )
    lines.extend(
        [
            "",
            "## Annual attribution (gross bid price only)",
            "",
            "| Year | Pairs | FOMC (bps) | Control (bps) | Paired (bps) |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for r in years:
        lines.append(
            f"| {r['year']} | {r['n']} | {r['fomc_gross_mean_bps']:.3f} "
            f"| {r['control_gross_mean_bps']:.3f} | {r['paired_gross_mean_bps']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Interpreting signal evidence",
            "",
            (
                f"- Preregistered standard error: HAC(2). Paired "
                f"t={paired_stats['t_statistic']:.3f}, "
                f"two-sided p={paired_stats['two_sided_p_value']:.4g}."
            ),
            (
                "- Lag-1 and lag-2 paired serial correlations: "
                f"{metrics['paired_serial_correlation_lag1']}, "
                f"{metrics['paired_serial_correlation_lag2']}."
            ),
            (
                "- Average observed positive gross price-move budget per FOMC night: "
                f"{metrics['predeclared_positive_net_cost_budget_bps']:.3f} bps "
                "(NOT a verified after-cost profit margin)."
            ),
            (
                "- Significant overlap with published pre-FOMC research through 2023; "
                "this does not satisfy independent holdout qualification."
            ),
            (
                "- The matched ordinary overnight controls general index carry only "
                "approximately. It does not identify the causal risk counterpart or "
                "current Hyperliquid execution."
            ),
            "",
            "## Run identities",
            "",
            f"- Session spec SHA: `{frozen['spec_sha256']}`",
            f"- Input endpoint Parquet SHA: `{metrics['source_sha256']}`",
            f"- Historical 53-pair source-audit SHA: `{metrics['preflight_sha256']}`",
            f"- Ledger: `run_log/diagnostics/{SESSION}/event_pairs_gross_proxy.csv`",
            f"- Metrics: `run_log/diagnostics/{SESSION}/metrics.json`",
            "",
            (
                "**Boundary:** This is a pre-backtest diagnostic, not native Engine "
                "cash/equity accounting. The user's actual perpetual venue has real "
                "trading costs and funding and its S&P 500 contract did not trade "
                "in 2018–2024. A Phase 3 PASS is not VALIDATE; a weak result is not "
                "fabricated as net PnL."
            ),
            "",
        ]
    )
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {
                "phase3_signal_decision": decision,
                "events": len(paired),
                "years": len(years),
                "candidate_gross_mean_bps": candidate_stats["mean_bps"],
                "control_gross_mean_bps": control_stats["mean_bps"],
                "paired_gross_mean_bps": paired_stats["mean_bps"],
                "paired_95_hac_ci_bps": [
                    paired_stats["lower_95_bps"],
                    paired_stats["upper_95_bps"],
                ],
                "after_cost_qualified": False,
            },
            indent=2,
        ),
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare", action="store_true")
    group.add_argument("--evaluate", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        prepare()
    else:
        evaluate()


if __name__ == "__main__":
    main()
