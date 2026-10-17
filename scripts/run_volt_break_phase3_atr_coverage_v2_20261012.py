"""VOLT BREAK Phase 3 single-instrument event diagnostics only.

Uses price-markouts and matched reference windows. It is NOT a backtest.
Source: Dukascopy USATECH.IDX/USD BID CFD, provider volume proxy.
No 2026 records are read. Methods: Polars + statsmodels HAC.
"""
from __future__ import annotations
import json
import hashlib
from pathlib import Path
import numpy as np
import polars as pl
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests

STORE = Path("/home/quant/dev/quant/ml4t-data/.data/store/index_minute_NQ")
FILES = [p for y in range(2018, 2026)
         for p in sorted((STORE / f"year={y}").glob("month=*/data.parquet"))]
assert len(FILES) == 96, f"expected 2018-2025 monthly source: {len(FILES)}"
# Freeze identity: existing vendor month SHA256 values are preserved in the
# previously inspected source_manifest; this script reports the exact input subset.
source_manifest_hash = hashlib.sha256(
    Path("run_log/one_bar_dukascopy_2013_2026_20261011/source_manifest.json").read_bytes()
).hexdigest()

src = (
    pl.scan_parquet([str(p) for p in FILES], hive_partitioning=False)
    .select(
        pl.col("timestamp").dt.replace_time_zone("UTC")
        .dt.convert_time_zone("America/Chicago").alias("ct"),
        pl.col("open"), pl.col("high"), pl.col("low"),
        pl.col("close"), pl.col("volume"),
    )
    .sort("ct")
    .with_columns(
        date=pl.col("ct").dt.date(),
        minute=pl.col("ct").dt.hour().cast(pl.Int32) * 60
              + pl.col("ct").dt.minute().cast(pl.Int32),
    )
    .with_columns(
        sess_date=pl.when(pl.col("minute") >= 1020)
        .then(pl.col("date") + pl.duration(days=1))
        .otherwise(pl.col("date"))
    )
    .collect()
)
assert src["ct"].n_unique() == src.height
assert bool(src.select(pl.all_horizontal([
    pl.col(c).is_finite() for c in ["open","high","low","close","volume"]
])).to_series().all())

# Daily Globex-like 17CT -> 16:14CT range. We do not assume this is
# equivalent to the author's unspecified 'ATR_Daily' convention.
daily = (
    src.group_by("sess_date")
    .agg(
        n=pl.len(), day_high=pl.col("high").max(),
        day_low=pl.col("low").min(), day_close=pl.col("close").last(),
    )
    .sort("sess_date")
    .with_columns(
        complete_session=pl.col("n") >= 1000,
    )
    .with_columns(
        previous_close=pl.col("day_close").shift(1),
    )
    .with_columns(
        daily_tr=pl.when(pl.col("complete_session")
                        & (pl.col("n").shift(1) >= 1000))
        .then(pl.max_horizontal(
            pl.col("day_high") - pl.col("day_low"),
            (pl.col("day_high") - pl.col("previous_close")).abs(),
            (pl.col("day_low") - pl.col("previous_close")).abs(),
        ))
        .otherwise(None),
    )
    .with_columns(
        atr15_prior=pl.col("daily_tr").rolling_mean(window_size=15, min_samples=15).shift(1),
    )
    .select(pl.col("sess_date").alias("date"), "atr15_prior", "complete_session")
)
assert daily["date"].n_unique() == daily.height

# Full source minute coverage: all 870 from 00:00 through 14:29 CT
# plus separate 14:30 CT open. It is permitted to examine only data through
# the day before the protected 2026 outcomes.
intraday = (
    src.filter(pl.col("date").dt.year().is_between(2019, 2025)
               & pl.col("minute").is_between(0, 870))
)
checks = intraday.group_by("date").agg(
    minutes=pl.col("minute").filter(pl.col("minute") < 870).n_unique(),
    midnight=(pl.col("minute") == 0).any(),
    open_1430=(pl.col("minute") == 870).any(),
    all_vol_positive=pl.col("volume").filter(pl.col("minute") < 870).min() > 0,
)
eligible_dates = checks.filter(
    (pl.col("minutes") == 870) & pl.col("midnight")
    & pl.col("open_1430") & pl.col("all_vol_positive")
).select("date")
assert eligible_dates.height == 1576, eligible_dates.height

