"""ML4T Quantitative Research Suite.

Core modular libraries:
- patterns: Candlestick pattern detection with TA-Lib parity
- features: Vectorized technical, momentum, and regime features
- labeling: Triple-Barrier and Meta-Labeling engines
- backtest: Institutional execution simulation with transaction cost models
- pipeline: Standardized ML4T 4-stage pipeline contract & orchestration
"""

from src.patterns import detect_engulfing, detect_high_sharpe_engulfing
from src.features import (
    compute_ema,
    compute_rsi,
    compute_atr,
    compute_realized_volatility,
    compute_bollinger_bands,
    compute_momentum_panel,
)
from src.labeling import (
    compute_forward_returns,
    triple_barrier_labels,
    create_meta_labels,
)
from src.backtest import CostModel, run_intraday_backtest
from src.pipeline import (
    Stage1Result,
    Stage2Result,
    Stage3Result,
    Stage4Result,
    PipelineReport,
    run_stage1_features,
    run_stage2_diagnostics,
    run_stage3_backtest,
    run_stage4_meta_labeling,
    run_full_pipeline,
)

__all__ = [
    "detect_engulfing",
    "detect_high_sharpe_engulfing",
    "compute_ema",
    "compute_rsi",
    "compute_atr",
    "compute_realized_volatility",
    "compute_bollinger_bands",
    "compute_momentum_panel",
    "compute_forward_returns",
    "triple_barrier_labels",
    "create_meta_labels",
    "CostModel",
    "run_intraday_backtest",
    "Stage1Result",
    "Stage2Result",
    "Stage3Result",
    "Stage4Result",
    "PipelineReport",
    "run_stage1_features",
    "run_stage2_diagnostics",
    "run_stage3_backtest",
    "run_stage4_meta_labeling",
    "run_full_pipeline",
]
