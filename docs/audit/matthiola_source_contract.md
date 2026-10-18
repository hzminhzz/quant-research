# Matthiola `ml-cross-sectional` — source contract (G0)

**Purpose.** Record the source's executable contract verbatim, so every later gate
can be diffed against something that was read rather than paraphrased. This file
supersedes `research_inbox/crypto_ml_matthiola_xgbranker_20usdt_2026_v1/thesis.yaml`
as the authority for implementation.

**Status of the inbox digest.** The inbox `thesis.yaml` describes this source as a
20-name Binance USDT study. The source says otherwise: the **primary** experiment is
**502 current S&P 500 constituents, 2015-01-02 → 2025-07-30**, and the 20-name
Binance USDT universe is a **robustness appendix in notebook 05**. Any claim that
the crypto panel reproduces "the paper" is wrong; it reproduces one appendix table.

---

## 1. Pinned artifacts

| Object | URL | SHA-256 |
| --- | --- | --- |
| `src/mlcs/features.py` | `raw.githubusercontent.com/matthiola0/ml-cross-sectional/main/src/mlcs/features.py` | `ce0726e50bb7bfb56e7d324964a8de78d76ce779b64df8b8ea85f14462e5a076` |
| `src/mlcs/model.py` | same repo | `21fa8bb8ab3e09bb8818d81b851e2fed4723e932ea64a87425187c1ec0f55a79` |
| `src/mlcs/validation.py` | same repo | `3c9df778c6aa06ec0c5d2323a595526f4c8799408925bd5d2fe3a08e76feb8c6` |
| `scripts/build_features.py` | same repo | `23ec62a87bdeef97d32fd6d002439691a7ce00395e823cad3561e271e0cb7562` |
| `notebooks/05_robustness_tw_btc.ipynb` | same repo | `c71a8c356422520c1af0d54b1c638d081771deb7e70ca76ce1e2543a4718e467` |
| `qtools/backtest/costs.py` | `github.com/matthiola0/qtools` | `bd84da52b9ef77649bcf55b13d3a25e68aa2e3461b2773139f6b018b9d29ef7e` |
| `qtools/backtest/portfolio.py` | same repo | `71b6d2c3375ab68ad3fcc9f32eb095c3a23bba22e8ae7835a0211947fdb1bb8b` |
| `qtools/backtest/engine.py` | same repo | `7683b214c42c93599093e888d6c14584f951ddaf0646af66c412fbca08d81f56` |
| `qtools/metrics/performance.py` | same repo | `fc9d630ac5407f12d350176234016f56b6360c930a8fc3c095c314c9d1f97ac1` |
| `qtools/utils/dates.py` | same repo | `abeec180e64e26e0d74465b7b0fbd6f6b4d191635bae2842590c9cfeb466abd7` |
| `qtools/data/loaders/crypto.py` | same repo | `92477264e2bf179fdf85d3b951396d8015c82481c0fed31f0eaa8e054868fc23` |
| `qtools/data/_util.py` | same repo | `2bfc2698a2f15915a9d7fd67874ef866cbc6f1c7892a3b8e0f1e8fdac0ce8d28` |
| `qtools/data/cache.py` | same repo | `6e2edb0c364e606c267ff6d69347fc6ee49a151cb63569e57d88ef225965d5e5` |

Vendored verbatim at `research_programs/matthiola/upstream/` (imports resolved by a
`sys.path` shim so the bytes are unchanged).

Repo metadata: `matthiola0/ml-cross-sectional`, default branch `main`, MIT, tree
`13ac1736afe802a82a6c1902f650219e9488503f`, `pushed_at 2026-05-10T07:02:54Z`.

---

## 2. Universe and clock (notebook 05, cell 10–11)

```python
BTC_UNIVERSE = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT",
    "DOGE/USDT", "SOL/USDT", "DOT/USDT", "LTC/USDT", "BCH/USDT",
    "LINK/USDT", "AVAX/USDT", "ATOM/USDT", "TRX/USDT", "XLM/USDT",
    "ETC/USDT", "FIL/USDT", "NEAR/USDT", "UNI/USDT", "ALGO/USDT",
]
btc_prices = get_crypto_prices(BTC_UNIVERSE, "2018-01-01", "2025-07-31", interval="1d")
btc_preds  = run_walkforward(btc_work, first_oos=2022, last_oos=2024, label="BTC")
```

- Venue: **Binance spot** via `ccxt`, `exchange="binance"`, `enableRateLimit=True`.
- Bar: **1 day**, `date` = `pd.to_datetime(ms, unit="ms", utc=True).dt.tz_localize(None)`.
- Pagination: `limit=1000`, cursor = last bar ms + 1, stop at `date < end`.
- Delisted pairs drop out silently (the notebook comment says so explicitly).
- OOS: 2022, 2023, 2024 — expanding annual window.

## 3. Features (UPSTREAM `src/mlcs/features.py`, used as `FEATURES` in nb05)

Twelve columns. `low_vol_60` exists in the module but is **excluded from `FEATURES`**
because it is ρ = −0.999 with `vol_60d`.

| Feature | Definition (verbatim) |
| --- | --- |
| `mom_12_1` | `close.shift(21) / close.shift(273) - 1` |
| `reversal_1w` | `-(close / close.shift(5) - 1)` |
| `size_adv_60` | `-(close * volume).rolling(60).mean()` |
| `ret_21d` | `close / close.shift(21) - 1` |
| `ret_63d` | `close / close.shift(63) - 1` |
| `ret_126d` | `close / close.shift(126) - 1` |
| `ret_252d` | `close / close.shift(252) - 1` |
| `vol_20d` | `log(close/close.shift(1)).rolling(20).std()` |
| `vol_60d` | `log(close/close.shift(1)).rolling(60).std()` |
| `rsi_14` | Wilder RSI, `ewm(alpha=1/14, adjust=False, min_periods=14)`, `100 - 100/(1+rs)`, `avg_loss.replace(0, NaN)` |
| `macd_hist` | `EMA12 - EMA26`, minus `EMA9` of that line; all `ewm(span=..., adjust=False)` |
| `volume_z_60` | `(log1p(volume) - rolling(60).mean()) / rolling(60).std()`, std 0 → NaN |

