"""Experiment Tracking & Statistical Trial Ledger.

Records parameter evaluations to prevent backtest overfitting and computes
the Deflated Sharpe Ratio (DSR) and Bailey & López de Prado Sharpe Haircut
across all recorded trials.
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional
import json
import numpy as np
from scipy import stats


DEFAULT_LEDGER_PATH = Path("run_log/trials.jsonl")


@dataclass
class TrialRecord:
    """Individual backtest trial entry."""
    trial_id: str
    strategy_name: str
    symbol: str
    timeframe: str
    parameters: Dict[str, Any]
    total_return_pct: float
    annualized_sharpe: float
    max_drawdown_pct: float
    win_rate_pct: float
    total_trades: int
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


def log_trial(trial: TrialRecord, ledger_path: Path = DEFAULT_LEDGER_PATH) -> None:
    """Append a trial record to the experiment ledger."""
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with open(ledger_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(trial)) + "\n")


def load_trials(ledger_path: Path = DEFAULT_LEDGER_PATH) -> List[Dict[str, Any]]:
    """Load all historical trial records from the ledger."""
    if not ledger_path.exists():
        return []
    records = []
    with open(ledger_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def compute_deflated_sharpe(
    observed_annualized_sharpe: float,
    all_sharpes: List[float],
    n_obs_days: int = 252 * 5,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> Dict[str, float]:
    """Compute Deflated Sharpe Ratio (DSR) and Sharpe Haircut.

    Implements Bailey & López de Prado (2014) multiple-testing correction.
    """
    n_trials = max(len(all_sharpes), 1)
    if n_trials <= 1:
        return {
            "n_trials": 1,
            "observed_sharpe": observed_annualized_sharpe,
            "haircut_sharpe": observed_annualized_sharpe,
            "expected_max_null": 0.0,
            "dsr_probability": 1.0 if observed_annualized_sharpe > 0 else 0.0,
        }

    # Standard deviation of trials
    sr_std = float(np.std(all_sharpes)) if np.std(all_sharpes) > 0 else 0.1

    # Euler-Mascheroni constant approximation for expected max under null
    euler = 0.5772156649
    expected_max = sr_std * (
        (1 - euler) * stats.norm.ppf(1 - 1 / n_trials)
        + euler * stats.norm.ppf(1 - 1 / (n_trials * np.e))
    )

    haircut_sharpe = observed_annualized_sharpe - expected_max

    # Per-period Sharpe standard error
    observed_daily_sr = observed_annualized_sharpe / np.sqrt(252)
    expected_daily_max = expected_max / np.sqrt(252)
    
    sr_se = np.sqrt(
        (1 - skew * observed_daily_sr + ((kurtosis - 1) / 4) * (observed_daily_sr**2))
        / max(n_obs_days - 1, 1)
    )

    test_stat = (observed_daily_sr - expected_daily_max) / (sr_se + 1e-12)
    dsr_prob = float(stats.norm.cdf(test_stat))

    return {
        "n_trials": n_trials,
        "observed_sharpe": float(observed_annualized_sharpe),
        "haircut_sharpe": float(haircut_sharpe),
        "expected_max_null": float(expected_max),
        "dsr_probability": float(dsr_prob),
    }
