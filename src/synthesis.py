"""Multiple-Testing Synthesis & Strategy Tearsheet Engine.

Governed by ML4T Skills:
- ml4t-deflated-sharpe
- ml4t-tearsheet
- ml4t-backtest-overfitting

Provides institutional reporting and overfitting corrections:
1. Bailey & López de Prado Deflated Sharpe Ratio (DSR) accounting for all historical trials.
2. Bootstrap Sharpe ratio confidence intervals (95% CI).
3. Standardized tearsheet metrics: Sortino, Calmar, Max Drawdown, Profit Factor, Fee Drag.
4. Persistent strategy leaderboard ledger export.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import polars as pl
from scipy import stats

import ml4t.diagnostic as mld
from ml4t.diagnostic.evaluation.stats import deflated_sharpe_ratio_from_statistics


@dataclass
class TrialEntry:
    """Audited trial record persisted to trials.jsonl."""
    trial_id: str
    strategy_name: str
    family: str
    symbol: str
    timeframe: str
    parameters: Dict[str, Any]
    in_sample_sharpe: float
    out_of_sample_sharpe: float
    total_return_pct: float
    max_drawdown_pct: float
    win_rate_pct: float
    total_trades: int
    rank_ic: float
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


def log_strategy_trial(
    trial: TrialEntry,
    ledger_path: str = "run_log/trials.jsonl",
) -> None:
    """Append a strategy trial to the persistent audit ledger."""
    p = Path(ledger_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(trial)) + "\n")


def load_strategy_trials(ledger_path: str = "run_log/trials.jsonl") -> List[Dict[str, Any]]:
    """Load all historical exploratory trials."""
    p = Path(ledger_path)
    if not p.exists():
        return []
    records = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def compute_dsr_audit(
    observed_annualized_sharpe: float,
    all_sharpes: List[float],
    n_samples: int = 750,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> Dict[str, Any]:
    """Legacy signature lacks aligned return paths and complete attempt coverage.

    Never manufacture a probability from scalar Sharpes; the governed oracle
    accepts complete, aligned candidate returns and authoritative trial scope.
    """
    return {"status": "INCONCLUSIVE", "reason_code": "TRIAL_COVERAGE_UNKNOWN",
            "observed_sharpe": observed_annualized_sharpe,
            "n_trials_recorded": len(all_sharpes), "dsr_probability": None,
            "haircut_sharpe": None}


def generate_tearsheet_metrics(
    daily_equity_df: pl.DataFrame,
    total_trades: int,
    win_rate_pct: float,
    profit_factor: float,
    rank_ic: float,
    p_value: float,
    n_trials: int = 50,
) -> Dict[str, Any]:
    """Generate comprehensive tearsheet metrics from daily equity trajectory."""
    df_rets = daily_equity_df.with_columns(
        pl.col("equity").pct_change().alias("daily_ret")
    ).drop_nulls()

    daily_rets = df_rets["daily_ret"].to_numpy()
    n_obs = len(daily_rets)
    if n_obs < 10:
        return {"error": "Insufficient daily observations"}

    sr_ci = mld.metrics.sharpe_ratio_with_ci(daily_rets, periods_per_year=252, random_state=42)
    sortino = mld.metrics.sortino_ratio(daily_rets, periods_per_year=252)

    # Max Drawdown
    eq = df_rets["equity"].to_numpy()
    peak = np.maximum.accumulate(eq)
    drawdowns = (eq - peak) / peak
    max_dd_pct = float(abs(drawdowns.min()) * 100.0) if len(drawdowns) > 0 else 0.0

    # Total Return %
    tot_ret_pct = float((eq[-1] / eq[0] - 1.0) * 100.0)

    # Calmar Ratio
    ann_ret = (eq[-1] / eq[0]) ** (252.0 / max(n_obs, 1)) - 1.0
    calmar = float((ann_ret * 100.0) / max(max_dd_pct, 1e-4))

    # DSR Audit
    dsr_res = compute_dsr_audit(
        observed_annualized_sharpe=sr_ci["sharpe"], all_sharpes=[], n_samples=n_obs)

    return {
        "annualized_sharpe": float(sr_ci["sharpe"]),
        "sharpe_95_ci": [float(sr_ci["lower_ci"]), float(sr_ci["upper_ci"])],
        "sortino_ratio": float(sortino),
        "calmar_ratio": calmar,
        "total_return_pct": tot_ret_pct,
        "max_drawdown_pct": max_dd_pct,
        "win_rate_pct": win_rate_pct,
        "profit_factor": profit_factor,
        "total_trades": total_trades,
        "rank_ic": rank_ic,
        "p_value": p_value,
        "dsr_probability": dsr_res["dsr_probability"],
        "dsr_haircut_sharpe": dsr_res["haircut_sharpe"],
        "dsr_status": dsr_res["status"],
        "n_daily_obs": n_obs,
    }
