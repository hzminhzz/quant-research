"""ML4T Quantitative Research Suite.

Core modular libraries:
- patterns: Candlestick pattern detection with TA-Lib parity
- features: Vectorized technical, momentum, and regime features
- labeling: Triple-Barrier and Meta-Labeling engines
- diagnostics: Factor predictive diagnostics, Rank IC, and decay
- models: Combinatorial Purged CV & Supervised Meta-Labeling
- backtest: Institutional execution simulation with transaction cost models
- synthesis: Deflated Sharpe Ratio (DSR) and tearsheet reporting
- pipeline: Standardized ML4T 7-stage artifact pipeline contract & orchestration
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
from src.diagnostics import (
    compute_spearman_rank_ic,
    compute_ic_decay,
    evaluate_factor,
    FactorDiagnosticReport,
)
from src.models import train_meta_model_cpcv, CPCVResult
from src.backtest import CostModel, run_intraday_backtest
from src.synthesis import (
    compute_dsr_audit,
    generate_tearsheet_metrics,
    log_strategy_trial,
    load_strategy_trials,
    TrialEntry,
)
from src.pipeline import (
    StageContract,
    CaseStudyPipelineReport,
    ML4TCaseStudyPipeline,
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
    "compute_spearman_rank_ic",
    "compute_ic_decay",
    "evaluate_factor",
    "FactorDiagnosticReport",
    "train_meta_model_cpcv",
    "CPCVResult",
    "CostModel",
    "run_intraday_backtest",
    "compute_dsr_audit",
    "generate_tearsheet_metrics",
    "log_strategy_trial",
    "load_strategy_trials",
    "TrialEntry",
    "StageContract",
    "CaseStudyPipelineReport",
    "ML4TCaseStudyPipeline",
]