All windows are **daily bars**. There is no hourly variant anywhere in the source.

## 4. Target (UPSTREAM `add_forward_target`, `horizon=21`)

```python
fwd = close.shift(-horizon) / close - 1          # close-to-close, 21 trading days
out[f"fwd_rank_{horizon}d"] = out.groupby("date")[col].rank(pct=True)
```

- Target column: `fwd_rank_21d`, a **per-date percentile rank in (0, 1]**.
- Rows dropped by `feats.dropna(subset=[TARGET])` only — no feature-coverage filter
  in notebook 05 (that filter lives in `scripts/build_features.py` for the equity path).

## 5. Models (notebook 05, cell 3 — note the override)

```python
XGBRankerModel(n_estimators=200, max_depth=4, learning_rate=0.05, random_state=42)
EqualWeightBaseline()
```

The notebook **overrides** `src/mlcs/model.py` defaults (`400` trees, `max_depth=5`)
down to `200` / `4` with the comment *"fewer trees / shallower depth — small
universes overfit fast."* Using the module defaults here would be a silent deviation.

- `XGBRanker`: `objective="rank:pairwise"`, `tree_method="hist"`.
- Labels: `_decile_labels(y, dates, n_bins=10)` — `pd.qcut(y, 10, labels=False)` per date.
- Row filter: `X.notna().sum(axis=1) >= max(1, n_features // 2)` i.e. ≥ 6 of 12.
- Grouping: rows sorted by date (mergesort), contiguous `group` sizes.
- `EqualWeightBaseline(features=("size_adv_60", "vol_60d", "reversal_1w"))`,
  each per-date cross-sectionally z-scored, summed with +1 signs.

## 6. Validation (UPSTREAM `src/mlcs/validation.py`)

Annual expanding window: for OOS year *Y*, train = `year < Y`, test = `year == Y`.

The source states verbatim:

> *"No purging/embargo — with monthly-horizon targets and annual re-fit the
> look-ahead risk is minor, and the gain from purging is dwarfed by the noise
> across folds."*

**Consequence for this mission:** G1 must reproduce the unpurged scheme (that is the
source), while G5 must re-run with purge/embargo (that is the causal requirement).
Reproduction fidelity and causal validity are deliberately separated.

## 7. Costs and portfolio (qtools)

```python
CRYPTO = CostModel(commission_bps=5, slippage_bps=5)     # 10 bps per leg one-way
```

- `CostModel.apply`: `bidir = (commission + slippage)/1e4`; cost = `(buys + sells) * bidir + sells * sell_tax`.
- `signal_to_weights(signal, n_quantiles=5, long_short=True, rebalance="ME")`:
  month-end resample → `rank(axis=1, pct=True, method="first")` → top `> 0.8` equal
  long, bottom `<= 0.2` equal short. Dollar-neutral, gross = 2.
- `BacktestEngine`: weights reindexed to close calendar, `ffill`, **lagged 1 day**;
  `gross = positions * pct_change`; `net = gross - costs`; NaN contributions = 0.

## 8. Reported numbers this gate must reproduce

BTC universe, 2018-01-01 → 2025-07-31, OOS 2022–2024 (README + nb05):

| Model | mean IC | IC-IR | net Sharpe |
| --- | ---: | ---: | ---: |
| `xgb_ranker` | not stated | **+0.18** | **+0.74** |
| `naive_ew` | not stated | **−0.39** | **−0.22** |

For reference, the primary US equity table (nb02/nb04, 2020–2024):

| Model | mean IC | IC-IR | t | net Sharpe | ann net | MDD | turnover |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `xgb_ranker` | 0.037 | 0.20 | 6.9 | 0.87 | 15.4% | −23.9% | 159% |
| `lgbm_ranker` | 0.031 | 0.14 | 5.1 | 0.68 | 13.1% | −28.0% | 159% |
| `naive_ew` | 0.021 | 0.11 | 4.0 | 0.43 | 6.7% | −32.7% | 231% |
| `linear_lasso` | 0.017 | 0.07 | 2.6 | 0.34 | 5.3% | — | — |
| `linear_ridge` | 0.016 | 0.07 | 2.6 | 0.34 | 5.2% | — | — |

Single-feature IC / IC-IR / t (nb01, 2015→2025): `size_adv_60` +0.016/+0.16/8.1;
`vol_60d` +0.029/+0.12/6.2; `vol_20d` +0.025/+0.12/5.9; `reversal_1w` +0.013/+0.08/3.9;
`mom_12_1` −0.002/−0.01/−0.5; `rsi_14` −0.016/−0.10/−5.0.

## 9. Acknowledged source limitations (not mine to fix, but binding on claims)

- Survivorship bias: **current** S&P 500 membership applied to history; README estimates
  +10–20% net-Sharpe inflation.
- No point-in-time index membership.
- Short borrow cost not modelled (GC borrow ~50–100 bps/yr).
- No purge/embargo (source's own deliberate deviation from López de Prado).
- IC-IR and Sharpe are point estimates over ~3 OOS years for the crypto appendix —
  no confidence interval is reported anywhere in the source.
