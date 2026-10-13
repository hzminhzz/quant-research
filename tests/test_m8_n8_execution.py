from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import polars as pl
import pytest
from ml4t.backtest import AssetClass, BacktestConfig, ContractSpec, DataFeed, Engine
from ml4t.backtest.config import (
    CommissionType,
    ExecutionMode,
    FillOrdering,
    SlippageType,
)
from ml4t.diagnostic.api import PortfolioAnalysis

from src.research_control.feature_gateway import FeatureContractError
from src.research_control.m8_n8 import (
    BASE_COST_BPS_PER_FILL,
    COMMISSION_BPS_PER_FILL,
    N8LongOnly,
    _assert_scheduled_fills_present,
    _dukascopy_bar_complete,
    _dukascopy_open,
    audit_n8_result,
    classify_n8_economics,
    expected_signals,
    summarize_n8_scenario,
)


def sample_bars() -> pl.DataFrame:
    start = datetime(2020, 1, 1, tzinfo=UTC)
    return pl.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=30 * index) for index in range(5)],
            "symbol": ["source"] * 5,
            "open": [100.0, 101.0, 102.0, 103.0, 104.0],
            "high": [101.0, 102.0, 103.0, 104.0, 105.0],
            "low": [99.0, 100.0, 101.0, 102.0, 103.0],
            "close": [100.5, 101.5, 102.5, 103.5, 104.5],
            "volume": [10.0] * 5,
        }
    )


def native_result(signals: list[int]):
    bars = sample_bars()
    prices = bars.rename({"symbol": "asset"})
    signal_data = pl.DataFrame(
        {
            "timestamp": bars["timestamp"],
            "asset": ["source"] * bars.height,
            "m8_n8_long": signals,
        }
    )
    strategy = N8LongOnly("source", bars["timestamp"][0], bars["timestamp"][-1])
    config = BacktestConfig(
        initial_cash=100_000.0,
        allow_short_selling=False,
        allow_leverage=False,
        execution_mode=ExecutionMode.NEXT_BAR,
        fill_ordering=FillOrdering.EXIT_FIRST,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=COMMISSION_BPS_PER_FILL / 10_000,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=BASE_COST_BPS_PER_FILL / 10_000,
    )
    result = Engine(
        DataFeed(prices_df=prices, signals_df=signal_data),
        strategy,
        config,
        contract_specs={
            "source": ContractSpec("source", AssetClass.EQUITY, multiplier=1.0)
        },
    ).run()
    return bars, result, strategy


def test_native_n8_fills_next_open_and_exit_following_open_with_reconciled_cash():
    bars, result, strategy = native_result([1, 1, 0, 0, 0])
    audit = audit_n8_result(
        result,
        strategy,
        bars,
        [bars["timestamp"][0], bars["timestamp"][1]],
        cost_multiple=1,
    )
    assert audit.status == "PASS"
    assert audit.evidence["executed_trade_count"] == 1
    trade = audit.evidence["trades"][0]
    assert trade["entry_at"] == "2020-01-01T00:30:00+00:00"
    assert trade["exit_at"] == "2020-01-01T01:00:00+00:00"
    assert trade["pnl_gross_normalized"] == 1.0
    metrics = summarize_n8_scenario(
        result,
        audit.evidence,
        bars["timestamp"][0],
        bars["timestamp"][-1] + timedelta(minutes=30),
    )
    assert metrics["trade_count"] == 1
    assert metrics["daily_sampling"].startswith("initial cash before first evaluation date")
    assert metrics["daily_risk_metrics_source"] == "ml4t.diagnostic.api.PortfolioAnalysis"


def test_m8_audit_rejects_entry_fill_on_the_decision_bar():
    bars, result, strategy = native_result([1, 0, 0, 0, 0])
    fills = result.to_fills_dataframe()
    fills = fills.with_columns(
        pl.Series(
            "timestamp",
            [bars["timestamp"][0], fills["timestamp"][1]],
            dtype=fills.schema["timestamp"],
        )
    )
    altered = SimpleNamespace(
        to_fills_dataframe=lambda: fills,
        to_equity_dataframe=result.to_equity_dataframe,
    )
    audit = audit_n8_result(
        altered,
        strategy,
        bars,
        [bars["timestamp"][0]],
        cost_multiple=1,
    )
    assert audit.status == "FAILED"
    assert audit.reason_code == "ENGINE_EXECUTION_INVALID"


def test_signal_eligibility_uses_schedule_and_not_future_bar_presence():
    signal_at = datetime(2020, 2, 3, 1, 0, tzinfo=UTC)
    stamps = [signal_at - timedelta(minutes=30 * (50 - i)) for i in range(53)]
    prices = pl.DataFrame(
        {
            "timestamp": stamps,
            "symbol": ["source"] * len(stamps),
            "high": [100.0] * len(stamps),
            "close": [99.0] * 50 + [101.0, 99.0, 99.0],
        }
    )
    features = pl.DataFrame(
        {
            "timestamp": stamps,
            "symbol": ["source"] * len(stamps),
            "prior_high_50": [None] * 50 + [100.0, 100.0, 100.0],
        }
    )
    start, end = stamps[0], stamps[-1] + timedelta(minutes=30)
    full = expected_signals(prices, features, start, end)
    truncated = expected_signals(prices.head(51), features.head(51), start, end)
    assert full == truncated == [signal_at]
    assert not _dukascopy_open(datetime(2024, 8, 4, 21, 30, tzinfo=UTC))
    assert _dukascopy_open(datetime(2024, 8, 4, 22, 0, tzinfo=UTC))
    assert _dukascopy_open(datetime(2024, 8, 2, 20, 0, tzinfo=UTC))
    assert not _dukascopy_bar_complete(datetime(2024, 8, 2, 20, 0, tzinfo=UTC))
    assert not _dukascopy_open(datetime(2024, 12, 25, 12, 0, tzinfo=UTC))
    with pytest.raises(FeatureContractError) as error:
        _assert_scheduled_fills_present(prices.head(51), [signal_at])
    assert error.value.reason_code == "EXECUTION_EXCEPTION"


