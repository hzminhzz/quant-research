from dataclasses import replace

import pytest

from src.portfolio_evidence import (
    BudgetUnit,
    MarkCadence,
    ReturnUnit,
    RiskBudgetPlan,
    SleeveEvidence,
    SleeveIdentity,
    TrialDisclosure,
    compare_sleeves,
)

DATES = ("2026-01-01", "2026-01-02", "2026-01-03")


def sleeve(name, gross, *, drag=None, carry=None, net=None, unit=ReturnUnit.CAPITAL,
           risk=.01, marks=MarkCadence.DAILY, costs=True, carry_ok=True, version="v1",
           denominator=100_000.0):
    gross = tuple(gross)
    drag = tuple((0.0,) * len(gross) if drag is None else drag)
    carry = tuple((0.0,) * len(gross) if carry is None else carry)
    net = tuple(g - d + c for g, d, c in zip(gross, drag, carry)) if net is None else tuple(net)
    return SleeveEvidence(
        SleeveIdentity(name, version, f"spec-{name}", f"code-{name}", "data1", "cost1", "cal1", "family1"),
        unit, DATES, gross, drag, carry, net, "daily-prior-close-capital-v1", "accounting-capital-A",
        denominator, risk, costs, carry_ok, marks, marks is MarkCadence.INTRADAY,
    )


def disclosure(*, unknown=0, outcomes=("negative", None), missing=("t2",)):
    return TrialDisclosure(("t1", "t2"), outcomes, unknown, missing)


def plan(baseline, candidate, *, unit=BudgetUnit.CAPITAL, budget=1, periods=252, trials=None):
    return RiskBudgetPlan(tuple(baseline), tuple(candidate), unit, budget, periods, trials or disclosure())


def test_first_day_loss_initial_wealth_audit_and_native_summary_are_separate():
    result = compare_sleeves([sleeve("a", [-.1, .05, -.02])], plan([], [("a", 1)]))
    metrics = dict(result.summaries)
    assert metrics["audit_max_drawdown_initial_wealth"] == pytest.approx(-.1)
    assert metrics["overlay_down_days"] == 2
    assert result.native_statistics_status.startswith("available:")
    assert dict(result.native_statistics)["max_drawdown"] == pytest.approx(-.02)
    assert result.plan.periods_per_year == 252


def test_periods_per_year_flows_to_native_diagnostic_and_is_retained():
    evidence = [sleeve("a", [.01, -.005, .02])]
    daily_252 = compare_sleeves(evidence, plan([], [("a", 1)], periods=252))
    daily_365 = compare_sleeves(evidence, plan([], [("a", 1)], periods=365))
    assert daily_252.plan.periods_per_year == 252
    assert daily_365.plan.periods_per_year == 365
    assert dict(daily_252.native_statistics)["annual_volatility"] != pytest.approx(
        dict(daily_365.native_statistics)["annual_volatility"]
    )


def test_per_date_capital_denominators_are_validated_and_preserved():
    values = (100_000.0, 99_000.0, 102_000.0)
    actual = sleeve("a", [0, 0, 0], denominator=values)
    broadcast = sleeve("b", [0, 0, 0], denominator=100_000.0)
    result = compare_sleeves([actual, broadcast], plan([], [("a", 1)]))
    assert result.sleeve_evidence[0].period_capital_denominator == values
    assert result.sleeve_evidence[1].period_capital_denominator == (100_000.0,) * len(DATES)
    for invalid in ((100_000.0, 0, 1), (100_000.0, float("inf"), 2), (1.0, 2.0)):
        with pytest.raises(ValueError, match="denominator"):
            replace(actual, period_capital_denominator=invalid)


def test_pairwise_co_loss_is_not_portfolio_down_days():
    a = sleeve("a", [-.1, .1, -.2])
    b = sleeve("b", [.2, -.1, -.1])
    result = compare_sleeves([a, b], plan([], [("a", .5), ("b", .5)]))
    pair = result.pairwise_co_losses[0]
    assert pair.sleeve_ids == ("a", "b")
    assert pair.simultaneous_loss_days == 1
    assert pair.joint_loss_severity == pytest.approx(.3)
    assert [(x.sleeve_id, x.sleeve_down_days) for x in result.sleeve_loss_summaries] == [("a", 2), ("b", 2)]
    assert dict(result.summaries)["overlay_down_days"] == 1


