"""Run comprehensive 10-year (2017-2026) backtest of the institutional Multi-Day EOW Meta-Gated ORB Strategy."""

import polars as pl
import talib
import numpy as np
from scipy import stats
import warnings
warnings.filterwarnings('ignore')

from src.labeling import MetaLabelingORBDatasetBuilder, compute_sample_uniqueness_weights
from src.models import train_meta_classifier_cpcv
from src.ftmo_simulator import FTMOSimulator, FTMOConfig

assets = [
    ('JP225', 'data/processed/JP225_USD_5m_2017_2026.parquet', [0], False),
    ('HK33', 'data/processed/HK33_5m_2017_2026.parquet', [1], False),
    ('DE30', 'data/processed/DE30_EUR_5m_2017_2026.parquet', [13], False),
    ('NAS100', 'data/processed/NAS100_5m_2017_2026.parquet', [14], False),
]

spx_p = 'data/processed/SPX500_USD_15m_2017_2026.parquet'
df_spx = pl.read_parquet(spx_p).sort('timestamp')
df_spx = df_spx.with_columns([
    pl.col('timestamp').dt.date().alias('date'),
    ((pl.col('high') + pl.col('low') + pl.col('close')) / 3.0).alias('tp'),
    pl.when(pl.col('volume') > 0).then(pl.col('volume')).otherwise(1.0).alias('eff_vol'),
]).with_columns([
    (pl.col('tp') * pl.col('eff_vol')).alias('pv')
]).with_columns([
    (pl.col('pv').cum_sum().over('date') / pl.col('eff_vol').cum_sum().over('date')).alias('spx_vwap')
]).select(['timestamp', pl.col('close').alias('spx_close'), 'spx_vwap'])

dfs = {}
for sym, path, s_hours, is_crypto in assets:
    print(f"Loading {sym} from {path}...")
    df = pl.read_parquet(path).sort('timestamp')
    df = df.filter(
        (pl.col('timestamp') >= pl.lit('2017-01-01').str.to_datetime())
        & (pl.col('timestamp') <= pl.lit('2026-07-31').str.to_datetime())
    )
    df = df.join_asof(df_spx, on='timestamp', strategy='backward')
    df_1h = df.group_by_dynamic('timestamp', every='1h').agg([
        pl.col('open').first(), pl.col('high').max(), pl.col('low').min(), pl.col('close').last()
    ]).drop_nulls()
    atr_1h = talib.ATR(df_1h['high'].to_numpy(), df_1h['low'].to_numpy(), df_1h['close'].to_numpy(), timeperiod=20)
    df_1h = df_1h.with_columns(pl.Series('atr20_bar', atr_1h).shift(1))
    df = df.join_asof(df_1h.select(['timestamp', 'atr20_bar']), on='timestamp', strategy='backward')
    df = df.with_columns([
        pl.col('timestamp').dt.date().alias('date'),
        pl.col('timestamp').dt.hour().alias('hour'),
        pl.col('timestamp').dt.year().alias('year'),
        pl.col('timestamp').dt.weekday().alias('weekday'),
        pl.col('close').ewm_mean(span=200).alias('ema_200'),
    ])
    dfs[sym] = (df, s_hours, is_crypto)

builder = MetaLabelingORBDatasetBuilder(
    target_multiple=3.0,
    holding_mode='multi_day_eow',
    enable_breakeven=True,
    enable_trailing_stop=True,
    trailing_distance_r=1.0,
    stretch_k=0.15,
)

print("\nExtracting Multi-Day EOW breakout events across 2017-2026...")
evs = []
all_ts = []
for sym, (df, s_hours, is_crypto) in dfs.items():
    sub_evs = builder.extract_events_and_labels(df, symbol=sym, session_hours=s_hours, is_crypto=is_crypto)
    evs.extend(sub_evs)
    all_ts.extend(df['timestamp'].cast(pl.String).to_list())
    print(f"  {sym}: {len(sub_evs)} events extracted")

print(f"\nTotal 10-Year Evaluated Events: {len(evs)}")

weights = compute_sample_uniqueness_weights(evs, sorted(list(set(all_ts))))
print(f"Sample uniqueness weights computed (mean: {np.mean(weights):.4f})")

print("\nTraining CPCV Meta-Classifier (6 groups, 15 folds, 5-bar embargo)...")
res = train_meta_classifier_cpcv(evs, sample_weights=weights, conviction_threshold=0.50, random_state=42)
print(f"CPCV Model Trained. Mean OOF AUC: {res.mean_auc:.4f}, Brier Score: {res.brier_score:.4f}")

# Build trade records
trades_all = []
for i, e in enumerate(evs):
    p_hat = float(res.oof_probabilities[i])
    trades_all.append({
        'date': str(e.date),
        'year': int(str(e.date)[:4]),
        'entry_time': str(e.entry_time),
        'exit_time': str(e.exit_time),
        'r_mult': e.r_multiple,
        'pnl_pct': e.r_multiple * 0.01,
        'prob': p_hat,
        'symbol': e.symbol,
    })

df_all = pl.DataFrame(trades_all)

# Compare Unfiltered vs Meta-Gated (p >= 0.50)
print("\n=======================================================")
print("=== 10-YEAR (2017-2026) FULL PORTFOLIO PERFORMANCE ===")
print("=======================================================")