def test_m8_schedule_uses_full_30m_bars_across_winter_summer_and_dst_edges():
    winter_sunday = datetime(2024, 1, 7, 23, 0, tzinfo=UTC)
    summer_sunday = datetime(2024, 7, 7, 22, 0, tzinfo=UTC)
    assert not _dukascopy_open(winter_sunday - timedelta(minutes=30))
    assert _dukascopy_bar_complete(winter_sunday)
    assert not _dukascopy_open(summer_sunday - timedelta(minutes=30))
    assert _dukascopy_bar_complete(summer_sunday)

    # Friday close is 21:15 UTC in winter and 20:15 UTC in summer.
    assert _dukascopy_bar_complete(datetime(2024, 1, 5, 20, 30, tzinfo=UTC))
    assert not _dukascopy_bar_complete(datetime(2024, 1, 5, 21, 0, tzinfo=UTC))
    assert _dukascopy_bar_complete(datetime(2024, 7, 5, 19, 30, tzinfo=UTC))
    assert not _dukascopy_bar_complete(datetime(2024, 7, 5, 20, 0, tzinfo=UTC))

    # Zurich and New York change clocks on different Sundays in March/October.
    # The predicate follows Zurich broker time on both sides of each switch.
    for day in (datetime(2024, 3, 24, 23, 0, tzinfo=UTC), datetime(2024, 3, 31, 22, 0, tzinfo=UTC),
                datetime(2024, 10, 20, 22, 0, tzinfo=UTC), datetime(2024, 10, 27, 23, 0, tzinfo=UTC)):
        assert _dukascopy_bar_complete(day)


def test_m8_signal_horizon_stays_strictly_before_protected_holdout():
    holdout = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
    final_2024_signal = datetime(2024, 12, 31, 19, 30, tzinfo=UTC)
    prior = [final_2024_signal - timedelta(minutes=30 * offset)
             for offset in range(50, 0, -1)]
    stamps = prior + [final_2024_signal,
                      datetime(2024, 12, 31, 23, 0, tzinfo=UTC)]
    prices = pl.DataFrame(
        {
            "timestamp": stamps,
            "symbol": ["source"] * len(stamps),
            "high": [100.0] * 50 + [101.0, 104.0],
            "close": [99.0] * 50 + [101.0, 103.0],
        }
    )
    features = pl.DataFrame(
        {
            "timestamp": stamps,
            "symbol": ["source"] * len(stamps),
            "prior_high_50": [None] * 50 + [100.0, 101.0],
        }
    )
    signals = expected_signals(prices, features, stamps[0], holdout)
    assert signals == [final_2024_signal]
    assert all(signal + 2 * timedelta(minutes=30) < holdout for signal in signals)


def test_m8_frozen_falsifier_distinguishes_negative_fragile_and_inconclusive():
    scenarios = [
        {"metrics": {"trade_count": 5, "net_trade_expectancy_native": 0.01,
                      "total_gross_pnl_normalized_native": 10.0}},
        {"metrics": {"trade_count": 5, "net_trade_expectancy_native": -0.01,
                      "total_gross_pnl_normalized_native": 10.0}},
        {"metrics": {"trade_count": 5, "net_trade_expectancy_native": -0.02,
                      "total_gross_pnl_normalized_native": 10.0}},
    ]
    assert classify_n8_economics(scenarios) == "POSITIVE_BASELINE_FRAGILE_TO_COST_STRESS"
    scenarios[0]["metrics"]["net_trade_expectancy_native"] = -0.01
    assert classify_n8_economics(scenarios) == "FALSIFIED_NONPOSITIVE_GROSS_OR_BASE_NET_EXPECTANCY"
    scenarios[0]["metrics"]["trade_count"] = 0
    assert classify_n8_economics(scenarios) == "INCONCLUSIVE_NO_TRADES"


def test_portfolio_analysis_metrics_match_independent_daily_return_oracle():
    returns = [0.01, -0.005, 0.0, 0.02]
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    expected_sharpe = mean / variance**0.5 * 252**0.5
    wealth = [1.0]
    for value in returns:
        wealth.append(wealth[-1] * (1 + value))
    peak = wealth[0]
    drawdowns = []
    for value in wealth[1:]:
        peak = max(peak, value)
        drawdowns.append(value / peak - 1)
    result = PortfolioAnalysis(
        pl.Series(returns), periods_per_year=252
    ).compute_summary_stats()
    assert result.sharpe_ratio == pytest.approx(expected_sharpe)
    assert result.max_drawdown == pytest.approx(min(drawdowns))
    assert result.calmar_ratio == pytest.approx(result.annual_return / abs(result.max_drawdown))
