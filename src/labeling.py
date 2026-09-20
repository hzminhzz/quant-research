"""Financial Target Labeling Engine & Institutional Meta-Labeling Dataset Builder.

Governed by ML4T Skills:
- ml4t-triple-barrier
- ml4t-meta-labels
- ml4t-purging-embargo

Implements path-dependent labeling techniques following Stefan Jansen's ML4T and
Marcos López de Prado's methodology:
1. Triple-Barrier Method with Dynamic Volatility Scaling (ATR / Opening Range Width)
2. Meta-Labeling (secondary binary classification y^(2) in {0, 1} for primary breakout events)
3. Average Sample Uniqueness Weighting to neutralize concurrency correlation
4. Multi-Horizon Forward Returns for IC Profiling
"""

from dataclasses import dataclass
from datetime import time, timedelta
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import polars as pl

from src.features import extract_breakout_feature_vector


@dataclass
class ORBTradeEvent:
    """Represents a single evaluated breakout event with Triple Barrier outcomes."""
    entry_time: str
    exit_time: str
    date: str
    symbol: str
    direction: int  # +1 (Long), -1 (Short)
    entry_price: float
    exit_price: float
    or_high: float
    or_low: float
    or_range: float
    atr20: float
    delta: float
    upper_barrier: float
    lower_barrier: float
    holding_bars: int
    exit_reason: str  # 'profit_target', 'stop_loss', 'time_expiry'
    label: int  # 1 = hit target (+2R), 0 = hit stop (-1R) or timed out
    realized_return: float
    r_multiple: float
    features: Dict[str, float]


def compute_forward_returns(
    df: pl.DataFrame,
    horizons: List[int] = [1, 4, 8, 16, 32],
    price_col: str = "close",
    group_col: Optional[str] = None,
) -> pl.DataFrame:
    """Compute forward returns across multiple prediction horizons."""
    exprs = []
    for h in horizons:
        expr = pl.col(price_col).pct_change(h).shift(-h)
        if group_col and group_col in df.columns:
            expr = expr.over(group_col)
        exprs.append(expr.alias(f"fwd_ret_{h}"))
    return df.with_columns(exprs)


def triple_barrier_labels(
    df: pl.DataFrame,
    upper_mult: float = 2.0,
    lower_mult: float = 1.0,
    max_holding: int = 16,
    atr_col: str = "atr",
    price_col: str = "close",
) -> pl.DataFrame:
    """Compute basic Triple Barrier Labels across a continuous price series."""
    prices = df[price_col].to_numpy()
    atrs = df[atr_col].to_numpy()
    n = len(prices)

    labels = np.full(n, np.nan)
    holding_bars = np.full(n, np.nan)
    trade_returns = np.full(n, np.nan)

    for i in range(n - max_holding):
        entry_price = prices[i]
        vol = atrs[i]
        if np.isnan(vol) or vol <= 0:
            continue

        upper_barrier = entry_price + (vol * upper_mult)
        lower_barrier = entry_price - (vol * lower_mult)

        hit_label = 0.0
        hit_bar = max_holding
        exit_price = prices[i + max_holding]

        for j in range(1, max_holding + 1):
            curr = prices[i + j]
            if curr >= upper_barrier:
                hit_label = 1.0
                hit_bar = j
                exit_price = curr
                break
            elif curr <= lower_barrier:
                hit_label = -1.0
                hit_bar = j
                exit_price = curr
                break

        labels[i] = hit_label
        holding_bars[i] = hit_bar
        trade_returns[i] = (exit_price - entry_price) / entry_price

    return df.with_columns([
        pl.Series("tb_label", labels),
        pl.Series("tb_holding_bars", holding_bars),
        pl.Series("tb_return", trade_returns),
    ])


def create_meta_labels(
    primary_signal_col: str,
    outcome_return_col: str,
    df: pl.DataFrame,
    profit_threshold: float = 0.0,
) -> pl.DataFrame:
    """Create binary meta-labels (1 = take trade, 0 = pass)."""
    is_signal = pl.col(primary_signal_col) != 0
    is_profitable = pl.col(outcome_return_col) > profit_threshold

    meta_label_expr = (
        pl.when(is_signal & is_profitable)
        .then(1)
        .when(is_signal & ~is_profitable)
        .then(0)
        .otherwise(None)
    )

    return df.with_columns(meta_label_expr.alias("meta_label"))


