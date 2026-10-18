from dataclasses import dataclass

import pandas as pd

from qtools.backtest.costs import CostModel


@dataclass
class BacktestResult:
    returns: pd.Series           # daily strategy returns, net of costs
    gross_returns: pd.Series     # daily returns before costs
    weights: pd.DataFrame        # daily held weights (after forward-fill)
    turnover: pd.Series          # one-way turnover per date, Σ|Δw|/2
    costs: pd.Series             # per-day cost drag


class BacktestEngine:
    """Vectorized long-only or long-short backtest.

    Assumes weights are applied at close of day t and earn t+1's return
    (standard lagged convention — no look-ahead).

    Missing-data policy: for any (date, symbol) with no return (e.g. the
    symbol has no price yet, delisted, or the calendar union has gaps),
    that asset's contribution is treated as zero for the day. This matches
    pandas' default ``DataFrame.sum(skipna=True)`` behavior but is applied
    here explicitly. Set ``strict_returns=True`` on ``run`` to raise when a
    non-zero position meets a NaN return — useful for catching data holes
    early.
    """

    def __init__(
        self,
        prices: pd.DataFrame,
        cost_model: CostModel | None = None,
    ) -> None:
        if not {"date", "symbol", "close"}.issubset(prices.columns):
            raise ValueError("prices must have columns: date, symbol, close")

        self._close = (
            prices.pivot(index="date", columns="symbol", values="close")
            .sort_index()
        )
        self._returns = self._close.pct_change()
        self.cost_model = cost_model or CostModel()

    def run(self, weights: pd.DataFrame, strict_returns: bool = False) -> BacktestResult:
        """Run the backtest.

        weights: date × symbol DataFrame. Can be sparse (only at rebalance
        dates) — will be forward-filled to daily. Missing symbols treated
        as zero weight.

        strict_returns: when True, raise if any non-zero lagged position
        lands on a NaN return. Default False keeps the permissive behavior
        documented on the class.
        """
        aligned = (
            weights.reindex(columns=self._close.columns, fill_value=0.0)
            .reindex(self._close.index)
            .ffill()
            .fillna(0.0)
        )

        # Lag weights by 1 day: today's position comes from yesterday's close
        positions = aligned.shift(1).fillna(0.0)

        if strict_returns:
            bad = (positions != 0) & self._returns.isna()
            if bad.any().any():
                first = bad.stack()[lambda s: s].index[0]
                raise ValueError(
                    f"Non-zero position on NaN return at {first}. "
                    "Clean the input prices or set strict_returns=False."
                )

        # fillna(0.0) makes the zero-contribution policy explicit (no
        # reliance on skipna semantics in sum).
        gross_daily = (positions * self._returns).fillna(0.0).sum(axis=1)

        costs = self.cost_model.apply(aligned)

        # One-way turnover (Σ|Δw|/2) matches qtools.metrics.factor.turnover.
        # Two-way is what the cost model consumes internally via buys+sells.
        turnover = aligned.diff().abs().sum(axis=1) / 2
        if len(aligned) > 0:
            turnover.iloc[0] = aligned.iloc[0].abs().sum() / 2

        net_daily = gross_daily.sub(costs, fill_value=0.0)

        return BacktestResult(
            returns=net_daily.fillna(0.0),
            gross_returns=gross_daily.fillna(0.0),
            weights=aligned,
            turnover=turnover,
            costs=costs,
        )
