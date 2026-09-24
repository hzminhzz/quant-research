#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.eow_rebuild import (
    FEATURES,
    build_events,
    load_config,
    parse_utc,
    portfolio_daily_mtm,
    prepare_all_markets,
    score_frozen_model,
    trade_summary,
    walk_forward_scores,
)

RUN = ROOT / "run_log/eow_rebuild/eow-ny-overlap-authoritative-20260924-final2"
CACHE = RUN / "forensics/cache"
CFG = ROOT / "config/eow_rebuild.yaml"
UTC = timezone.utc
SYMS = ("DE30", "NAS100")


def key(event):
    return f"{event.symbol}|{event.date}"


def metrics(events, scores, markets, threshold, cost_bps):
    scores = np.asarray(scores, dtype=float)
    summary = trade_summary(events, scores, threshold=threshold)
    _, portfolio = portfolio_daily_mtm(
        events,
        scores,
        markets,
        threshold=threshold,
        risk_unit_pct=1.0,
        roundtrip_cost_bps=cost_bps,
    )
    labels = np.asarray([int(e.label) for e in events], dtype=int)
    auc = None
    if len(np.unique(labels)) == 2 and len(events) > 1:
        auc = float(roc_auc_score(labels, scores))
    return {
        "candidates": len(events),
        "selected": summary["trade_count"],
        "win_rate_pct": summary["win_rate_pct"],
        "net_r": summary["net_r"],
        "mean_r": summary["mean_r"],
        "daily_sharpe": portfolio["annualized_sharpe"],
        "max_drawdown": portfolio["max_drawdown"],
        "score_auc": auc,
        "yearly": summary["yearly"],
    }


def subset(events, symbols):
    allowed = set(symbols)
    return [e for e in events if e.symbol in allowed]


def align_old_scores(events, parquet_path):
    frame = pl.read_parquet(parquet_path).filter(pl.col("symbol").is_in(list(SYMS)))
    score_map = {
        row["event_key"]: float(row["score"])
        for row in frame.select("event_key", "score").to_dicts()
    }
    missing = [key(e) for e in events if key(e) not in score_map]
    if missing:
        raise RuntimeError(f"missing old shared-model scores for {len(missing)} events")
    return np.asarray([score_map[key(e)] for e in events], dtype=float)


