import pytest

from src.hftbacktest_accounting import (
    assert_trade_reconciliation,
    attribute_trade,
    entry_fully_confirmed,
    execution_cost,
    exit_fully_confirmed,
)


def test_entry_requires_both_confirmed_fills_and_positions():
    assert not entry_fully_confirmed(True, False, 0.01, -0.2)
    assert not entry_fully_confirmed(True, True, 0.01, 0.0)
    assert entry_fully_confirmed(True, True, 0.01, -0.2)


def test_exit_requires_both_fills_and_flat_positions():
    assert not exit_fully_confirmed(True, False, 0.0, 0.0)
    assert not exit_fully_confirmed(True, True, 0.01, 0.0)
    assert exit_fully_confirmed(True, True, 0.0, 0.0)
    assert exit_fully_confirmed(True, True, 1e-13, -1e-13)


def test_original_maker_cost_can_capture_spread():
    cost = execution_cost(
        signed_order_qty=1.0,
        exec_price=99.90,
        reference_mid=100.00,
        style="maker_original",
    )
    assert cost.maker_adverse_selection == pytest.approx(-0.10)
    assert cost.repeg_cost == pytest.approx(0.0)
    assert cost.total == pytest.approx(-0.10)


def test_repeg_cost_is_separate_from_original_passive_quote():
    cost = execution_cost(
        signed_order_qty=1.0,
        exec_price=100.00,
        reference_mid=100.00,
        style="maker_repeg",
        original_quote=99.90,
    )
    assert cost.maker_adverse_selection == pytest.approx(-0.10)
    assert cost.repeg_cost == pytest.approx(0.10)
    assert cost.total == pytest.approx(0.0)


def test_taker_cost_splits_timing_and_crossing():
    cost = execution_cost(
        signed_order_qty=1.0,
        exec_price=100.30,
        reference_mid=100.00,
        style="taker",
        taker_submit_mid=100.20,
    )
    assert cost.taker_timing_cost == pytest.approx(0.20)
    assert cost.taker_crossing_cost == pytest.approx(0.10)
    assert cost.total == pytest.approx(0.30)


def test_attribution_identity_reconciles_exactly():
    trade = attribute_trade(
        gross_alpha=1.00,
        maker_adverse_selection=-0.10,
        repeg_cost=0.20,
        taker_timing_cost=0.10,
        taker_crossing_cost=0.05,
        taker_fee=0.04,
        net_pnl=0.71,
    )
    assert trade.taker_cost == pytest.approx(0.19)
    assert trade.reconciliation_residual == pytest.approx(0.0)
    assert trade.net_pnl == pytest.approx(
        trade.gross_alpha
        - trade.maker_adverse_selection
        - trade.repeg_cost
        - trade.taker_timing_cost
        - trade.taker_crossing_cost
        - trade.taker_fee
        + trade.reconciliation_residual
    )


def test_trade_reconciliation_requires_explicit_unclosed_component():
    completed = [-0.74, 1.12, -0.38]
    assert assert_trade_reconciliation(completed, sum(completed)) == pytest.approx(0.0)
    with pytest.raises(AssertionError):
        assert_trade_reconciliation(completed, sum(completed) + 0.01)
    assert assert_trade_reconciliation(
        completed,
        sum(completed) + 0.01,
        unclosed_realized_component=0.01,
    ) == pytest.approx(0.0)
