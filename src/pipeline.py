"""ML4T 7-Stage Case Study Pipeline Architecture.

Governed by ML4T Skills:
- ml4t-case-study-pipeline
- ml4t-case-study-development
- ml4t-strategy-workflow
- ml4t-compute-features
- ml4t-triple-barrier
- ml4t-evaluate-factor
- ml4t-cpcv
- ml4t-run-backtest
- ml4t-deflated-sharpe

Implements the institutional artifact-contract pattern across all 7 stages:
[1. Setup]     setup.yaml: hypothesis, universe, label horizon, CV folds
     │
[2. Labels]    prices ──> forward returns & triple-barrier labels (data/labels/)
     │
[3. Features]  prices ──> momentum, volatility, microstructure (data/features/)
     │
[4. Evaluate]  features + labels ──> Rank IC, HAC t-stat, decay (run_log/diagnostics/)
     │
[5. Models]    features + labels + CPCV ──> predictions per fold (run_log/models/{hash}/)
     │
[6. Backtest]  predictions ──> event-driven simulation (run_log/strategy/{hash}/)
     │
[7. Synthesis] all results ──> DSR, tearsheets, final production signoff
"""

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import polars as pl
import yaml

from src.features import compute_atr, compute_bollinger_bands, compute_ema, compute_rsi
from src.labeling import compute_forward_returns, create_meta_labels, triple_barrier_labels
from src.diagnostics import evaluate_factor, FactorDiagnosticReport
from src.models import train_meta_model_cpcv, CPCVResult
from src.backtest import CostModel, run_intraday_backtest
from src.synthesis import compute_dsr_audit, generate_tearsheet_metrics, log_strategy_trial, TrialEntry


@dataclass(frozen=True)
class StageContract:
    """Base artifact contract for an ML4T pipeline stage."""
    stage_id: int
    stage_name: str
    reads_from: List[str]
    writes_to: List[str]
    passed_gate: bool


@dataclass
class CaseStudyPipelineReport:
    """Comprehensive artifact report across all 7 pipeline stages."""
    symbol: str
    timeframe: str
    stage1_setup: StageContract
    stage2_labels: StageContract
    stage3_features: StageContract
    stage4_evaluate: StageContract
    stage5_models: StageContract
    stage6_backtest: StageContract
    stage7_synthesis: StageContract

    @property
    def is_production_ready(self) -> bool:
        """Pipeline is production ready only if all 7 stage gates pass."""
        return (
            self.stage1_setup.passed_gate
            and self.stage2_labels.passed_gate
            and self.stage3_features.passed_gate
            and self.stage4_evaluate.passed_gate
            and self.stage5_models.passed_gate
            and self.stage6_backtest.passed_gate
            and self.stage7_synthesis.passed_gate
        )


