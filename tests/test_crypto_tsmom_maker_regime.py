"""Unit tests for CryptoTSMOMRegimeStrategy (tests/test_crypto_tsmom_maker_regime.py)."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from src.strategies.crypto_tsmom_maker_regime import (
    CryptoTSMOMRegimeStrategy,
    StrategyRiskConfig,
)


def test_strategy_orders_on_conviction_momentum():
    strat = CryptoTSMOMRegimeStrategy()
    broker = MagicMock()
    broker.get_cash.return_value = 10000.0
    broker.get_portfolio_value.return_value = 10000.0
    broker.get_position.return_value = None

    strat.on_start(broker)

    # Feed data with positive ROC_168, valid regime weight, low choppiness
    bar_data = {
        "BTCUSDT": {
            "signals": {
                "roc_168": 0.05,
                "regime_scaled_weight": 0.25,
                "choppiness_index": 45.0,
            }
        }
    }

    strat.on_data(datetime.now(timezone.utc), bar_data, {}, broker)
    broker.order_target_percent.assert_called_once_with("BTCUSDT", 0.25)


def test_kill_switch_triggers_on_drawdown():
    strat = CryptoTSMOMRegimeStrategy(
        risk_config=StrategyRiskConfig(max_portfolio_drawdown=0.15)
    )
    broker = MagicMock()
    broker.get_cash.return_value = 10000.0
    broker.get_portfolio_value.return_value = 10000.0
    strat.on_start(broker)

    # Drop equity by 20%
    broker.get_portfolio_value.return_value = 8000.0

    bar_data = {
        "BTCUSDT": {
            "signals": {
                "roc_168": 0.05,
                "regime_scaled_weight": 0.25,
                "choppiness_index": 45.0,
            }
        }
    }

    strat.on_data(datetime.now(timezone.utc), bar_data, {}, broker)
    assert strat.kill_switch_tripped is True
    broker.flatten_all_positions.assert_called_once()