def test_identical_sleeves_remain_identical_and_opposite_sleeves_offset():
    a = sleeve("a", [.1, -.1, .1])
    b = sleeve("b", [.1, -.1, .1])
    c = sleeve("c", [-.1, .1, -.1])
    same = compare_sleeves([a, b], plan([], [("a", .5), ("b", .5)]))
    opposed = compare_sleeves([a, c], plan([], [("a", .5), ("c", .5)]))
    assert same.candidate_net == pytest.approx(a.net)
    assert opposed.candidate_net == pytest.approx((0, 0, 0))


def test_joint_block_indices_are_exposed_and_preserve_dependence_for_all_series():
    a = sleeve("a", [.1, -.1, .1])
    b = sleeve("b", [.1, -.1, .1])
    c = sleeve("c", [-.1, .1, -.1])
    same = compare_sleeves([a, b], plan([], [("a", .5), ("b", .5)]), samples=12, block_size=2, seed=9)
    opposed = compare_sleeves([a, c], plan([], [("a", .5), ("c", .5)]), samples=12, block_size=2, seed=9)
    again = compare_sleeves([a, b], plan([], [("a", .5), ("b", .5)]), samples=12, block_size=2, seed=9)
    assert same.resampled_indices == again.resampled_indices
    assert all(
        row == pytest.approx(tuple(a.net[index] for index in indices))
        for row, indices in zip(same.resampled_candidate_net, same.resampled_indices)
    )
    assert all(row == pytest.approx((0, 0, 0)) for row in opposed.resampled_candidate_net)
    assert all(len(indices) == len(DATES) for indices in same.resampled_indices)


@pytest.mark.parametrize("bad", [
    lambda s: replace(s, dates=(DATES[0], DATES[0], DATES[2])),
    lambda s: replace(s, dates=(DATES[1], DATES[0], DATES[2])),
    lambda s: replace(s, dates=(DATES[0], DATES[1])),
    lambda s: replace(s, gross=(float("nan"), 0, 0)),
])
def test_missing_duplicate_unsorted_or_nonfinite_data_rejected(bad):
    with pytest.raises(ValueError):
        bad(sleeve("a", [0, 0, 0]))


def test_noncanonical_date_and_truthy_qualification_values_rejected():
    actual = sleeve("a", [0, 0, 0])
    with pytest.raises(ValueError, match="ISO"):
        replace(actual, dates=("20260101", DATES[1], DATES[2]))
    with pytest.raises(TypeError, match="qualification"):
        replace(actual, costs_qualified="yes")


def test_unaligned_dates_rejected_without_intersection():
    short = replace(sleeve("b", [0, 0, 0]), dates=(DATES[0], DATES[1], "2026-01-04"))
    with pytest.raises(ValueError, match="align exactly"):
        compare_sleeves([sleeve("a", [0, 0, 0]), short], plan([], [("a", 1)]))


def test_unknown_path_never_authorizes_barrier_claim_and_trial_history_stays_visible():
    a = sleeve("a", [.01, 0, 0], marks=MarkCadence.INTRADAY)
    incomplete = disclosure(unknown=None, outcomes=("failed_retry", None), missing=("t2",))
    result = compare_sleeves([a], plan([], [("a", 1)], trials=incomplete))
    assert result.barrier_claim_allowed is False
    assert result.unsupported_claim_reasons == (
        "daily_return_overlay_has_no_raw_intraday_path", "no_combined_native_account_simulation",
    )
    assert not result.selection_adjustment_allowed
    assert "selection_history_incomplete_or_unknown" in result.evidence_status
    assert result.trial_disclosure.outcomes == ("failed_retry", None)
    assert result.sleeve_evidence == (a,)


def test_capital_only_sleeve_has_optional_risk_unit_but_r_budget_requires_it():
    a = sleeve("a", [.01, -.02, .03], risk=None)
    cap = compare_sleeves([a], plan([], [("a", 1)]))
    assert cap.candidate_net == pytest.approx((.01, -.02, .03))
    with pytest.raises(ValueError, match="risk_fraction"):
        compare_sleeves([a], plan([], [("a", .01)], unit=BudgetUnit.RISK, budget=.01))