class MetaLabelingORBDatasetBuilder:
    """Institutional Triple Barrier Dataset Builder tailored for Opening Range Breakouts.

    Operates strictly at candidate breakout timestamps, building event records
    with path-dependent labels and feature snapshots.
    """

    def __init__(
        self,
        target_multiple: float = 2.0,
        stop_multiple: float = 1.0,
        max_holding_bars: int = 24,  # 120 minutes on 5m bars
        stretch_k: float = 0.15,
        friction_bps: float = 4.0,   # 4.0 bps roundtrip
    ):
        self.target_multiple = target_multiple
        self.stop_multiple = stop_multiple
        self.max_holding_bars = max_holding_bars
        self.stretch_k = stretch_k
        self.friction = friction_bps / 10_000.0

    def extract_events_and_labels(
        self,
        df: pl.DataFrame,
        symbol: str,
        session_hours: List[int],
        allow_long: bool = True,
        allow_short: bool = True,
        is_crypto: bool = False,
    ) -> List[ORBTradeEvent]:
        """Extract candidate breakout events and compute exact Triple Barrier meta-labels.

        Input DataFrame must contain:
        ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'date', 'hour', 'atr20_bar', 'ema_200']
        Optional macro columns: ['spx_close', 'spx_vwap']
        """
        dates = df["date"].unique().sort().to_list()
        events: List[ORBTradeEvent] = []

        for d in dates:
            day_df = df.filter(pl.col("date") == d)

            for open_h in session_hours:
                session_df = day_df.filter((pl.col("hour") >= open_h) & (pl.col("hour") < open_h + 6))
                if len(session_df) < 12 + 4:
                    continue

                or_df = session_df.slice(0, 12)
                or_high = or_df["high"].max()
                or_low = or_df["low"].min()
                or_range = or_high - or_low
                atr20 = or_df["atr20_bar"].first()
                ema200 = or_df["ema_200"].last()

                if not or_range or or_range <= 0 or not atr20 or np.isnan(atr20):
                    continue

                # Volatility expansion gate
                if or_range < 1.2 * atr20:
                    continue

                # Dynamic risk unit
                delta = max(or_range, 0.5 * atr20)
                stretch = self.stretch_k * atr20

                rest_df = session_df.slice(12)
                max_bars = min(len(rest_df), 36)
                entry_cutoff = 18  # 90 minutes post-range = 2.5 hours from open

                in_trade = False
                for i in range(max_bars):
                    bar = rest_df[i]
                    c = bar["close"][0]
                    h = bar["high"][0]
                    l = bar["low"][0]
                    t_stamp = str(bar["timestamp"][0])
                    spx_c = bar["spx_close"][0] if "spx_close" in bar.columns else None
                    spx_v = bar["spx_vwap"][0] if "spx_vwap" in bar.columns else None

                    if not in_trade:
                        if i < entry_cutoff:
                            long_sig = allow_long and (c > or_high + stretch) and (ema200 is None or c > ema200)
                            if not is_crypto and spx_c is not None and spx_v is not None and spx_c <= spx_v:
                                long_sig = False

                            short_sig = allow_short and (c < or_low - stretch) and (ema200 is None or c < ema200)
                            if not is_crypto and spx_c is not None and spx_v is not None and spx_c >= spx_v:
                                short_sig = False

                            if long_sig or short_sig:
                                in_trade = True
                                direction = 1 if long_sig else -1
                                entry_price = c
                                entry_time = t_stamp
                                entry_bar_idx = i

                                upper_barrier = entry_price + (direction * self.target_multiple * delta)
                                lower_barrier = entry_price - (direction * self.stop_multiple * delta)

                                # Snapshot features at entry timestamp
                                features_snapshot = self._extract_snapshot_features(
                                    or_df=or_df,
                                    current_bar=bar,
                                    or_high=or_high,
                                    or_low=or_low,
                                    or_range=or_range,
                                    atr20=atr20,
                                    direction=direction,
                                    spx_c=spx_c,
                                    spx_v=spx_v,
                                    is_crypto=is_crypto,
                                )


                    else:
                        # Monitor forward path for barrier hits
                        bars_held = i - entry_bar_idx
                        hit_tp = (h >= upper_barrier) if direction == 1 else (l <= upper_barrier)
                        hit_sl = (l <= lower_barrier) if direction == 1 else (h >= lower_barrier)
                        time_expired = (bars_held >= self.max_holding_bars) or (i == max_bars - 1)

                        if hit_tp or hit_sl or time_expired:
                            if hit_tp and hit_sl:
                                exit_price = lower_barrier
                                exit_reason = "stop_loss"
                                label = 0
                            elif hit_tp:
                                exit_price = upper_barrier
                                exit_reason = "profit_target"
                                label = 1
                            elif hit_sl:
                                exit_price = lower_barrier
                                exit_reason = "stop_loss"
                                label = 0
                            else:
                                exit_price = c
                                exit_reason = "time_expiry"
                            raw_ret = direction * (exit_price - entry_price) / entry_price - self.friction
                            r_mult = raw_ret / (delta / entry_price) if delta > 0 else 0.0

                            # In institutional meta-labeling (López de Prado), label y=1 if trade produced
                            # net positive payoff (target reached or positive session close after costs), 0 otherwise
                            if exit_reason == "profit_target":
                                label = 1
                            elif exit_reason == "stop_loss":
                                label = 0
                            else:
                                label = 1 if r_mult > 0.0 else 0

                            events.append(
                                ORBTradeEvent(
                                    entry_time=entry_time,
                                    exit_time=t_stamp,

                                    date=str(d),
                                    symbol=symbol,
                                    direction=direction,
                                    entry_price=entry_price,
                                    exit_price=exit_price,
                                    or_high=or_high,
                                    or_low=or_low,
                                    or_range=or_range,
                                    atr20=atr20,
                                    delta=delta,
                                    upper_barrier=upper_barrier,
                                    lower_barrier=lower_barrier,
                                    holding_bars=bars_held,
                                    exit_reason=exit_reason,
                                    label=label,
                                    realized_return=raw_ret,
                                    r_multiple=r_mult,
                                    features=features_snapshot,
                                )
                            )
                            break  # 1 trade per session maximum

        return events

    def _extract_snapshot_features(
        self,
        or_df: pl.DataFrame,
        current_bar: pl.DataFrame,
        or_high: float,
        or_low: float,
        or_range: float,
        atr20: float,
        direction: int = 1,
        spx_c: Optional[float] = None,
        spx_v: Optional[float] = None,
        is_crypto: bool = False,
    ) -> Dict[str, float]:
        """Extract stationary, zero-lookahead feature vector at breakout bar close."""
        # Check for optional gk_vol and is_nr7 columns if present in current_bar
        gk_vol = float(current_bar["garman_klass"][0]) if "garman_klass" in current_bar.columns else 0.0
        is_nr7 = bool(current_bar["nr7"][0]) if "nr7" in current_bar.columns else False
        base_vol = float(current_bar["avg_1h_volume"][0]) if "avg_1h_volume" in current_bar.columns else 1.0

        return extract_breakout_feature_vector(
            or_df=or_df,
            current_bar=current_bar,
            or_high=or_high,
            or_low=or_low,
            or_range=or_range,
            atr20=atr20,
            direction=direction,
            baseline_volume_1h=base_vol,
            gk_vol=gk_vol,
            is_nr7=is_nr7,
            spx_c=spx_c,
            spx_v=spx_v,
            is_crypto=is_crypto,
        )