minutes = intraday.join(eligible_dates, on="date", how="inner").sort("date", "minute")
trading = minutes.filter(pl.col("minute") < 870).with_columns(
    pv=((pl.col("high") + pl.col("low") + pl.col("close")) / 3.0) * pl.col("volume")
).with_columns(
    volume_sum=pl.col("volume").cum_sum().over("date"),
    pv_sum=pl.col("pv").cum_sum().over("date"),
    block=(pl.col("minute") // 30).cast(pl.Int32),
).with_columns(
    proxy_vwap=pl.col("pv_sum") / pl.col("volume_sum")
)
bar = (
    trading.group_by("date", "block")
    .agg(
        n=pl.len(), bar_close=pl.col("close").last(),
        vwap_at_close=pl.col("proxy_vwap").last(),
    )
    .with_columns(
        bar_end=(pl.col("block") + 1) * 30,
    ).sort("date", "bar_end")
)
assert bar.height == eligible_dates.height * 29
assert bar.filter(pl.col("n") != 30).height == 0

# Midnight quote from the same 00:00 CT research day.
midnight = trading.filter(pl.col("minute") == 0).select(
    "date", pl.col("open").alias("midnight_open")
)
bar = (
    bar.join(midnight, on="date", how="inner")
    .join(daily.select("date", "atr15_prior"), on="date", how="left")
    .with_columns(noise_barrier=pl.col("midnight_open") + 0.30 * pl.col("atr15_prior"))
    .with_columns(
        barrier_ok=pl.col("bar_close") > pl.col("noise_barrier"),
        vwap_ok=pl.col("bar_close") > pl.col("vwap_at_close"),
    )
    .with_columns(
        both_ok=pl.col("barrier_ok") & pl.col("vwap_ok"),
        year=pl.col("date").dt.year(),
    )
    .filter(pl.col("bar_end").is_between(600, 840)
            & pl.col("atr15_prior").is_not_null())
)
assert bar.filter(pl.col("atr15_prior") <= 0).height == 0
# Prices used as marks are opens at timestamp (not prior or future close).
boundaries = minutes.filter(pl.col("minute") % 30 == 0).select(
    "date", "minute", "open"
)
for new_col, end_expr in [
    ("entry", pl.col("bar_end")),
    ("next30", pl.col("bar_end") + 30),
    ("next60", pl.col("bar_end") + 60),
    ("exit1430", pl.lit(870)),
]:
    bar = (
        bar.with_columns(end_expr.alias(f"minute_{new_col}"))
        .join(boundaries.rename({
            "minute": f"minute_{new_col}",
            "open": f"open_{new_col}",
        }), on=["date", f"minute_{new_col}"], how="left")
    )
bar = bar.with_columns(
    mark_30=(pl.col("open_next30") - pl.col("open_entry")),
    mark_60=(pl.col("open_next60") - pl.col("open_entry")),
    mark_exit=(pl.col("open_exit1430") - pl.col("open_entry")),
)
assert bar.filter(pl.col("minute_entry") >= pl.col("minute_next30")).height == 0
assert bar.filter(pl.col("minute_entry") == 870).height == 0

# Strict one first hit per eligible day (not a simulated fill or reentry).
first = (
    bar.filter(pl.col("both_ok")).sort("date", "bar_end")
    .group_by("date").first().sort("date")
)

def hac_location(vals: list[float]) -> dict:
    v = np.asarray(vals, dtype=float)
    v = v[np.isfinite(v)]
    if len(v) < 12:
        return {"n": int(len(v)), "mean": float(v.mean()) if len(v) else None,
                "status": "INSUFFICIENT"}
    fit = sm.OLS(v, np.ones((len(v), 1), dtype=float)).fit(
        cov_type="HAC", cov_kwds={"maxlags": 5}
    )
    conf = fit.conf_int(alpha=0.05)[0]
    return {
        "n": int(len(v)), "mean": float(fit.params[0]),
        "se_hac": float(fit.bse[0]), "t_hac": float(fit.tvalues[0]),
        "p_hac": float(fit.pvalues[0]),
        "ci95": [float(conf[0]), float(conf[1])], "status": "ESTIMATED"
    }

out = {}
pvals = []
for horizon, return_col in [("30m", "mark_30"),("60m", "mark_60"),("1430", "mark_exit")]:
    # Fixed year-and-clock matched ordinary periods. Nontriggers are selected
    # only by known signal state at that clock, not future returns.
    ref = (
        bar.filter(~pl.col("both_ok") & pl.col(return_col).is_not_null())
        .group_by("year", "bar_end").agg(
            control_mean=pl.col(return_col).mean(),
            controls=pl.len(),
        )
    )
    matched = first.filter(pl.col(return_col).is_not_null()).join(
        ref, on=["year", "bar_end"], how="inner"
    ).filter(pl.col("controls") >= 5)
    matched = matched.with_columns(
        premium=pl.col(return_col) - pl.col("control_mean")
    ).sort("date")
    stats = hac_location(matched["premium"].to_list())
    raw = hac_location(matched[return_col].to_list())
    raw["mean_usd_gross_one_nq_equivalent"] = (
        raw["mean"] * 20 if raw["mean"] is not None else None
    )
    out[horizon] = {
        "matching": "year and CT decision clock, no-signal controls >=5",
        "signal_gross": raw,
        "matched_premium": stats,
        "controls_per_event_median": (
            float(matched["controls"].median()) if matched.height else None
        ),
        "yearly": matched.group_by("year").agg(
            first_hits=pl.len(),
            mean_gross_points=pl.col(return_col).mean(),
            mean_matched_premium_points=pl.col("premium").mean(),
            fraction_positive=(pl.col(return_col) > 0).mean(),
        ).sort("year").to_dicts(),
    }
    pvals.append(stats.get("p_hac", 1.0))
rejected, adjusted, _, _ = multipletests(pvals, alpha=0.05, method="holm")
for key, p, passed in zip(["30m","60m","1430"], adjusted, rejected):
    out[key]["matched_premium"]["holm3_p"] = float(p)
    out[key]["matched_premium"]["holm3_reject05"] = bool(passed)

# Descriptive decomposition on first qualification only; different cohorts,
# not a three-arm randomized experiment.
decomposition = {}
for label, pred in [("barrier_only", "barrier_ok"),("vwap_only", "vwap_ok"),("joint", "both_ok")]:
    e = (bar.filter(pl.col(pred))
         .sort("date","bar_end").group_by("date").first().sort("date"))
    decomp = e.filter(pl.col("mark_30").is_not_null())
    decomposition[label] = {
        "event_days": int(e.height),
        "gross_30m_points_mean": float(decomp["mark_30"].mean()) if decomp.height else None,
        "positive_fraction": float((decomp["mark_30"]>0).mean()) if decomp.height else None,
    }
res = {
    "session": "volt_break_nq_phase3_atr_coverage_v2_20261012",
    "status": "COMPLETED_DIAGNOSTIC",
    "classification": "EXPLORATORY",
    "approval_status": "NOT_APPROVED",
    "no_2026_market_outcomes_read": True,
    "source_provider": "Dukascopy USATECH.IDX/USD BID CFD proxy",
    "actual_cme_vwap": False,
    "atr_variant": "prior15_Globex_sessions_min1000_minute_count_TR_mean",
    "source_manifest_existing_sha256": source_manifest_hash,
    "files_2018_2025": len(FILES),
    "data_rows_2018_2025": int(src.height),
    "full_00_1430_ct_days_2019_2025": int(eligible_dates.height),
    "days_with_prior_atr_and_decision": int(bar["date"].n_unique()),
    "decision_rows": int(bar.height),
    "first_joint_signal_days": int(first.height),
    "no_joint_signal_days_in_atr_eligible": int(bar["date"].n_unique() - first.height),
    "primary_first_hit_by_year": first.group_by("year").agg(
        event_days=pl.len(),
        median_decision_minute=pl.col("bar_end").median(),
    ).sort("year").to_dicts(),
    "forward_markout_stats": out,
    "filter_decomposition": decomposition,
    "limitations": [
        "CFD BID price and provider-volume VWAP; not actual NQ futures execution",
        "SMA15(daily true range) is an explicit proxy interpretation, not confirmed nested ATR",
        "all 2019-2025 data are retrospective; 2026 held out",
        "one first hit/day ignores trade exits and reentries; Phase 4 required",
        "mean returns exclude spread, commissions, and slippage",
        "matched ordinary periods are observational, not causal flow identification",
        "multiple 30m observations per day are not treated as independent primary samples",
    ],
}
print(json.dumps(res, indent=2, sort_keys=True, allow_nan=False))
