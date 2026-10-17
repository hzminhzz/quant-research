"""Focused invariants for the Program 1 retrospective close-out v3."""
from __future__ import annotations
import json
from pathlib import Path
import math
import polars as pl
from scripts.correct_tokyo_alpha_map_calendar_v3 import exact_nominal

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"run_log/tokyo_alpha_map_program1_closure_v3"


def evidence(stage):
    return json.loads((OUT/stage/"result.json").read_text())


def test_window_specific_coverage_cannot_drop_2026_silently():
    win={x["name"]:x for x in evidence("T1_window_coverage")["windows"]}
    assert win["B_0956_1010"]["eligible"]==1625
    assert win["B_0956_1010"]["gotobi"]==468
    assert win["B_0956_1010"]["eligible_2026"]>0
    assert win["B_0956_1010"]["last_eligible"]=="2026-08-31"
    assert win["L_0300_0954"]["eligible"]==999
    assert win["L_0300_0954"]["last_eligible"]=="2026-04-24"
    assert evidence("T1_window_coverage")["holdout_read"] is False


def test_costs_and_cohort_partition():
    b=evidence("T3_postfix")["results"]["B_0956_1010"]
    g=b["groups"]["B1_gotobi"]
    o=b["groups"]["B0_ordinary"]
    assert g["sample"]["n"]+o["sample"]["n"]==1625
    assert math.isclose(g["costed_net_mean_pips"],g["sample"]["mean_pips"]-1,abs_tol=1e-12)
    assert b["groups"]["B3_original_gate_gotobi"]["sample"]["n"]<100


def test_nominal_day_exact_token_corrected():
    series=pl.Series("nominal",["5","15","25","30;5","10",None])
    assert exact_nominal(series,5).tolist()==[1,0,0,1,0,0]
    err=json.loads((OUT/"T4_calendar/nominal_exact_token_erratum.json").read_text())
    assert err["status"]=="CALENDAR_ERRATUM_VERIFIED"
    assert err["regressions"]["A_0830_0954"]["coefficients"]["nominal_5"]["n_label"]==78


def test_corrected_curve_anchor_and_uncertainty():
    df=pl.read_csv(OUT/"T2_alpha_windows/coverage_corrected_curves.csv")
    anchor=df.filter(pl.col("minute")==595).row(0,named=True)
    assert anchor["gotobi_n"]==468
    assert anchor["ordinary_n"]==1157
    assert abs(anchor["gotobi_mean"])<1e-12
    assert abs(anchor["ordinary_mean"])<1e-12
    assert (df["gotobi_n"]<=470).all()
    assert df.height==541


def test_verified_native_execution_reused_not_fabricated():
    t=evidence("T6_reconciliation")
    assert t["fill_count"]==4118
    assert t["independent_fill_oracle_status"]=="PASS"
    assert t["starting_usd_equity"]==10000
    assert t["fixed_usd_position_notional"]==10000
    assert t["conclusion"]=="EXPLORATORY_NOT_APPROVED"
