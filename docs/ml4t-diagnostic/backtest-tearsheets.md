# Backtest Tearsheets & HTML Reports

Generate standalone, interactive Plotly HTML reports from backtest results, normalized trade logs, and return series.

```python
from pathlib import Path
import numpy as np
from ml4t.diagnostic.visualization.backtest import generate_backtest_tearsheet

daily_returns = np.random.normal(0.0005, 0.01, size=252)
metrics = {
    "n_trades": 80,
    "total_pnl": 12_500.0,
    "win_rate": 0.54,
    "profit_factor": 1.6,
    "sharpe_ratio": 1.3,
    "max_drawdown": -0.12,
}

html = generate_backtest_tearsheet(
    metrics=metrics,
    returns=daily_returns,
    template="quant_trader",
    theme="default",
    output_path=Path("tearsheet.html"),
    n_trials=25,
)
```

## Available Templates

| Template | Primary Focus | Best For |
|---|---|---|
| `quant_trader` | Individual trades, PnL attribution, execution slippage | Systematic strategy refinement |
| `hedge_fund` | Risk-adjusted performance, cost analysis, benchmark comparison | Investor and LP reporting |
| `risk_manager` | Tail risk (VaR, CVaR), maximum drawdown, trial corrections | Risk committee qualification |
| `full` | Complete comprehensive report across all sections | Final promotion audits |
