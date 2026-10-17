"""Frozen ten D1 variants: causal gates and source baseline invariants."""
import polars as pl
import pytest

from scripts.mechanicalpremia_c3_d1_naive_ten_20261014 import VARIANTS, apply_d1_variant
from scripts.mechanicalpremia_us2_2013_2026_v1 import HOLDOUT, TRIAL_WEIGHTS
from scripts.run_mechanicalpremia_c3_d1_naive_ten_20261014 import STRESS_YEARS


def sample():
    return pl.DataFrame({
        "timestamp": [1,2,3,4,5,6],
        "d_trend": [True,True,True,True,False,True],
        "d_lowvol": [True,True,True,False,True,False],
        "d_pctb": [0.15,0.42,0.26,0.71,0.10,None],
        "d_enter": [True,False,False,False,False,False],
        "d_exit": [False,False,False,False,False,False],
        "h_enter": [False,True,False,True,False,True],
        "last_d_atr": [10.0]*6,
    })


def test_ten_unique_rules_are_registered_before_any_run():
    assert len(VARIANTS)==10
    assert len(set(VARIANTS.values()))==10
    assert STRESS_YEARS=={2021,2024,2025,2026}
    assert HOLDOUT.year==2026 and HOLDOUT.month==10 and HOLDOUT.day==12
    assert (TRIAL_WEIGHTS["PORTFOLIO-SOURCE-RISK"].h,
            TRIAL_WEIGHTS["PORTFOLIO-SOURCE-RISK"].d)==(0.2336,0.7664)


def test_baseline_preserves_source_flags_and_h1_exit_timing():
    before=sample()
    after=apply_d1_variant(before,"C3-BASELINE")
    assert after["d_enter"].to_list()==before["d_enter"].to_list()
    assert after["d_exit"].to_list()==before["d_exit"].to_list()
    assert after["h_enter"].to_list()==before["h_enter"].to_list()
    with pytest.raises(ValueError):
        apply_d1_variant(before,"UNREGISTERED")


def test_monotone_relaxation_and_causal_null_warmup():
    src=sample()
    outputs={v:apply_d1_variant(src,v) for v in VARIANTS}
    count={k:sum(v["d_enter"]) for k,v in outputs.items()}
    assert count["N01-LV-PB35"]<=count["N02-LV-PB50"]<=count["N03-LV-PB80"]
    assert count["N04-PB20"]<=count["N05-PB35"]<=count["N06-PB50"]<=count["N07-PB80"]
    assert count["N03-LV-PB80"]<=count["N08-LV-ONLY"]
    assert count["N07-PB80"]<=count["N09-TREND"]
    assert count["N01-LV-PB35"]>sum(src["d_enter"])
    assert outputs["N09-TREND"]["d_enter"][-1] is False
    for value in outputs.values():
        assert value["d_exit"].to_list()==src["d_exit"].to_list()
        assert value["h_enter"].to_list()==src["h_enter"].to_list()
        assert value["last_d_atr"].to_list()==src["last_d_atr"].to_list()
