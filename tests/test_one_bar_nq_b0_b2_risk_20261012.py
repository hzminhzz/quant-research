import importlib.util
from pathlib import Path

import numpy as np
import polars as pl


MODULE_PATH = Path(__file__).parents[1] / "run_log/one_bar_nq_stop_scaling_20261012/risk_comparison_20261012/analyze.py"
SPEC = importlib.util.spec_from_file_location("b0_b2_risk", MODULE_PATH)
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


def test_safe_sharpe_handles_constant_calendar_series():
    assert analysis.safe_sharpe(np.zeros(10)) is None
    assert analysis.safe_sharpe(np.array([1.0, -1.0, 1.0, -1.0])) == 0.0


def test_trade_metrics_use_net_pnl_and_ex_ante_risk():
    df = pl.DataFrame({"pnl": [100.0, -50.0, 0.0], "nominal_risk_usd": [1000.0] * 3,
                       "r_multiple": [0.1, -0.05, 0.0], "quantity": [10, 10, 10],
                       "direction": ["long", "short", "long"]})
    stats = analysis.trade_stats(df, "fixture")
    assert stats["win_rate"] == 1 / 3
    assert stats["ties"] == 1
    assert stats["risk_unit_expectancy_r"] == np.mean([0.1, -0.05, 0.0])
    assert stats["stored_r_multiple_max_abs_error"] < 1e-12


def test_moving_block_bootstrap_is_paired_and_reproducible(monkeypatch):
    monkeypatch.setattr(analysis, "REPS", 40)
    a = np.tile([1.0, -0.5, 0.0, 0.25], 8)
    b = a * 0.5
    one = analysis.block_bootstrap(a, b, 5, 19, (5.0,))
    two = analysis.block_bootstrap(a, b, 5, 19, (5.0,))
    assert one == two
    assert one["prob_B2_sharpe_gt_B0"] == 0.0
    assert one["replicates"] == 40


def test_signed_short_quantity_is_positive_exposure_not_a_short_pnl_flip():
    df = pl.DataFrame({"pnl": [100.0, -50.0, -20.0],
        "nominal_risk_usd": [900.0, 950.0, 1000.0],
        "r_multiple": [100.0/900, -50.0/950, -20.0/1000],
        "quantity": [-4.0, 8.0, -10.0],
        "direction": ["short", "long", "short"],
        "fees": [10.0, 20.0, 25.0],
        "total_slippage_cost": [4.0, 8.0, 10.0]})
    orig = analysis.trade_stats(df, "B2")
    scaled = analysis.scale_b2_to_one_nq_equivalent(df)
    counter = analysis.trade_stats(scaled, "scaled")
    assert orig["quantity_median_mnq"] == 8.0
    assert orig["win_rate"] == counter["win_rate"] == 1/3
    assert orig["profit_factor"] > 0 and counter["profit_factor"] > 0
    assert abs(orig["risk_unit_expectancy_r"] - counter["risk_unit_expectancy_r"]) < 1e-12
    assert scaled["pnl"].to_list() == [250.0, -62.5, -20.0]
    assert scaled["quantity"].to_list() == df["quantity"].to_list()
    assert counter["fees_usd"] == 10*2.5 + 20*1.25 + 25.0
