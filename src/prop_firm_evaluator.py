"""Prop Firm Challenge Evaluator (ML4T Institutional Standard).

Decoupled architecture:
1. `prepare_dual_timeframe_pit`: Point-in-time higher-timeframe signals with strict zero lookahead.
2. `PropFirmConfig`: Typed configuration for challenge rules, horizons, and retail execution costs.
3. `PropFirmChallengeWrapper`: Strategy adapter that wraps ANY user Strategy and enforces challenge limits.
4. `PropFirmEvaluator`:
   - Enforces Fixed-Horizon Competing-Risk evaluation (strictly slices feeds to [start, start + H]).
   - Rejects start dates lacking a full H-day runway to eliminate right-censoring bias.
   - Computes verified Newey-West HAC standard errors via `statsmodels` with lags derived from H / step.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import Any, Callable, Dict, List, Optional
import numpy as np
import polars as pl
import statsmodels.api as sm

from ml4t.backtest import Strategy, Engine, DataFeed, BacktestConfig
from ml4t.backtest.config import ShareType, CommissionType, SlippageType


@dataclass
class PropFirmConfig:
    """Challenge evaluation rules and cost parameters."""
    initial_balance: float = 10000.0
    target_pct: float = 0.15              # +15.0% profit target
    static_floor_pct: float = 0.10        # -10.0% static max loss floor from initial balance
    daily_loss_pct: float = 0.05          # -5.0% daily loss limit from midnight balance
    watchdog_flatten_pct: float = 0.025   # Watchdog intraday flatten trigger
    max_evaluation_days: int = 60         # Fixed competing-risk horizon (calendar days)
    challenge_fee_usd: float = 100.0      # Purchase fee for the evaluation account
    commission_bps: float = 10.0          # Retail taker commission (bps per leg)
    slippage_bps: float = 5.0             # Retail spread/slippage (bps per leg)


def prepare_dual_timeframe_pit(
    df_1m: pl.DataFrame,
    symbol_col: str = "symbol",
    timestamp_col: str = "timestamp",
    close_col: str = "close",
    ema_span: int = 120,
    roc_lookback: int = 168,
) -> pl.DataFrame:
    """Prepares 1-minute data with higher-timeframe signals joined at strict point-in-time boundaries.

    Invariant: The 1-hour candle spanning [T, T+1h) closes at T+59m and its signal is only
    available starting at T+1h (offset by +1 hour). Mutating prices inside [T, T+1h) cannot
    change signals observed at or before T.
    """
    dfs_by_sym = []
    unique_symbols = df_1m[symbol_col].unique().to_list()

    for sym in unique_symbols:
        df_sym = df_1m.filter(pl.col(symbol_col) == sym).sort(timestamp_col)

        # 1. Aggregate to true completed 1-hour candles
        df_1h = (
            df_sym.group_by_dynamic(timestamp_col, every="1h")
            .agg([
                pl.col("open").first(),
                pl.col("high").max(),
                pl.col("low").min(),
                pl.col(close_col).last(),
                pl.col("volume").sum(),
            ])
            .sort(timestamp_col)
            .with_columns([
                pl.col(close_col).ewm_mean(span=ema_span).alias("ema_120h"),
                ((pl.col(close_col) - pl.col(close_col).shift(roc_lookback)) / pl.col(close_col).shift(roc_lookback)).alias("roc_168h"),
            ])
            # Completed candle for [T, T+1h) is available strictly at T+1h
            .with_columns(
                pl.col(timestamp_col).dt.offset_by("1h").alias("available_at")
            )
        )

        # 2. Minute data joins on the hour it belongs to
        df_sym = df_sym.with_columns(
            pl.col(timestamp_col).dt.truncate("1h").alias("current_hour"),
            (pl.col(timestamp_col).dt.minute() == 0).cast(pl.Int8).alias("is_hour_close"),
        )

        # 3. Strict point-in-time join
        df_pit = df_sym.join(
            df_1h.select(["available_at", "ema_120h", "roc_168h"]),
            left_on="current_hour",
            right_on="available_at",
            how="left",
        ).drop("current_hour")

        dfs_by_sym.append(df_pit)

    return pl.concat(dfs_by_sym).sort([timestamp_col, symbol_col])


class PropFirmChallengeWrapper(Strategy):
    """Generic Strategy Adapter that wraps ANY user Strategy and enforces challenge limits."""
    def __init__(
        self,
        inner_strategy: Strategy,
        config: PropFirmConfig,
        start_datetime: Optional[datetime] = None,
    ):
        super().__init__()
        self.inner_strategy = inner_strategy
        self.config = config
        self.start_datetime = start_datetime

        self.target_equity = config.initial_balance * (1.0 + config.target_pct)
        self.floor_equity = config.initial_balance * (1.0 - config.static_floor_pct)

        self.current_date = None
        self.day_start_equity = config.initial_balance
        self.circuit_breaker_active = False

        self.outcome = "TIME_EXPIRED"
        self.end_timestamp = None
        self.final_equity = config.initial_balance
        self.lowest_equity = config.initial_balance
        self.worst_daily_dd = 0.0

    def on_start(self, broker: Any) -> None:
        if hasattr(self.inner_strategy, "on_start"):
            self.inner_strategy.on_start(broker)

    def on_prepare(self, broker: Any, config: Any | None = None) -> None:
        if hasattr(self.inner_strategy, "on_prepare"):
            self.inner_strategy.on_prepare(broker, config=config)

    def on_end(self, broker: Any) -> None:
        if hasattr(self.inner_strategy, "on_end"):
            self.inner_strategy.on_end(broker)

    def on_data(self, timestamp: datetime, data: Dict[str, Dict[str, Any]], context: Dict[str, Any], broker: Any) -> None:
        bar_date = timestamp.strftime("%Y-%m-%d")
        equity = float(broker.equity())

        if equity < self.lowest_equity:
            self.lowest_equity = equity

        # Midnight rollover check
        if self.current_date != bar_date:
            self.current_date = bar_date
            self.day_start_equity = equity
            self.circuit_breaker_active = False

        floating_daily_dd = (equity - self.day_start_equity) / self.day_start_equity
        if floating_daily_dd < self.worst_daily_dd:
            self.worst_daily_dd = floating_daily_dd

        # --- ABSORBING BOUNDARIES ---
        # 1. Target Reached (+15%)
        if equity >= self.target_equity:
            self.outcome = "PASSED"
            self.end_timestamp = timestamp
            self.final_equity = equity
            raise StopIteration("Target reached")

        # 2. Daily Loss Breached (-5%)
        if floating_daily_dd <= -self.config.daily_loss_pct:
            self.outcome = "BREACHED_DAILY"
            self.end_timestamp = timestamp
            self.final_equity = equity
            raise StopIteration("Daily limit breached")

        # 3. Static Max Loss Floor Breached (-10%)
        if equity <= self.floor_equity:
            self.outcome = "BREACHED_STATIC_FLOOR"
            self.end_timestamp = timestamp
            self.final_equity = equity
            raise StopIteration("Static floor breached")

        # 4. Fixed-Horizon Expiration Check (Competing Risk at H days)
        if self.start_datetime is not None:
            days_elapsed = (timestamp - self.start_datetime).total_seconds() / 86400.0
            if days_elapsed >= self.config.max_evaluation_days:
                self.outcome = "TIME_EXPIRED"
                self.end_timestamp = timestamp
                self.final_equity = equity
                raise StopIteration("Fixed horizon reached")

        # --- INTRADAY WATCHDOG ---
        if not self.circuit_breaker_active and floating_daily_dd <= -self.config.watchdog_flatten_pct:
            self.circuit_breaker_active = True
            for sym in data.keys():
                pos = broker.get_position(sym)
                if pos is not None and pos.quantity != 0:
                    broker.order_target_percent(sym, 0.0)
            return

        if self.circuit_breaker_active:
            for sym in data.keys():
                pos = broker.get_position(sym)
                if pos is not None and pos.quantity != 0:
                    broker.order_target_percent(sym, 0.0)
            return

        # Delegate execution callback to the inner strategy
        self.inner_strategy.on_data(timestamp, data, context, broker)


class PropFirmEvaluator:
    """Evaluates challenge pass rates for any strategy factory across fixed-horizon cohorts."""
    def __init__(
        self,
        prices_df: pl.DataFrame,
        signals_df: pl.DataFrame,
        strategy_factory: Callable[[], Strategy],
        config: Optional[PropFirmConfig] = None,
    ):
        self.prices_df = prices_df.sort("timestamp")
        self.signals_df = signals_df.sort("timestamp")
        self.strategy_factory = strategy_factory
        self.config = config or PropFirmConfig()

        # Precompute timestamp arrays for fast binary search slicing
        self._price_timestamps = self.prices_df["timestamp"].to_numpy()
        self._signal_timestamps = self.signals_df["timestamp"].to_numpy()
        self.max_dataset_timestamp = self.prices_df["timestamp"][-1]

    def generate_fixed_horizon_start_dates(
        self,
        interval_days: int = 14,
    ) -> List[datetime]:
        """Generates cohort start dates strictly bounded by t <= max_date - max_evaluation_days."""
        max_start = self.max_dataset_timestamp - timedelta(days=self.config.max_evaluation_days)
        min_start = self.prices_df["timestamp"][0]

        start_dates = []
        curr = min_start
        while curr <= max_start:
            start_dates.append(curr)
            curr += timedelta(days=interval_days)

        return start_dates

    def run_cohorts(
        self,
        cohort_start_dates: List[datetime],
    ) -> Dict[str, Any]:
        """Runs fresh-account trials with strict [start, start + H] feed bounds and verified HAC SE."""
        # 1. Input Runway Validation: reject dates lacking a full H-day evaluation window
        max_valid_start = self.max_dataset_timestamp - timedelta(days=self.config.max_evaluation_days)
        for s_date in cohort_start_dates:
            if s_date > max_valid_start:
                raise ValueError(
                    f"Cohort start date {s_date} does not have a full {self.config.max_evaluation_days}-day "
                    f"evaluation window before dataset end ({self.max_dataset_timestamp}). "
                    f"Latest allowable start date is {max_valid_start}."
                )

        outcomes = {"PASSED": 0, "BREACHED_STATIC_FLOOR": 0, "BREACHED_DAILY": 0, "TIME_EXPIRED": 0}
        days_to_pass = []
        cohort_records = []
        binary_passed = []

        cfg = BacktestConfig(
            initial_cash=self.config.initial_balance,
            allow_short_selling=True,
            share_type=ShareType.FRACTIONAL,
            commission_type=CommissionType.PERCENTAGE,
            commission_rate=self.config.commission_bps / 10000.0,
            slippage_type=SlippageType.PERCENTAGE,
            slippage_rate=self.config.slippage_bps / 10000.0,
        )

        for s_date in cohort_start_dates:
            e_date = s_date + timedelta(days=self.config.max_evaluation_days)

            unit = "us" if "us" in str(self._price_timestamps.dtype) else "ns"
            dt_s_clean = s_date if s_date.tzinfo is None else s_date.astimezone(timezone.utc).replace(tzinfo=None)
            dt_e_clean = e_date if e_date.tzinfo is None else e_date.astimezone(timezone.utc).replace(tzinfo=None)

            s_date_np = np.datetime64(dt_s_clean, unit)
            e_date_np = np.datetime64(dt_e_clean, unit)

            # Strict bounds: slice [start, start + H] so feed strictly terminates at H
            p_start_idx = int(np.searchsorted(self._price_timestamps, s_date_np, side="left"))
            p_end_idx = int(np.searchsorted(self._price_timestamps, e_date_np, side="right"))

            s_start_idx = int(np.searchsorted(self._signal_timestamps, s_date_np, side="left"))
            s_end_idx = int(np.searchsorted(self._signal_timestamps, e_date_np, side="right"))

            p_sub = self.prices_df.slice(p_start_idx, p_end_idx - p_start_idx)
            s_sub = self.signals_df.slice(s_start_idx, s_end_idx - s_start_idx)

            inner_strat = self.strategy_factory()
            wrapper = PropFirmChallengeWrapper(inner_strategy=inner_strat, config=self.config, start_datetime=s_date)

            try:
                Engine(DataFeed(prices_df=p_sub, signals_df=s_sub), wrapper, cfg).run()
                outcome = wrapper.outcome
            except StopIteration:
                outcome = wrapper.outcome

            outcomes[outcome] = outcomes.get(outcome, 0) + 1
            is_pass = outcome == "PASSED"
            binary_passed.append(1.0 if is_pass else 0.0)

            end_t = wrapper.end_timestamp or e_date
            d_taken = (end_t - s_date).total_seconds() / 86400.0 if wrapper.end_timestamp else self.config.max_evaluation_days
            if is_pass and d_taken:
                days_to_pass.append(d_taken)

            cohort_records.append({
                "start_date": s_date.strftime("%Y-%m-%d"),
                "end_date": end_t.strftime("%Y-%m-%d") if isinstance(end_t, datetime) else str(end_t)[:10],
                "outcome": outcome,
                "days_taken": round(d_taken, 1),
                "lowest_equity": round(wrapper.lowest_equity, 2),
                "final_equity": round(wrapper.final_equity, 2),
            })

        total_cohorts = len(cohort_start_dates)
        completed_cohorts = total_cohorts  # All validated cohorts complete full H horizon
        p_hat = outcomes["PASSED"] / total_cohorts if total_cohorts > 0 else 0.0

        # Naive i.i.d. standard error
        naive_se = np.sqrt(p_hat * (1.0 - p_hat) / total_cohorts) * 100.0 if total_cohorts > 0 else 0.0

        # Verified Newey-West HAC Standard Error via statsmodels.api.OLS
        hac_se = naive_se
        max_overlap_lags = 1
        if total_cohorts >= 4:
            y = np.array(binary_passed)
            X = np.ones((total_cohorts, 1))

            # Calculate lag parameter based on fixed horizon H / step interval
            if len(cohort_start_dates) > 1:
                step_days = max(1.0, (cohort_start_dates[-1] - cohort_start_dates[0]).total_seconds() / 86400.0 / (total_cohorts - 1))
                max_overlap_lags = max(1, int(math.ceil(self.config.max_evaluation_days / step_days)))
                max_overlap_lags = min(max_overlap_lags, total_cohorts // 2)

            ols_fit = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": max_overlap_lags})
            hac_se = float(ols_fit.bse[0]) * 100.0

        cost_per_pass = (total_cohorts * self.config.challenge_fee_usd) / outcomes["PASSED"] if outcomes["PASSED"] > 0 else float("inf")

        return {
            "total_cohorts": total_cohorts,
            "completed_cohorts": completed_cohorts,
            "outcomes": outcomes,
            "pass_rate_pct": round(p_hat * 100.0, 2),
            "naive_se_pct": round(naive_se, 2),
            "hac_adjusted_se_pct": round(hac_se, 2),
            "hac_max_lags": max_overlap_lags,
            "hac_ci_95": [round(max(0.0, p_hat * 100.0 - 1.96 * hac_se), 2), round(min(100.0, p_hat * 100.0 + 1.96 * hac_se), 2)],
            "avg_days_to_pass": round(float(np.mean(days_to_pass)), 1) if days_to_pass else None,
            "median_days_to_pass": round(float(np.median(days_to_pass)), 1) if days_to_pass else None,
            "cost_per_pass_usd": round(cost_per_pass, 2) if cost_per_pass != float("inf") else None,
            "cohort_records": cohort_records,
        }
