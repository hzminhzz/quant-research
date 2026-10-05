from __future__ import annotations

import hashlib
import json
import math
import warnings
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
from ml4t.data.storage import create_storage
from statsmodels.tsa.stattools import adfuller, kpss

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "run_log" / "btc_eth_relative_value" / "btc-eth-relative-value-20261004"
DATA_OUT = ROOT / "data" / "research_sessions" / "btc_eth_relative_value"
STORE_ROOT = Path("/home/quant/dev/quant/ml4t-data/.data/store")
PRICE_DATASET = "crypto_futures_ohlcv_1h_BINANCE_UM_PERP"
FUNDING_KEYS = {s: f"crypto/futures/funding/{s}_PERP" for s in ("BTCUSDT", "ETHUSDT")}
SYMBOLS = ("BTCUSDT", "ETHUSDT")
DEV_START = pd.Timestamp("2021-01-01T00:00:00Z")
DEV_END = pd.Timestamp("2026-01-01T00:00:00Z")
HOLD_START = pd.Timestamp("2026-01-01T00:00:00Z")
HOLD_END = pd.Timestamp("2026-10-01T00:00:00Z")
DATA_START = pd.Timestamp("2020-09-01T00:00:00Z")
DATA_END = HOLD_END
MAX_FUNDING_INTERVAL = pd.Timedelta(hours=8)
BASE_BPS = 5.0
RNG_SEED = 20261004


@dataclass(frozen=True)
class Params:
    stage: str = "P0"
    formation_days: int = 90
    entry_abs_z: float = 2.0
    exit_abs_z: float = 0.5
    emergency_abs_z: float = 4.0
    max_holding_hours: int = 48
    cost_multiplier: int = 2


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_partitions(root: Path, start: pd.Timestamp, end: pd.Timestamp) -> list[dict[str, object]]:
    files = sorted(root.rglob("data.parquet"))
    selected = []
    for path in files:
        frame = pl.read_parquet(path, columns=["timestamp"])
        ts = pd.to_datetime(frame["timestamp"].to_list(), utc=True)
        if len(ts) and ts.min() < end and ts.max() >= start:
            sidecar = path.with_name("source.json")
            selected.append({
                "path": str(path.relative_to(root)),
                "sha256": _sha256(path),
                "source": json.loads(sidecar.read_text()) if sidecar.is_file() else None,
            })
    return selected


