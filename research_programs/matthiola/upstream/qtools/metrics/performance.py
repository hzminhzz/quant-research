import numpy as np
import pandas as pd


def sharpe(returns: pd.Series, periods_per_year: int = 252, rf: float = 0.0) -> float:
    excess = returns - rf / periods_per_year
    if excess.std() == 0:
        return np.nan
    return float(excess.mean() / excess.std() * np.sqrt(periods_per_year))


def sortino(returns: pd.Series, periods_per_year: int = 252, rf: float = 0.0) -> float:
    excess = returns - rf / periods_per_year
    downside = excess[excess < 0]
    if len(downside) == 0 or downside.std() == 0:
        return np.nan
    return float(excess.mean() / downside.std() * np.sqrt(periods_per_year))


def max_drawdown(returns: pd.Series) -> float:
    cum = (1 + returns).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    return float(dd.min())


def calmar(returns: pd.Series, periods_per_year: int = 252) -> float:
    ann_ret = annualized_return(returns, periods_per_year)
    mdd = max_drawdown(returns)
    if mdd == 0:
        return np.nan
    return float(ann_ret / abs(mdd))


def annualized_return(returns: pd.Series, periods_per_year: int = 252) -> float:
    total = (1 + returns).prod()
    n_years = len(returns) / periods_per_year
    if n_years == 0:
        return np.nan
    return float(total ** (1 / n_years) - 1)


def annualized_vol(returns: pd.Series, periods_per_year: int = 252) -> float:
    return float(returns.std() * np.sqrt(periods_per_year))
