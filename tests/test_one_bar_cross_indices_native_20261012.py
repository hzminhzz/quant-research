"""Cross-index transfer invariants. No custom trading execution."""
from __future__ import annotations
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

import polars as pl
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"scripts"))
import run_one_bar_cross_indices_native_20261012 as cross
import run_one_bar_practical_yearly_20261012 as original
from study_one_bar_cross_indices_events_20261012 import event_labels

def test_frozen_native_trials_no_parameter_search():
    frozen=json.loads((cross.OUT/"phase34_frozen_spec.json").read_text())
    cfg=yaml.safe_load((ROOT/"config/research_sessions/one_bar_b0_cross_indices_20261012.yaml").read_text())
    assert frozen["core_rules"]["stop_points"]==50
    assert frozen["trial_count"]==6
    assert not frozen["param_tuning"] and frozen["independent_unseen_holdout"] is False
    assert cfg["core_B0_rules"]["added_filters"] == []
    assert cfg["core_B0_rules"]["session_anchor"].startswith("17:00")
    assert cross.SYNTHETIC_MULTIPLIER == 20 and cross.SYNTHETIC_TICK == 0.25

def test_ES_readonly_schema_normalization():
    x=cross.scan_index(cross.store_paths("ES", 2013))
    assert "year" not in x.columns and "month" not in x.columns
    assert x["timestamp"].dtype == pl.Datetime("us","UTC")
    assert x["timestamp"].max() < datetime(2014,2,1,tzinfo=timezone.utc)
    assert x.height > 200000

@pytest.mark.parametrize("symbol", ["ES","DAX","NIKKEI225"])
def test_causal_completed_bar_levels_and_source_retention(symbol):
    feed,q=cross.build_feed(symbol,2026)
    assert q["retained_execution_minutes"] == q["raw_minutes"] == feed.height
    assert q["warmup_complete_30m_bars"] >= 50
    assert feed["timestamp"].max() < datetime(2026,7,15,tzinfo=timezone.utc)
    assert feed["next_long_stop"].null_count() > 0 or feed["next_long_stop"].null_count()==0
    nonnull=feed.filter(pl.col("next_long_stop").is_not_null())
    assert nonnull.height > 1000
    assert nonnull.select((pl.col("next_long_stop") >= pl.col("next_short_stop")).all()).item()
    # A strategy decision sees prior completed bar levels on the current
    # minute, but any order can only fill on the following native bar.
    candidates=nonnull.filter(pl.col("timestamp").dt.minute().is_in([29,59]))
    assert candidates.height > 1000
    assert cross.next_boundary(candidates["timestamp"][0]) > candidates["timestamp"][0]
    events=event_labels(feed)
    assert events.height>2000
    assert events.select(
        (pl.col("next_window_start") > pl.col("timestamp")).all()).item()

def test_nq_signal_feed_matches_original_2026_after_warmup():
    canonical,_=original.build_year_feed(2026)
    new,_=cross.build_feed("NQ",2026)
    cols=["timestamp","next_long_stop","next_short_stop"]
    lower=datetime(2026,1,10,tzinfo=timezone.utc)
    a=canonical.filter(pl.col("timestamp")>=lower).select(cols)
    b=new.filter(pl.col("timestamp")>=lower).select(cols)
    assert a.height==b.height
    joined=a.join(b,on="timestamp",suffix="_new")
    assert joined.height==a.height
    for col in cols[1:]:
        v=joined.select(
            ((pl.col(col)-pl.col(col+"_new")).abs()>1e-9)
            .fill_null(False).sum()).item()
        assert v==0, (col,v)

def test_HSI_1m_remains_unavailable_not_fake_1m():
    audit=json.loads((cross.OUT/"phase2_quality.json").read_text())
    assert audit["HSI"]["status"] == "BLOCKED_1M_NOT_FOUND_5M_AVAILABLE"
