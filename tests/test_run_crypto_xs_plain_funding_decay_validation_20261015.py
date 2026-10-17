from __future__ import annotations

from scripts.run_crypto_xs_plain_funding_decay_validation_20261015 import (
    REF_FUNDING_YIELD,
    REF_MEAN_IC,
    terminal_and_decay,
)


def _ic(mean_ic: float) -> dict:
    return {"mean_ic": mean_ic}


def _opp(spread_ratio: float = 1.0) -> dict:
    return {
        "funding_spread_ratio_to_2022_2023": spread_ratio,
        "funding_std_ratio_to_2022_2023": 1.0,
        "funding_iqr_ratio_to_2022_2023": 1.0,
    }


def _arm(ret: float, funding_yield: float = 0.3) -> dict:
    return {
        "total_return": ret,
        "annualized_funding_yield_on_avg_gross": funding_yield,
    }


def test_decay_gate_validates_surviving_edge_and_classifies_partial_decay():
    terminal, decay, reasons, ratios = terminal_and_decay(
        _ic(REF_MEAN_IC * 0.4),
        _opp(0.7),
        _arm(0.2, REF_FUNDING_YIELD * 0.8),
        _arm(0.05),
        _arm(0.1, 0.0),
    )
    assert terminal == "VALIDATE"
    assert decay == "PARTIAL_DECAY"
    assert not reasons
    assert ratios["ic_ratio_to_2022_2023"] == 0.4


def test_decay_gate_rejects_economic_failure():
    terminal, decay, reasons, _ = terminal_and_decay(
        _ic(REF_MEAN_IC),
        _opp(),
        _arm(-0.01, REF_FUNDING_YIELD),
        _arm(0.01),
        _arm(0.0, 0.0),
    )
    assert terminal == "REJECT"
    assert decay == "STRUCTURAL_DECAY"
    assert reasons


def test_decay_gate_detects_carry_mechanism_shift():
    terminal, decay, reasons, _ = terminal_and_decay(
        _ic(-0.001),
        _opp(),
        _arm(0.2, REF_FUNDING_YIELD * 0.8),
        _arm(0.05),
        _arm(-0.1, 0.0),
    )
    assert terminal == "VALIDATE"
    assert decay == "MECHANISM_SHIFT_CARRY"
    assert not reasons