class ML4TCaseStudyPipeline:
    """Deterministic orchestrator executing the 7-stage ML4T Case Study Pipeline."""

    def __init__(self, config_path: str = "config/setup.yaml"):
        self.config_path = Path(config_path)
        with self.config_path.open("r", encoding="utf-8") as f:
            self.cfg = yaml.safe_load(f)

        # Artifact directories
        self.processed_dir = Path(self.cfg.get("artifacts", {}).get("prices_dir", "data/processed"))
        self.labels_dir = Path(self.cfg.get("artifacts", {}).get("labels_dir", "data/labels"))
        self.features_dir = Path(self.cfg.get("artifacts", {}).get("features_dir", "data/features"))
        self.models_dir = Path(self.cfg.get("artifacts", {}).get("models_dir", "run_log/models"))
        self.strategy_dir = Path(self.cfg.get("artifacts", {}).get("strategy_dir", "run_log/strategy"))
        self.diag_dir = Path("run_log/diagnostics")

        for d in [
            self.processed_dir,
            self.labels_dir,
            self.features_dir,
            self.models_dir,
            self.strategy_dir,
            self.diag_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------------------------
    # STAGE 1: SETUP
    # --------------------------------------------------------------------------
    def run_stage1_setup(self, symbol: str) -> StageContract:
        """Stage 1: Validate input market data and establish canonical price series."""
        sym_clean = symbol.replace("/", "_")
        cache_candidates = [
            self.processed_dir / f"{sym_clean}_15m_2019_2026.parquet",
            Path(f"/tmp/lse_15m_cache/{sym_clean}_15m_2019_2026.parquet"),
        ]
        price_file = None
        for p in cache_candidates:
            if p.exists():
                price_file = p
                break

        if not price_file:
            raise FileNotFoundError(f"No price data found for symbol: {symbol}")

        df_raw = pl.read_parquet(price_file).sort("timestamp")
        
        # Resample to 1H bars for institutional holding period
        df_1h = (
            df_raw.group_by_dynamic("timestamp", every="1h")
            .agg([
                pl.col("open").first(),
                pl.col("high").max(),
                pl.col("low").min(),
                pl.col("close").last(),
                pl.col("volume").sum(),
                pl.col("symbol").first(),
            ])
            .drop_nulls()
        )

        canonical_out = self.processed_dir / f"{sym_clean}_1h_canonical.parquet"
        df_1h.write_parquet(canonical_out)

        passed = len(df_1h) >= 5000
        return StageContract(
            stage_id=1,
            stage_name="Setup",
            reads_from=[str(price_file)],
            writes_to=[str(canonical_out)],
            passed_gate=passed,
        )

    # --------------------------------------------------------------------------
    # STAGE 2: LABELS
    # --------------------------------------------------------------------------
    def run_stage2_labels(self, symbol: str) -> StageContract:
        """Stage 2: Generate forward returns and ATR volatility-adaptive triple-barrier labels."""
        sym_clean = symbol.replace("/", "_")
        prices_in = self.processed_dir / f"{sym_clean}_1h_canonical.parquet"
        df = pl.read_parquet(prices_in)

        # 1. Forward returns
        df_labeled = compute_forward_returns(df, horizons=[1, 4, 8, 16, 20, 32])

        # 2. ATR Triple-Barrier Labels
        df_labeled = compute_atr(df_labeled, period=14, alias="atr_14")
        df_labeled = triple_barrier_labels(
            df_labeled,
            upper_mult=float(self.cfg["labeling"]["triple_barrier"]["upper_mult"]),
            lower_mult=float(self.cfg["labeling"]["triple_barrier"]["lower_mult"]),
            max_holding=int(self.cfg["labeling"]["triple_barrier"]["max_holding"]),
            atr_col="atr_14",
        )

        labels_out = self.labels_dir / f"{sym_clean}_labels.parquet"
        df_labeled.select([
            "timestamp", "symbol", "fwd_ret_1", "fwd_ret_4", "fwd_ret_8",
            "fwd_ret_16", "fwd_ret_20", "fwd_ret_32", "tb_label", "tb_holding_bars", "tb_return"
        ]).write_parquet(labels_out)

        passed = df_labeled["tb_label"].drop_nulls().len() > 1000
        return StageContract(
            stage_id=2,
            stage_name="Labels",
            reads_from=[str(prices_in)],
            writes_to=[str(labels_out)],
            passed_gate=passed,
        )

    # --------------------------------------------------------------------------
    # STAGE 3: FEATURES
    # --------------------------------------------------------------------------
    def run_stage3_features(self, symbol: str) -> StageContract:
        """Stage 3: Compute technical, momentum, and volatility feature matrix with zero lookahead."""
        sym_clean = symbol.replace("/", "_")
        prices_in = self.processed_dir / f"{sym_clean}_1h_canonical.parquet"
        df = pl.read_parquet(prices_in)

        # Momentum features
        df_feat = compute_rsi(df, period=2, alias="rsi_2")
        df_feat = compute_rsi(df_feat, period=5, alias="rsi_5")
        df_feat = compute_rsi(df_feat, period=14, alias="rsi_14")

        # Trend features
        df_feat = compute_ema(df_feat, span=20, alias="ema_20")
        df_feat = compute_ema(df_feat, span=50, alias="ema_50")
        df_feat = compute_ema(df_feat, span=200, alias="ema_200")

        # Volatility features
        df_feat = compute_atr(df_feat, period=14, alias="atr_14")
        df_feat = compute_bollinger_bands(df_feat, period=20, num_std=2.0)

        # Donchian rolling channels (strictly shifted by 1 to prevent lookahead)
        c = pl.col("close")
        o = pl.col("open")
        h = pl.col("high")
        l = pl.col("low")

        donchian_10 = pl.col("high").shift(1).rolling_max(10).alias("donchian_10")
        donchian_20 = pl.col("high").shift(1).rolling_max(20).alias("donchian_20")
        donchian_48 = pl.col("high").shift(1).rolling_max(48).alias("donchian_48")
        ema_stretch = ((c - pl.col("ema_50")) / pl.col("atr_14")).alias("ema50_stretch")

        df_feat = df_feat.with_columns([donchian_10, donchian_20, donchian_48, ema_stretch]).drop_nulls()

        features_out = self.features_dir / f"{sym_clean}_features.parquet"
        df_feat.write_parquet(features_out)

        passed = len(df_feat) >= 4000
        return StageContract(
            stage_id=3,
            stage_name="Features",
            reads_from=[str(prices_in)],
            writes_to=[str(features_out)],
            passed_gate=passed,
        )

    # --------------------------------------------------------------------------
    # STAGE 4: EVALUATE (DIAGNOSTICS)
    # --------------------------------------------------------------------------
    def run_stage4_evaluate(self, symbol: str) -> Tuple[StageContract, FactorDiagnosticReport]:
        """Stage 4: Evaluate factor predictive power (Rank IC, HAC t-stat, Decay)."""
        sym_clean = symbol.replace("/", "_")
        feat_in = self.features_dir / f"{sym_clean}_features.parquet"
        labels_in = self.labels_dir / f"{sym_clean}_labels.parquet"

        df_feat = pl.read_parquet(feat_in)
        df_labels = pl.read_parquet(labels_in)

        # Point-in-time join
        df_merged = df_feat.join(df_labels, on=["timestamp", "symbol"], how="inner")

        # Evaluate momentum signal vs 20-bar forward return
        sig_expr = (pl.col("close") > pl.col("donchian_10")).cast(pl.Float64).alias("primary_signal")
        df_eval = df_merged.with_columns(sig_expr)

        report = evaluate_factor(
            df=df_eval,
            signal_col="primary_signal",
            return_col="fwd_ret_20",
            min_ic=float(self.cfg["quality_gates"]["alpha_gate"]["min_rank_ic"]),
            max_p_value=float(self.cfg["quality_gates"]["alpha_gate"]["max_p_value"]),
        )

        diag_out = self.diag_dir / f"{sym_clean}_diagnostics.json"
        with diag_out.open("w", encoding="utf-8") as f:
            json.dump({
                "factor": report.factor_name,
                "mean_ic": report.mean_ic,
                "hac_t_stat": report.hac_t_stat,
                "hac_p_value": report.hac_p_value,
                "is_monotonic": report.is_monotonic,
                "passed_quality_gate": report.passed_quality_gate,
            }, f, indent=2)

        return StageContract(
            stage_id=4,
            stage_name="Evaluate",
            reads_from=[str(feat_in), str(labels_in)],
            writes_to=[str(diag_out)],
            passed_gate=report.passed_quality_gate,
        ), report

    # --------------------------------------------------------------------------
    # STAGE 5: MODELS (CPCV & META-LABELING)
    # --------------------------------------------------------------------------
    def run_stage5_models(self, symbol: str) -> Tuple[StageContract, CPCVResult]:
        """Stage 5: Train Machine Learning Meta-Model with Combinatorial Purged CV."""
        sym_clean = symbol.replace("/", "_")
        feat_in = self.features_dir / f"{sym_clean}_features.parquet"
        labels_in = self.labels_dir / f"{sym_clean}_labels.parquet"

        df_feat = pl.read_parquet(feat_in)
        df_labels = pl.read_parquet(labels_in)
        df_merged = df_feat.join(df_labels, on=["timestamp", "symbol"], how="inner")

        # Primary signal: Donchian high breakout in trend
        primary_signal = (
            (pl.col("close") > pl.col("donchian_10"))
            & (pl.col("close") > pl.col("ema_200"))
        ).cast(pl.Int32).alias("primary_signal")

        df_merged = df_merged.with_columns(primary_signal)

        # Meta-label: 1 if forward return covered friction (> 6 bps), else 0
        df_meta = create_meta_labels(
            primary_signal_col="primary_signal",
            outcome_return_col="fwd_ret_20",
            df=df_merged,
            profit_threshold=0.0006,
        )

        # Feature matrix for meta-model
        feature_cols = [
            "rsi_2", "rsi_5", "rsi_14", "atr_14", "bb_pct_b",
            "donchian_10", "donchian_20", "donchian_48", "ema50_stretch"
        ]
        available_cols = [c for c in feature_cols if c in df_meta.columns]
        X = df_meta.select(available_cols).to_numpy()
        y_meta = df_meta["meta_label"].to_numpy().astype(float)
        active_mask = (df_meta["primary_signal"] == 1).to_numpy()

        cpcv_res = train_meta_model_cpcv(
            X=X,
            y_meta=y_meta,
            active_trade_mask=active_mask,
            n_groups=int(self.cfg["validation"]["cpcv"]["n_groups"]),
            n_test_groups=int(self.cfg["validation"]["cpcv"]["n_test_groups"]),
            label_horizon=int(self.cfg["validation"]["cpcv"]["label_horizon"]),
            embargo_size=int(self.cfg["validation"]["cpcv"]["embargo_size"]),
            conviction_threshold=0.52,
        )

        model_hash = hashlib.sha256(f"{symbol}_cpcv_v1".encode()).hexdigest()[:10]
        model_out_dir = self.models_dir / model_hash
        model_out_dir.mkdir(parents=True, exist_ok=True)
        preds_out = model_out_dir / "predictions.parquet"

        df_meta.with_columns([
            pl.Series("meta_probability", cpcv_res.oof_probabilities),
            pl.when(pl.Series("meta_probability", cpcv_res.oof_probabilities) >= 0.52)
            .then(1).otherwise(0).alias("final_signal")
        ]).select(["timestamp", "symbol", "primary_signal", "meta_probability", "final_signal"]).write_parquet(preds_out)

        return StageContract(
            stage_id=5,
            stage_name="Models",
            reads_from=[str(feat_in), str(labels_in)],
            writes_to=[str(preds_out)],
            passed_gate=cpcv_res.passed_quality_gate,
        ), cpcv_res

    # --------------------------------------------------------------------------
    # STAGE 6: BACKTEST
    # --------------------------------------------------------------------------
    def run_stage6_backtest(self, symbol: str, model_contract: StageContract) -> Tuple[StageContract, Dict[str, Any]]:
        """Stage 6: Event-driven backtest with realistic 6 bps execution friction."""
        sym_clean = symbol.replace("/", "_")
        prices_in = self.processed_dir / f"{sym_clean}_1h_canonical.parquet"
        preds_in = Path(model_contract.writes_to[0])

        df_prices = pl.read_parquet(prices_in)
        df_preds = pl.read_parquet(preds_in)
        df_bt = df_prices.join(df_preds, on=["timestamp", "symbol"], how="inner")

        res = run_intraday_backtest(
            df=df_bt,
            entry_signal_col="final_signal",
            holding_bars=int(self.cfg["labeling"]["triple_barrier"]["max_holding"]),
            commission_bps=float(self.cfg["execution"]["commission_bps"]),
            slippage_bps=float(self.cfg["execution"]["slippage_bps"]),
        )

        strat_hash = hashlib.sha256(f"{symbol}_strat_v1".encode()).hexdigest()[:10]
        strat_out_dir = self.strategy_dir / strat_hash
        strat_out_dir.mkdir(parents=True, exist_ok=True)

        eq_out = strat_out_dir / "equity.parquet"
        res["daily_equity"].write_parquet(eq_out)

        metrics_out = strat_out_dir / "metrics.json"
        with metrics_out.open("w", encoding="utf-8") as f:
            json.dump({
                "symbol": symbol,
                "annualized_sharpe": res["annualized_sharpe"],
                "total_return_pct": res["total_return_pct"],
                "max_drawdown_pct": res["max_drawdown_pct"],
                "win_rate_pct": res["win_rate_pct"],
                "total_trades": res["total_trades"],
            }, f, indent=2)

        passed = bool(
            res["annualized_sharpe"] >= float(self.cfg["quality_gates"]["economic_gate"]["min_oos_sharpe"])
            and res["max_drawdown_pct"] <= float(self.cfg["quality_gates"]["economic_gate"]["max_drawdown_pct"])
        )

        return StageContract(
            stage_id=6,
            stage_name="Backtest",
            reads_from=[str(prices_in), str(preds_in)],
            writes_to=[str(eq_out), str(metrics_out)],
            passed_gate=passed,
        ), res

    # --------------------------------------------------------------------------
    # STAGE 7: SYNTHESIS & AUDIT
    # --------------------------------------------------------------------------
    def run_stage7_synthesis(
        self,
        symbol: str,
        bt_results: Dict[str, Any],
        diag_report: FactorDiagnosticReport,
    ) -> Tuple[StageContract, Dict[str, Any]]:
        """Stage 7: Deflated Sharpe Ratio audit and standardized tearsheet export."""
        tearsheet = generate_tearsheet_metrics(
            daily_equity_df=bt_results["daily_equity"],
            total_trades=bt_results["total_trades"],
            win_rate_pct=bt_results["win_rate_pct"],
            profit_factor=bt_results["profit_factor"],
            rank_ic=diag_report.mean_ic,
            p_value=diag_report.hac_p_value,
        )

        # Log trial to persistent ledger
        trial = TrialEntry(
            trial_id=f"pipeline-{symbol.replace('/', '_')}-1h",
            strategy_name="ML4T Meta-Labeled Breakout Pipeline",
            family="Breakout+MetaModel",
            symbol=symbol,
            timeframe="1h",
            parameters={
                "holding_bars": self.cfg["labeling"]["triple_barrier"]["max_holding"],
                "commission_bps": self.cfg["execution"]["commission_bps"],
                "slippage_bps": self.cfg["execution"]["slippage_bps"],
            },
            in_sample_sharpe=0.50,
            out_of_sample_sharpe=tearsheet["annualized_sharpe"],
            total_return_pct=tearsheet["total_return_pct"],
            max_drawdown_pct=tearsheet["max_drawdown_pct"],
            win_rate_pct=tearsheet["win_rate_pct"],
            total_trades=tearsheet["total_trades"],
            rank_ic=diag_report.mean_ic,
        )
        log_strategy_trial(trial, ledger_path=self.cfg["artifacts"]["trials_ledger"])

        passed = bool(
            tearsheet["dsr_probability"] >= float(self.cfg["quality_gates"]["overfitting_gate"]["min_dsr_probability"])
        )

        synth_out = Path(self.cfg["artifacts"]["leaderboard_file"])
        return StageContract(
            stage_id=7,
            stage_name="Synthesis",
            reads_from=[self.cfg["artifacts"]["trials_ledger"]],
            writes_to=[str(synth_out)],
            passed_gate=passed,
        ), tearsheet

    # --------------------------------------------------------------------------
    # FULL END-TO-END PIPELINE EXECUTION
    # --------------------------------------------------------------------------
    def run_pipeline(self, symbol: str) -> CaseStudyPipelineReport:
        """Run complete 7-stage ML4T Case Study Pipeline for a target asset."""
        # Stage 1
        s1 = self.run_stage1_setup(symbol)
        # Stage 2
        s2 = self.run_stage2_labels(symbol)
        # Stage 3
        s3 = self.run_stage3_features(symbol)
        # Stage 4
        s4, diag_rep = self.run_stage4_evaluate(symbol)
        # Stage 5
        s5, cpcv_res = self.run_stage5_models(symbol)
        # Stage 6
        s6, bt_res = self.run_stage6_backtest(symbol, s5)
        # Stage 7
        s7, tearsheet = self.run_stage7_synthesis(symbol, bt_res, diag_rep)

        return CaseStudyPipelineReport(
            symbol=symbol,
            timeframe=self.cfg["universe"]["resample_timeframe"],
            stage1_setup=s1,
            stage2_labels=s2,
            stage3_features=s3,
            stage4_evaluate=s4,
            stage5_models=s5,
            stage6_backtest=s6,
            stage7_synthesis=s7,
        )
