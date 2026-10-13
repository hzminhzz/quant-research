"""Native Dukascopy 15:14 CFD clock and strict pilot integration, synthetic only."""
from datetime import date, timedelta

import polars as pl
from ml4t.backtest import (
    AssetClass,
    BacktestConfig,
    ContractSpec,
    DataFeed,
    ExecutionMode,
    StopFillMode,
)
from ml4t.backtest.config import CommissionType, FillOrdering, SlippageType

from src.research_control.dukascopy_migration import (
    dukascopy_feature_contract,
    features_for_legacy_rules,
    strict_sessions,
)
from src.research_control.dukascopy_native import (
    DATA_SYMBOL,
    ENGINE_VERSION,
    LegalLimitsEngine,
)
from src.research_control.dukascopy_strategy import DukascopyClockStrategy
from tests.test_dukascopy_migration import synthetic_cfds


def test_native_migrated_b1_cfd_forced_flat_on_real_1514_bar():
    source = synthetic_cfds(445).with_columns(
        (pl.col("timestamp") - timedelta(minutes=40)).alias("timestamp")
    )
    features, _ = features_for_legacy_rules(
        source, dukascopy_feature_contract("duk-m4-synthetic"))
    bars, qa = strict_sessions(features, date(2026, 1, 5), date(2026, 1, 5))
    assert bars.height == 405
    assert len(qa["accepted_days"]) == 1
    strategy = DukascopyClockStrategy("B1")
    cfg = BacktestConfig(
        initial_cash=1_000_000.0, allow_short_selling=False, allow_leverage=True,
        fixed_margin_schedule={DATA_SYMBOL: (25_000.0, 20_000.0)},
        execution_mode=ExecutionMode.NEXT_BAR,
        fill_ordering=FillOrdering.EXIT_FIRST, stop_fill_mode=StopFillMode.STOP_PRICE,
        commission_type=CommissionType.NONE, slippage_type=SlippageType.NONE
    )
    engine = LegalLimitsEngine(
        DataFeed(
            prices_df=bars.select("timestamp", "asset", "open", "high", "low", "close", "volume"),
            signals_df=bars.select("timestamp", "asset", "or_high", "prior_close", "vwap", "adx", "prior_adx", "next_tp", "next_sl")
        ),
        strategy,
        cfg,
        contract_specs={DATA_SYMBOL: ContractSpec(symbol=DATA_SYMBOL, asset_class=AssetClass.FUTURE,
                                                   multiplier=20.0, tick_size=0.25, margin=25_000)}
    )
    result = engine.run()
    assert ENGINE_VERSION == "0.1.7"
    assert result.to_equity_dataframe().height == 405
    assert result.to_fills_dataframe().height % 2 == 0
    assert len(strategy.signal_log) > 0
    assert all(s["expected_entry_at"] > s["signal_at"] for s in strategy.signal_log)
    for record in result.to_fills_dataframe().iter_rows(named=True):
        if record["order_type"] == "limit" and record["side"] == "sell":
            assert record["price"] >= record["limit_price"]