def test_capital_and_risk_budget_have_explicit_fixed_unit_conversions():
    a = sleeve("a", [1, -2, 3], unit=ReturnUnit.RISK, risk=.01)
    capital_plan = compare_sleeves([a], plan([], [("a", 1)]))
    risk_plan = compare_sleeves([a], plan([], [("a", .01)], unit=BudgetUnit.RISK, budget=.01))
    assert capital_plan.candidate_net == pytest.approx(risk_plan.candidate_net)


def test_nonzero_baseline_risk_is_not_overwritten_by_zero_candidate_weight():
    capital_only = sleeve("a", [.01, -.01, .02], risk=None)
    with pytest.raises(ValueError, match="risk_fraction"):
        compare_sleeves(
            [capital_only],
            plan([("a", .01)], [("a", 0.0)], unit=BudgetUnit.RISK, budget=.01),
        )
    zero_weight = compare_sleeves(
        [capital_only], plan([], [("a", 0.0)], unit=BudgetUnit.RISK, budget=.01)
    )
    assert zero_weight.candidate_net == pytest.approx((0, 0, 0))


def test_drag_carry_reconciliation_and_execution_stress_preserve_signed_carry():
    a = sleeve("a", [.02, -.01, .01], drag=[.01, .02, .01], carry=[.02, -.01, .01])
    result = compare_sleeves([a], plan([], [("a", 1)]))
    stress = dict(result.cost_stress_net)
    assert result.candidate_net == pytest.approx((.03, -.04, .01))
    assert result.candidate_net[0] > result.candidate_gross[0]
    assert stress["2x_execution_drag_fixed_exposure"] == pytest.approx((.02, -.06, 0))
    assert stress["3x_execution_drag_fixed_exposure"] == pytest.approx((.01, -.08, -.01))
    with pytest.raises(ValueError, match="net must equal"):
        replace(a, net=(.02, -.01, .01))


def test_same_denominator_gross_component_is_not_compounded_as_its_own_equity_path():
    a = sleeve("a", [-1.5, 0, 0], carry=[1.6, 0, 0])
    result = compare_sleeves([a], plan([], [("a", 1)]))
    assert result.candidate_gross[0] == pytest.approx(-1.5)
    assert result.candidate_net[0] == pytest.approx(.1)


@pytest.mark.parametrize("returns", [(-1.0, 0, 0), (-1.1, 0, 0)])
def test_undefined_or_negative_equity_paths_rejected(returns):
    a = sleeve("a", returns)
    with pytest.raises(ValueError, match="greater than -100%"):
        compare_sleeves([a], plan([], [("a", 1)]))


def test_invalid_stressed_path_and_block_size_rejected():
    a = sleeve("a", [0, 0, 0], drag=[0, 0, 0])
    with pytest.raises(ValueError, match="block_size"):
        compare_sleeves([a], plan([], [("a", 1)]), samples=1, block_size=4)
    ruin = sleeve("ruin", [0, 0, 0], drag=[.5, .5, .5])
    with pytest.raises(ValueError, match="greater than -100%"):
        compare_sleeves([ruin], plan([], [("ruin", 1)]), samples=0)


def test_full_identity_bindings_survive_comparison():
    a = sleeve("a", [0, 0, 0], version="v9")
    result = compare_sleeves([a], plan([], [("a", 1)]))
    assert result.sleeve_evidence[0].identity == a.identity
    assert result.sleeve_evidence[0].return_basis_id == "daily-prior-close-capital-v1"
    assert result.sleeve_evidence[0].denominator_id == "accounting-capital-A"


def test_budget_constraints_and_trial_validation():
    with pytest.raises(ValueError, match="budget"):
        plan([], [("a", .6), ("b", .5)])
    with pytest.raises(ValueError, match="distinct"):
        TrialDisclosure(("t1", "t1"), ("x", "y"), 0)
    with pytest.raises(ValueError, match="blank"):
        TrialDisclosure(("t1",), ("",), 0)
    with pytest.raises(ValueError, match="distinct"):
        TrialDisclosure((), (), 0)
