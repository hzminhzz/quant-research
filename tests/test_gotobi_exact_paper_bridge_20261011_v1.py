"""Regression and independent-source checks for the author Gotobi calendar bridge."""
from datetime import date
from pathlib import Path
import importlib.util

import polars as pl
import pytest

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/"run_log/gotobi_exact_paper_bridge_20261011_v1"
OLD=ROOT/"run_log/gotobi_paper_replication_20261011_v1"
SOURCE=ROOT/"scripts/run_gotobi_exact_paper_bridge_20261011_v1.py"
spec=importlib.util.spec_from_file_location("gotobi_paper_bridge",SOURCE)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

def test_calendar_last_business_day_replaces_nominal30():
    cal=pl.read_parquet(ROOT/"run_log/tokyo_fix_alpha_map_program1_20261010/execution_v1/calendar_event_registry.parquet")
    subset=cal.filter(pl.col("session").is_between(date(2020,1,1),date(2025,12,31)))
    author,labels=mod.source_calendar(subset)
    gotobi=set(author.filter(pl.col("author_gotobi"))["session"].to_list())
    assert date(2025,10,31) in gotobi
    assert date(2025,10,30) not in gotobi
    assert "last_calendar_day" in labels[date(2025,10,31)]
    assert "nominal_25" in labels[date(2025,10,24)] or date(2025,10,25) in gotobi
    assert date(2025,10,31) not in set(subset.filter(pl.col("gotobi"))["session"].to_list())

def test_original_previously_executed_results_parity():
    old=pl.read_parquet(OLD/"runs/gotobi_1pip/trades.parquet").filter(
        pl.col("year")<=2025).select("session","gross_pips")
    new=pl.read_parquet(ART/"bridge_B0_previous_calendar_strict_0954open.parquet").select(
        "session",pl.col("gross_pips").alias("replicated_pips"))
    joined=old.join(new,on="session",validate="1:1")
    assert old.height==290 and new.height==290 and joined.height==290
    assert float((joined["gross_pips"]-joined["replicated_pips"]).abs().max())<1e-9

def test_paper_close_and_native_execution_have_distinct_timing():
    paper=pl.read_parquet(ART/"author_paper_exact_trades.parquet")
    native=pl.read_parquet(ART/"native/trades.parquet")
    assert paper.height==native.height==370
    # The author marks the 09:55 candle CLOSE, while the native engine
    # waits until the 09:56 OPEN. They must never be mislabeled identical.
    native_gross=native.select("session",((pl.col("src_exit")-pl.col("src_entry"))/.01).alias("native_gross"))
    common=paper.select("session",pl.col("gross_pips").alias("paper_gross")).join(native_gross,on="session",validate="1:1")
    assert common.height==370
    assert abs(float((common["paper_gross"]-common["native_gross"]).mean()))>0.01
    assert native.filter(pl.col("exit_at").dt.convert_time_zone("Asia/Tokyo").dt.strftime("%H:%M")!="09:56").is_empty()
    assert native.filter(pl.col("entry_at").dt.convert_time_zone("Asia/Tokyo").dt.strftime("%H:%M")!="03:00").is_empty()

def test_calendar_event_coverage_and_protected_boundaries():
    panel=pl.read_parquet(ART/"event_panel.parquet")
    assert panel["session"].max() <= date(2025,12,31)
    assert panel.filter(pl.col("author_gotobi")).height==429
    exact=pl.read_parquet(ART/"author_paper_exact_trades.parquet")
    assert exact.height==370
    assert exact["session"].is_duplicated().sum()==0