def _frame_fingerprint(frame: pd.DataFrame, semantics: str) -> str:
    payload = {
        "range": [frame["timestamp"].min().isoformat(), frame["timestamp"].max().isoformat()],
        "schema": [(str(name), str(dtype)) for name, dtype in frame.dtypes.items()],
        "timestamp_semantics": semantics,
        "rows": len(frame),
        "values": pd.util.hash_pandas_object(frame, index=False).astype("uint64").tolist(),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _check_hours(frame: pd.DataFrame, symbol: str) -> None:
    expected = pd.date_range(DATA_START, DATA_END - pd.Timedelta(hours=1), freq="1h", tz="UTC")
    actual = pd.DatetimeIndex(frame["timestamp"])
    missing = expected.difference(actual)
    extra = actual.difference(expected)
    if len(missing) or len(extra) or actual.has_duplicates:
        raise RuntimeError(f"{symbol} canonical prices incomplete: missing={len(missing)} extra={len(extra)} duplicates={actual.has_duplicates}")


def _load_price(storage, symbol: str, manifest: dict[str, object]) -> tuple[pd.DataFrame, dict[str, object]]:
    root = STORE_ROOT / PRICE_DATASET
    files = _source_partitions(root / f"symbol={symbol}", DATA_START, DATA_END)
    if not files:
        raise RuntimeError(f"No canonical source partitions for {symbol}")
    source = storage.read(f"symbol={symbol}", start_date=DATA_START.to_pydatetime(), end_date=DATA_END.to_pydatetime()).collect()
    pdf = source.select("timestamp", "symbol", "open", "high", "low", "close", "volume", "quote_volume").to_pandas()
    pdf["timestamp"] = pd.to_datetime(pdf["timestamp"], utc=True)
    pdf = pdf[(pdf["timestamp"] >= DATA_START) & (pdf["timestamp"] < DATA_END)].sort_values("timestamp")
    _check_hours(pdf, symbol)
    if (pdf[["open", "high", "low", "close"]] <= 0).any().any():
        raise RuntimeError(f"{symbol} has non-positive canonical OHLC")
    return pdf, {
        "dataset": PRICE_DATASET, "manifest_identity": _sha256(root / "dataset_manifest.json"),
        "manifest": manifest, "partitions": files, "fingerprint": _frame_fingerprint(pdf, "UTC candle open time"),
    }


def _load_funding(storage, symbol: str) -> tuple[pd.DataFrame, dict[str, object]]:
    key = FUNDING_KEYS[symbol]
    root = STORE_ROOT / key.replace("/", "_")
    context_start = DATA_START - MAX_FUNDING_INTERVAL
    context_end = DATA_END + MAX_FUNDING_INTERVAL
    files = _source_partitions(root, context_start, context_end)
    if not files:
        raise RuntimeError(f"No canonical funding partitions for {symbol}")
    pdf = storage.read(
        key,
        start_date=context_start.to_pydatetime(),
        end_date=context_end.to_pydatetime(),
    ).collect().to_pandas()
    if pdf.empty or "funding_interval_hours" not in pdf.columns:
        raise RuntimeError(f"{symbol} canonical funding cadence evidence is incomplete")
    pdf["timestamp"] = pd.to_datetime(pdf["timestamp"], utc=True)
    pdf = pdf.sort_values("timestamp").reset_index(drop=True)
    timestamps = pdf["timestamp"]
    cadence = pd.to_numeric(pdf["funding_interval_hours"], errors="coerce")
    if (
        timestamps.duplicated().any()
        or cadence.isna().any()
        or not cadence.isin([1, 4, 8]).all()
    ):
        raise RuntimeError(f"{symbol} canonical funding cadence evidence is invalid")

    # This field is the interval from the preceding settlement, not a fixed 8h cadence.
    observed = timestamps.diff().iloc[1:]
    expected = pd.to_timedelta(cadence.iloc[1:], unit="h")
    if ((observed - expected).abs() > pd.Timedelta(minutes=1)).any():
        raise RuntimeError(
            f"{symbol} canonical funding settlement spacing disagrees with "
            "funding_interval_hours"
        )
    in_range = (timestamps >= DATA_START) & (timestamps < DATA_END)
    if (
        not in_range.any()
        or not (timestamps < DATA_START).any()
        or not (timestamps >= DATA_END).any()
    ):
        raise RuntimeError(f"{symbol} canonical funding range lacks boundary evidence")

    result = pdf.loc[
        in_range, ["timestamp", "symbol", "funding_interval_hours", "funding_rate"]
    ]
    return result, {
        "dataset": key, "storage_metadata": storage.get_metadata(key), "partitions": files,
        "fingerprint": _frame_fingerprint(result, "UTC funding settlement time"),
    }


def prepare_data() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    price_storage = create_storage(STORE_ROOT / PRICE_DATASET, strategy="hive")
    funding_storage = create_storage(STORE_ROOT, strategy="hive")
    price_root = STORE_ROOT / PRICE_DATASET
    manifest_path = price_root / "dataset_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Canonical price manifest missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("completeness_status") != "complete_for_requested_archives" or manifest.get("failure_count_this_run") != 0:
        raise RuntimeError("Canonical Binance price manifest is not complete")
    prices, funding_frames = {}, []
    audit: dict[str, object] = {"price_dataset": PRICE_DATASET, "symbols": {}, "funding": {}}
    for symbol in SYMBOLS:
        prices[symbol], audit["symbols"][symbol] = _load_price(price_storage, symbol, manifest)
        funding, audit["funding"][symbol] = _load_funding(funding_storage, symbol)
        funding_frames.append(funding)
    merged = prices["BTCUSDT"][["timestamp", "open", "close"]].rename(columns={"open": "btc_open", "close": "btc_close"}).merge(
        prices["ETHUSDT"][["timestamp", "open", "close"]].rename(columns={"open": "eth_open", "close": "eth_close"}),
        on="timestamp", how="inner", validate="one_to_one",
    )
    if len(merged) != len(prices["BTCUSDT"]):
        raise RuntimeError("BTC/ETH aligned price panel lost rows")
    funding = pd.concat(funding_frames, ignore_index=True).sort_values(["timestamp", "symbol"])
    audit["strategy_price_frame"] = {
        "fingerprint": _frame_fingerprint(merged, "UTC candle open time"),
        "schema": [(str(name), str(dtype)) for name, dtype in merged.dtypes.items()],
    }
    DATA_OUT.mkdir(parents=True, exist_ok=True)
    pl.from_pandas(merged).write_parquet(DATA_OUT / "prices.parquet")
    pl.from_pandas(funding).write_parquet(DATA_OUT / "funding.parquet")
    (DATA_OUT / "data_audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    return merged, funding, audit




def compute_features(prices: pd.DataFrame, formation_days: int) -> pd.DataFrame:
    df = prices.copy().set_index("timestamp")
    w = formation_days * 24
    x = np.log(df["btc_close"])
    y = np.log(df["eth_close"])
    mx = x.rolling(w, min_periods=w).mean()
    my = y.rolling(w, min_periods=w).mean()
    cov = (x * y).rolling(w, min_periods=w).mean() - mx * my
    var = (x * x).rolling(w, min_periods=w).mean() - mx * mx
    beta = cov / var.replace(0.0, np.nan)
    alpha = my - beta * mx
    resid = y - alpha - beta * x
    rmean = resid.rolling(w, min_periods=w).mean()
    rstd = resid.rolling(w, min_periods=w).std(ddof=0)
    z = (resid - rmean) / rstd.replace(0.0, np.nan)

    btc_lr = np.log(df["btc_close"]).diff()
    eth_lr = np.log(df["eth_close"]).diff()
    btc_rv = np.sqrt((btc_lr * btc_lr).rolling(24, min_periods=24).sum())
    eth_rv = np.sqrt((eth_lr * eth_lr).rolling(24, min_periods=24).sum())
    qwin = 90 * 24
    btc_q95 = btc_rv.rolling(qwin, min_periods=qwin).quantile(0.95)
    eth_q95 = eth_rv.rolling(qwin, min_periods=qwin).quantile(0.95)
    vol_gate = (btc_rv <= btc_q95) & (eth_rv <= eth_q95)

    out = df.assign(beta=beta, residual=resid, z=z, vol_gate=vol_gate)

    gate_rows: list[tuple[pd.Timestamp, bool, float, float, float]] = []
    day_points = out.index[(out.index.hour == 0)]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for ts in day_points:
            loc = out.index.get_loc(ts)
            if isinstance(loc, slice) or loc < w - 1:
                continue
            arr = out["residual"].iloc[loc - w + 1 : loc + 1].dropna().to_numpy()
            if len(arr) < w * 0.95:
                continue
            try:
                adf_p = float(adfuller(arr, maxlag=24, regression="c", autolag=None)[1])
                kpss_p = float(kpss(arr, regression="c", nlags="auto")[1])
                lag = arr[:-1]
                nxt = arr[1:]
                phi = float(np.polyfit(lag, nxt, 1)[0])
                half = float(-math.log(2) / math.log(phi)) if 0.0 < phi < 1.0 else float("inf")
                passed = bool(adf_p < 0.05 and kpss_p > 0.05 and 2.0 <= half <= 72.0)
            except Exception:
                adf_p = kpss_p = float("nan")
                half = float("inf")
                passed = False
            gate_rows.append((ts, passed, adf_p, kpss_p, half))
    gates = pd.DataFrame(gate_rows, columns=["timestamp", "stationary_gate", "adf_p", "kpss_p", "half_life_hours"])
    if len(gates):
        gates = gates.set_index("timestamp").reindex(out.index).ffill()
        out = out.join(gates)
    else:
        out["stationary_gate"] = False
        out["adf_p"] = np.nan
        out["kpss_p"] = np.nan
        out["half_life_hours"] = np.nan
    out["stationary_gate"] = out["stationary_gate"].fillna(False).astype(bool)
    out["vol_gate"] = out["vol_gate"].fillna(False).astype(bool)
    return out.reset_index()


def funding_maps(funding: pd.DataFrame) -> dict[str, dict[pd.Timestamp, float]]:
    result: dict[str, dict[pd.Timestamp, float]] = {}
    for symbol in SYMBOLS:
        x = funding[funding["symbol"] == symbol]
        # Funding timestamps can carry millisecond offsets. Charge them in their UTC hour.
        keys = x["timestamp"].dt.floor("1h")
        result[symbol] = dict(zip(keys, x["funding_rate"]))
    return result


def run_backtest(
    features: pd.DataFrame,
    funding: pd.DataFrame,
    params: Params,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[pd.DataFrame, dict[str, object]]:
    df = features.set_index("timestamp")
    fmap = funding_maps(funding)
    idx = df.index
    start_i = int(idx.searchsorted(start))
    end_i = int(idx.searchsorted(end))
    if start_i >= end_i - 1:
        raise RuntimeError("Empty evaluation interval")

    direction = 0
    w_btc = 0.0
    w_eth = 0.0
    entry_i: int | None = None
    pending: tuple[int, float] | None = None
    rows: list[dict[str, object]] = []
    trades = 0
    base_cost = BASE_BPS * params.cost_multiplier / 10_000.0

    for i in range(start_i, end_i - 1):
        ts = idx[i]
        row = df.iloc[i]

        # Execute decision made on the previous completed hourly close.
        turnover = 0.0
        if pending is not None:
            new_dir, beta_for_entry = pending
            if new_dir == 0:
                new_btc = new_eth = 0.0
                entry_i = None
            else:
                gross = 1.0 + abs(beta_for_entry)
                new_eth = new_dir / gross
                new_btc = -new_dir * beta_for_entry / gross
                entry_i = i
                trades += 1
            turnover = abs(new_btc - w_btc) + abs(new_eth - w_eth)
            w_btc, w_eth, direction = new_btc, new_eth, new_dir
            pending = None

        btc_ret = float(df["btc_open"].iloc[i + 1] / df["btc_open"].iloc[i] - 1.0)
        eth_ret = float(df["eth_open"].iloc[i + 1] / df["eth_open"].iloc[i] - 1.0)
        price_pnl = w_btc * btc_ret + w_eth * eth_ret
        fr_btc = float(fmap["BTCUSDT"].get(ts, 0.0))
        fr_eth = float(fmap["ETHUSDT"].get(ts, 0.0))
        funding_pnl = -w_btc * fr_btc - w_eth * fr_eth
        cost = turnover * base_cost
        net = price_pnl + funding_pnl - cost
        rows.append(
            {
                "timestamp": ts,
                "net_return": net,
                "price_pnl": price_pnl,
                "funding_pnl": funding_pnl,
                "trading_cost": cost,
                "w_btc": w_btc,
                "w_eth": w_eth,
                "z": float(row["z"]) if pd.notna(row["z"]) else np.nan,
            }
        )

        # Form the next-open decision from this completed close.
        z = float(row["z"]) if pd.notna(row["z"]) else np.nan
        beta = float(row["beta"]) if pd.notna(row["beta"]) else np.nan
        if direction == 0:
            allow = np.isfinite(z) and np.isfinite(beta) and beta > 0.0
            if params.stage in ("P1", "P2"):
                allow = allow and bool(row["stationary_gate"])
            if params.stage == "P2":
                allow = allow and bool(row["vol_gate"])
            if allow and abs(z) >= params.entry_abs_z and abs(z) < params.emergency_abs_z:
                pending = (-1 if z > 0 else 1, beta)
        else:
            held = 0 if entry_i is None else i - entry_i + 1
            must_exit = (
                (not np.isfinite(z))
                or abs(z) <= params.exit_abs_z
                or abs(z) >= params.emergency_abs_z
                or held >= params.max_holding_hours
            )
            if params.stage in ("P1", "P2") and not bool(row["stationary_gate"]):
                must_exit = True
            if must_exit:
                pending = (0, 0.0)

    ret = pd.DataFrame(rows)
    # Force terminal liquidation cost on any still-open position.
    if len(ret) and (abs(w_btc) + abs(w_eth)) > 0:
        liq_cost = (abs(w_btc) + abs(w_eth)) * base_cost
        ret.loc[ret.index[-1], "trading_cost"] += liq_cost
        ret.loc[ret.index[-1], "net_return"] -= liq_cost

    daily = (
        ret.assign(date=ret["timestamp"].dt.floor("1d"))
        .groupby("date", sort=True)
        .agg(
            net_return=("net_return", lambda x: float(np.prod(1.0 + x) - 1.0)),
            price_pnl=("price_pnl", "sum"),
            funding_pnl=("funding_pnl", "sum"),
            trading_cost=("trading_cost", "sum"),
        )
        .reset_index()
    )
    metrics = summarize(daily, trades)
    return daily, metrics


def summarize(daily: pd.DataFrame, trades: int) -> dict[str, object]:
    r = daily["net_return"].to_numpy(dtype=float)
    if len(r) == 0:
        return {}
    eq = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1.0
    std = float(np.std(r, ddof=1)) if len(r) > 1 else float("nan")
    sharpe = float(np.mean(r) / std * math.sqrt(365.0)) if std > 0 else float("nan")
    years = daily.assign(year=daily["date"].dt.year).groupby("year")["net_return"].apply(
        lambda x: float(np.prod(1.0 + x) - 1.0)
    )
    return {
        "days": int(len(r)),
        "mean_daily_net_return": float(np.mean(r)),
        "annualized_sharpe": sharpe,
        "total_return": float(eq[-1] - 1.0),
        "max_drawdown": float(np.min(dd)),
        "trades": int(trades),
        "funding_pnl_sum": float(daily["funding_pnl"].sum()),
        "trading_cost_sum": float(daily["trading_cost"].sum()),
        "calendar_year_returns": {str(int(k)): float(v) for k, v in years.items()},
        "positive_years": int((years > 0).sum()),
    }


def stationary_bootstrap_lower_bound(r: np.ndarray, block: float = 7.0, n: int = 5000) -> float:
    rng = np.random.default_rng(RNG_SEED)
    m = len(r)
    p = 1.0 / block
    means = np.empty(n)
    for b in range(n):
        sample = np.empty(m)
        j = int(rng.integers(0, m))
        for i in range(m):
            if i == 0 or rng.random() < p:
                j = int(rng.integers(0, m))
            else:
                j = (j + 1) % m
            sample[i] = r[j]
        means[b] = sample.mean()
    return float(np.quantile(means, 0.05))


def child_beats_parent(child: dict[str, object], parent: dict[str, object]) -> tuple[bool, int]:
    cy = child["calendar_year_returns"]
    py = parent["calendar_year_returns"]
    years = sorted(set(cy) & set(py))
    better = sum(float(cy[y]) > float(py[y]) for y in years)
    return (
        int(child.get("trades", 0)) > 0
        and float(child["mean_daily_net_return"]) > float(parent["mean_daily_net_return"])
        and better >= 3,
        better,
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    prices, funding, audit = prepare_data()

    feature_cache: dict[int, pd.DataFrame] = {}
    def feat(days: int) -> pd.DataFrame:
        if days not in feature_cache:
            feature_cache[days] = compute_features(prices, days)
        return feature_cache[days]

    primary_results: dict[str, object] = {}
    accepted = Params(stage="P0")
    parent_daily, parent_metrics = run_backtest(feat(90), funding, accepted, DEV_START, DEV_END)
    primary_results["P0"] = parent_metrics

    p1 = replace(accepted, stage="P1")
    p1_daily, p1_metrics = run_backtest(feat(90), funding, p1, DEV_START, DEV_END)
    promote1, better1 = child_beats_parent(p1_metrics, parent_metrics)
    primary_results["P1"] = {**p1_metrics, "promotion_vs_parent": promote1, "years_better_than_parent": better1}
    if promote1:
        accepted, parent_daily, parent_metrics = p1, p1_daily, p1_metrics

    p2 = replace(accepted, stage="P2")
    p2_daily, p2_metrics = run_backtest(feat(90), funding, p2, DEV_START, DEV_END)
    promote2, better2 = child_beats_parent(p2_metrics, parent_metrics)
    primary_results["P2"] = {**p2_metrics, "promotion_vs_parent": promote2, "years_better_than_parent": better2}
    if promote2:
        accepted, parent_daily, parent_metrics = p2, p2_daily, p2_metrics

    lb = stationary_bootstrap_lower_bound(parent_daily["net_return"].to_numpy(), block=7.0, n=5000)
    dev_pass = bool(
        float(parent_metrics["mean_daily_net_return"]) > 0.0
        and int(parent_metrics["positive_years"]) >= 3
        and lb > 0.0
    )

    sensitivity_specs = {
        "formation-60d": replace(accepted, formation_days=60),
        "formation-120d": replace(accepted, formation_days=120),
        "entry-1p5": replace(accepted, entry_abs_z=1.5),
        "entry-2p5": replace(accepted, entry_abs_z=2.5),
        "hold-24h": replace(accepted, max_holding_hours=24),
        "hold-72h": replace(accepted, max_holding_hours=72),
    }
    sensitivities: dict[str, object] = {}
    for name, p in sensitivity_specs.items():
        _, m = run_backtest(feat(p.formation_days), funding, p, DEV_START, DEV_END)
        sensitivities[name] = m

    cost_results: dict[str, object] = {}
    for mult in (1, 2, 3):
        p = replace(accepted, cost_multiplier=mult)
        _, m = run_backtest(feat(p.formation_days), funding, p, DEV_START, DEV_END)
        cost_results[f"{mult}x"] = m

    # Freeze selection before this point. Open the holdout only if development passes.
    hold_daily = None
    hold_metrics = None
    holdout_open_count = 0
    if dev_pass:
        hold_daily, hold_metrics = run_backtest(
            feat(accepted.formation_days), funding, accepted, HOLD_START, HOLD_END
        )
        holdout_open_count = 1

    robustness_positive = sum(
        float(v["mean_daily_net_return"]) > 0 for v in sensitivities.values()
    )
    gate_diag = {}
    f90 = feat(90)
    dev_mask = (f90["timestamp"] >= DEV_START) & (f90["timestamp"] < DEV_END)
    dev_f90 = f90.loc[dev_mask]
    gate_diag["stationarity_gate_pass_hours"] = int(dev_f90["stationary_gate"].sum())
    gate_diag["stationarity_gate_pass_fraction"] = float(dev_f90["stationary_gate"].mean())
    gate_diag["z_entry_candidate_hours"] = int((dev_f90["z"].abs() >= 2.0).sum())
    gate_diag["z_entry_and_stationarity_hours"] = int(
        ((dev_f90["z"].abs() >= 2.0) & dev_f90["stationary_gate"]).sum()
    )
    result = {
        "session_id": "btc-eth-relative-value-20261004",
        "status": "EXPLORATORY",
        "approval_status": "NOT_APPROVED",
        "data_audit": audit,
        "primary_development": primary_results,
        "selected_primary_model": accepted.__dict__,
        "development_selected_metrics": parent_metrics,
        "development_stationary_bootstrap_95pct_one_sided_lower_bound": lb,
        "development_acceptance_passed": dev_pass,
        "sensitivities_development_only": sensitivities,
        "sensitivity_positive_mean_count": robustness_positive,
        "sensitivity_total": len(sensitivities),
        "cost_stress_development": cost_results,
        "gate_diagnostics": gate_diag,
        "holdout_open_count": holdout_open_count,
        "frozen_holdout": hold_metrics,
        "holdout_confirmation": bool(
            dev_pass and hold_metrics is not None and float(hold_metrics["mean_daily_net_return"]) > 0.0
        ),
        "interpretation": (
            "Research completion does not approve deployment. The historical holdout is a one-time "
            "confirmation only. Any rule change motivated by holdout results requires new unseen future data."
        ),
    }
    pl.from_pandas(parent_daily).write_parquet(OUT / "development_daily.parquet")
    holdout_path = OUT / "holdout_daily.parquet"
    if hold_daily is not None:
        pl.from_pandas(hold_daily).write_parquet(holdout_path)
    elif holdout_path.exists():
        holdout_path.unlink()
    (OUT / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
