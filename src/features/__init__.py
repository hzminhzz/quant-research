"""Feature package with stable legacy API and opt-in source-qualified features."""

from .legacy import (
    add_feature_availability,
    join_features_at_decision,
    compute_ema,
    compute_rsi,
    compute_atr,
    compute_realized_volatility,
    compute_bollinger_bands,
    compute_momentum_panel,
    compute_garman_klass_volatility,
    compute_nr7,
    extract_breakout_feature_vector,
)
from .microstructure import add_book_imbalance, add_trade_sign_proxy, require_market_structure_capability
from .stationarity import fit_fractional_difference_d, add_fractional_difference
from .volatility import add_signed_semivariance_jump_proxy
from .spillover import join_cross_session_asof

__all__ = [
    "add_feature_availability", "join_features_at_decision", "compute_ema",
    "compute_rsi", "compute_atr", "compute_realized_volatility",
    "compute_bollinger_bands", "compute_momentum_panel",
    "compute_garman_klass_volatility", "compute_nr7",
    "extract_breakout_feature_vector", "add_book_imbalance",
    "add_trade_sign_proxy", "fit_fractional_difference_d",
    "require_market_structure_capability",
    "add_fractional_difference",
    "add_signed_semivariance_jump_proxy", "join_cross_session_asof",
]