def compute_sample_uniqueness_weights(
    events: List[ORBTradeEvent],
    all_timestamps: List[str],
) -> np.ndarray:
    """Calculate average sample uniqueness weights (López de Prado) for training events."""
    if not events:
        return np.array([])

    n_events = len(events)
    time_to_idx = {t: idx for idx, t in enumerate(all_timestamps)}
    n_bars = len(all_timestamps)

    concurrency = np.zeros(n_bars, dtype=np.int32)
    spans = []

    for e in events:
        s_idx = time_to_idx.get(e.entry_time)
        e_idx = time_to_idx.get(e.exit_time)
        if s_idx is not None and e_idx is not None and e_idx >= s_idx:
            concurrency[s_idx : e_idx + 1] += 1
            spans.append((s_idx, e_idx))
        else:
            spans.append((-1, -1))

    uniqueness_weights = np.zeros(n_events, dtype=np.float64)
    returns = np.array([abs(e.realized_return) for e in events])

    for i, (s_idx, e_idx) in enumerate(spans):
        if s_idx == -1:
            uniqueness_weights[i] = 1.0
        else:
            conc_slice = concurrency[s_idx : e_idx + 1]
            u_t = 1.0 / np.maximum(conc_slice, 1)
            uniqueness_weights[i] = float(np.mean(u_t))

    # Compound uniqueness with return magnitude
    raw_w = uniqueness_weights * np.maximum(returns, 0.001)
    norm_w = raw_w / np.mean(raw_w) if np.mean(raw_w) > 0 else np.ones(n_events)
    return norm_w