def main():
    config = load_config(CFG)
    threshold = float(config["strategy"]["meta_threshold"])
    cost_bps = float(config["execution"]["authoritative_roundtrip_bps"])
    dev_start = parse_utc(config["validation"]["initial_training"]["start"])
    dev_end = datetime(2024, 12, 31, 23, 59, 59, tzinfo=UTC)
    hold_start = parse_utc(config["validation"]["final_holdout"]["start"])
    hold_end = parse_utc(config["validation"]["final_holdout"]["end"])

    markets = prepare_all_markets(ROOT, config, end=hold_end)

    dev_all = build_events(
        markets,
        config,
        variant="corrected",
        roundtrip_cost_bps=cost_bps,
        decision_start=dev_start,
        decision_end=dev_end,
    ).events
    hold_all = build_events(
        markets,
        config,
        variant="corrected",
        roundtrip_cost_bps=cost_bps,
        decision_start=hold_start,
        decision_end=hold_end,
    ).events

    dev = {sym: subset(dev_all, (sym,)) for sym in SYMS}
    hold = {sym: subset(hold_all, (sym,)) for sym in SYMS}
    dev_pool = subset(dev_all, SYMS)
    hold_pool = subset(hold_all, SYMS)

    # Three pre-declared model trials: DE-only, NAS-only, pooled DE+NAS.
    de_scores, de_wf, de_model = walk_forward_scores(dev["DE30"], config)
    nas_scores, nas_wf, nas_model = walk_forward_scores(dev["NAS100"], config)
    pool_scores, pool_wf, pool_model = walk_forward_scores(dev_pool, config)

    de_hold_scores = score_frozen_model(de_model.model, hold["DE30"])
    nas_hold_scores = score_frozen_model(nas_model.model, hold["NAS100"])
    pool_hold_scores = score_frozen_model(pool_model.model, hold_pool)

    # Independent combined model: each instrument is scored by its own model.
    independent_dev_events = dev["DE30"] + dev["NAS100"]
    independent_dev_scores = np.concatenate([de_scores, nas_scores])
    independent_hold_events = hold["DE30"] + hold["NAS100"]
    independent_hold_scores = np.concatenate([de_hold_scores, nas_hold_scores])

    # Existing four-asset shared-model scores provide the prior baseline.
    old_shared_dev_scores = align_old_scores(dev_pool, CACHE / "can6_wf_dev.parquet")
    old_shared_hold_scores = align_old_scores(hold_pool, CACHE / "hold.parquet")

    result = {
        "experiment": "de30_nas100_timezone_corrected_meta_retrain",
        "status": "DIAGNOSTIC_RETRAIN_NO_TUNING",
        "contracts": {
            "symbols": list(SYMS),
            "excluded_and_frozen": ["JP225", "HK33"],
            "variant": "corrected",
            "roundtrip_cost_bps": cost_bps,
            "meta_threshold": threshold,
            "feature_set": list(FEATURES),
            "development": [dev_start.isoformat(), dev_end.isoformat()],
            "evaluation": [hold_start.isoformat(), hold_end.isoformat()],
            "model_trials": ["DE30_ONLY", "NAS100_ONLY", "POOLED_DE30_NAS100"],
            "no_threshold_search": True,
            "no_feature_search": True,
            "no_hyperparameter_search": True,
            "evaluation_caveat": "2025-2026 is mechanically frozen but was already inspected in prior forensic work, so it is not a pristine independent holdout for this newly proposed model-universe experiment.",
        },
        "counts": {
            "development": {sym: len(dev[sym]) for sym in SYMS},
            "evaluation": {sym: len(hold[sym]) for sym in SYMS},
        },
        "development": {
            "combined": {
                "raw_orb": metrics(dev_pool, np.ones(len(dev_pool)), markets, threshold, cost_bps),
                "old_four_asset_shared_meta": metrics(dev_pool, old_shared_dev_scores, markets, threshold, cost_bps),
                "independent_per_instrument_meta": metrics(independent_dev_events, independent_dev_scores, markets, threshold, cost_bps),
                "pooled_de_nas_meta": metrics(dev_pool, pool_scores, markets, threshold, cost_bps),
            },
            "DE30": {
                "raw_orb": metrics(dev["DE30"], np.ones(len(dev["DE30"])), markets, threshold, cost_bps),
                "independent_meta": metrics(dev["DE30"], de_scores, markets, threshold, cost_bps),
                "pooled_meta": metrics(
                    dev["DE30"],
                    [pool_scores[i] for i, e in enumerate(dev_pool) if e.symbol == "DE30"],
                    markets,
                    threshold,
                    cost_bps,
                ),
            },
            "NAS100": {
                "raw_orb": metrics(dev["NAS100"], np.ones(len(dev["NAS100"])), markets, threshold, cost_bps),
                "independent_meta": metrics(dev["NAS100"], nas_scores, markets, threshold, cost_bps),
                "pooled_meta": metrics(
                    dev["NAS100"],
                    [pool_scores[i] for i, e in enumerate(dev_pool) if e.symbol == "NAS100"],
                    markets,
                    threshold,
                    cost_bps,
                ),
            },
        },
        "evaluation_2025_2026": {
            "combined": {
                "raw_orb": metrics(hold_pool, np.ones(len(hold_pool)), markets, threshold, cost_bps),
                "old_four_asset_shared_meta": metrics(hold_pool, old_shared_hold_scores, markets, threshold, cost_bps),
                "independent_per_instrument_meta": metrics(independent_hold_events, independent_hold_scores, markets, threshold, cost_bps),
                "pooled_de_nas_meta": metrics(hold_pool, pool_hold_scores, markets, threshold, cost_bps),
            },
            "DE30": {
                "raw_orb": metrics(hold["DE30"], np.ones(len(hold["DE30"])), markets, threshold, cost_bps),
                "independent_meta": metrics(hold["DE30"], de_hold_scores, markets, threshold, cost_bps),
                "pooled_meta": metrics(
                    hold["DE30"],
                    [pool_hold_scores[i] for i, e in enumerate(hold_pool) if e.symbol == "DE30"],
                    markets,
                    threshold,
                    cost_bps,
                ),
            },
            "NAS100": {
                "raw_orb": metrics(hold["NAS100"], np.ones(len(hold["NAS100"])), markets, threshold, cost_bps),
                "independent_meta": metrics(hold["NAS100"], nas_hold_scores, markets, threshold, cost_bps),
                "pooled_meta": metrics(
                    hold["NAS100"],
                    [pool_hold_scores[i] for i, e in enumerate(hold_pool) if e.symbol == "NAS100"],
                    markets,
                    threshold,
                    cost_bps,
                ),
            },
        },
        "walk_forward_diagnostics": {
            "DE30_ONLY": de_wf,
            "NAS100_ONLY": nas_wf,
            "POOLED_DE30_NAS100": pool_wf,
            "final_inner_auc": {
                "DE30_ONLY": float(de_model.mean_auc),
                "NAS100_ONLY": float(nas_model.mean_auc),
                "POOLED_DE30_NAS100": float(pool_model.mean_auc),
            },
        },
    }

    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