for name, p_cut in [("Unfiltered Multi-Day EOW", 0.0), ("Meta-Gated Multi-Day EOW (p >= 0.50)", 0.50)]:
    sub = df_all.filter(pl.col('prob') >= p_cut) if p_cut > 0.0 else df_all
    rets = sub['r_mult'].to_numpy()
    wr = np.mean(rets > 0) * 100
    net_r = np.sum(rets)
    t_sr = np.mean(rets) / (np.std(rets) + 1e-12)
    # Approx 2400 trading days over 9.5 years (~250 trades/yr)
    ann_sr = t_sr * np.sqrt(len(rets) / 9.5)
    
    # Daily returns for DSR
    daily_pnl = sub.group_by('date').agg(pl.col('pnl_pct').sum()).sort('date')
    daily_rets = np.zeros(2400)
    p_vals = daily_pnl['pnl_pct'].to_numpy()
    daily_rets[:len(p_vals)] = p_vals
    d_sr = np.mean(daily_rets) / (np.std(daily_rets) + 1e-12)
    d_ann_sr = d_sr * np.sqrt(252)
    sk = float(stats.skew(daily_rets))
    kt = float(stats.kurtosis(daily_rets, fisher=False))
    
    # DSR calculation (N=42 trials)
    em = 0.5772156649
    n_trials = 42
    sr_std = 0.35 / np.sqrt(252)
    e_max = sr_std * ((1 - em) * stats.norm.ppf(1 - 1.0 / n_trials) + em * stats.norm.ppf(1 - 1.0 / (n_trials * np.e)))
    sr_se = np.sqrt((1 - sk * d_sr + (kt - 1) / 4.0 * d_sr**2) / 2399)
    dsr = stats.norm.cdf((d_sr - e_max) / sr_se)
    haircut_sr = (d_sr - e_max) * np.sqrt(252)
    
    print(f"\n{name}:")
    print(f"  Total Trades:     {len(rets):,} (Avg {len(rets)/9.5:.1f} trades/year)")
    print(f"  Win Rate:         {wr:.1f}%")
    print(f"  Net Realized R:   {net_r:+.1f}R")
    print(f"  Trade Sharpe:     {t_sr:.4f}")
    print(f"  Annualized Sharpe:{d_ann_sr:.2f}")
    print(f"  Haircut Sharpe:   {haircut_sr:+.2f} (Penalized for {n_trials} trials)")
    print(f"  DSR Probability:  {dsr:.4f} ({dsr*100:.1f}%)")
    print(f"  Skew / Kurtosis:  {sk:+.2f} / {kt:.1f}")

# Annual breakdown for Meta-Gated (p >= 0.50)
print("\n=======================================================")
print("=== CALENDAR YEAR BREAKDOWN (META-GATED p >= 0.50) ===")
print("=======================================================")
sub_gated = df_all.filter(pl.col('prob') >= 0.50)
years = sorted(sub_gated['year'].unique().to_list())
for yr in years:
    df_yr = sub_gated.filter(pl.col('year') == yr)
    y_rets = df_yr['r_mult'].to_numpy()
    y_wr = np.mean(y_rets > 0) * 100
    y_net = np.sum(y_rets)
    y_sr = (np.mean(y_rets) / (np.std(y_rets) + 1e-12)) * np.sqrt(len(y_rets))
    print(f"  {yr}: Trades: {len(y_rets):3d} | WinRate: {y_wr:5.1f}% | Net R: {y_net:+6.1f}R | Ann Sharpe: {y_sr:+5.2f}")

# Run 2,000-trial FTMO Monte Carlo
print("\n=======================================================")
print("=== 10-YEAR 2,000-TRIAL MONTE CARLO FTMO EVALUATION ===")
print("=======================================================")
sim = FTMOSimulator(trades=trades_all)
mc_unfiltered = sim.run_monte_carlo(n_simulations=2000, risk_pct=1.0, prob_threshold=None, random_seed=42)
mc_gated = sim.run_monte_carlo(n_simulations=2000, risk_pct=1.0, prob_threshold=0.50, random_seed=42)

def print_mc(name, mc):
    print(f"\n{name}:")
    print(f"  Step 1 Pass Rate:           {mc['step1_pass_rate_pct']:.1f}%")
    print(f"  Step 2 Conditional Rate:    {mc['step2_conditional_pass_rate_pct']:.1f}%")
    print(f"  Complete 2-Step Pass Rate:  {mc['overall_two_step_pass_rate_pct']:.1f}%")
    print(f"  Max Drawdown Breach Risk:   {mc['max_loss_breach_rate_pct']:.1f}%")
    print(f"  Daily Loss Breach Risk:     {mc['daily_loss_breach_rate_pct']:.1f}%")
    print(f"  Median Total Days to Pass:  {mc['median_total_days_to_funded']:.0f} days")
    print(f"  Expected Funded Payout:     ${mc['expected_payout_per_challenge']:,.0f}")
    print(f"  ROI on Challenge Fee:       {mc['expected_roi_on_fee_pct']:+.1f}%")

print_mc("Option A: 10-Year Multi-Day EOW (Unfiltered)", mc_unfiltered)
print_mc("Option B: 10-Year Multi-Day EOW (Meta-Gated p >= 0.50)", mc_gated)
