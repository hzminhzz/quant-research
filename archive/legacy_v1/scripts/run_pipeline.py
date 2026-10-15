#!/usr/bin/env python3
"""ML4T 7-Stage Case Study Pipeline Runner.

Usage:
    python scripts/run_pipeline.py --symbol DE30/EUR
    python scripts/run_pipeline.py --symbol JP225/USD --stage 4
"""

import argparse
from pathlib import Path
import sys

# Add repo root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pipeline import ML4TCaseStudyPipeline


def main():
    parser = argparse.ArgumentParser(description="Run ML4T 7-Stage Case Study Pipeline")
    parser.add_argument("--symbol", type=str, default="DE30/EUR", help="Target symbol (e.g. DE30/EUR, JP225/USD)")
    parser.add_argument("--stage", type=int, default=0, help="Stage to run (1-7), or 0 for full pipeline")
    parser.add_argument("--config", type=str, default="config/setup.yaml", help="Path to setup.yaml")
    args = parser.parse_args()

    pipeline = ML4TCaseStudyPipeline(config_path=args.config)
    print(f"=== ML4T 7-Stage Case Study Pipeline: {args.symbol} ===")

    if args.stage == 0:
        report = pipeline.run_pipeline(args.symbol)
        print(f"\n[Artifact Contracts Summary for {report.symbol}]:")
        for s in [
            report.stage1_setup,
            report.stage2_labels,
            report.stage3_features,
            report.stage4_evaluate,
            report.stage5_models,
            report.stage6_backtest,
            report.stage7_synthesis,
        ]:
            status_emoji = "✅ PASS" if s.passed_gate else "❌ FAIL"
            print(f"  Stage {s.stage_id} [{s.stage_name}]: {status_emoji}")
            print(f"     Output: {s.writes_to[0]}")
        print(f"\nProduction Ready: {'YES ✅' if report.is_production_ready else 'NO ❌'}")

    elif args.stage == 1:
        s1 = pipeline.run_stage1_setup(args.symbol)
        print(f"Stage 1 [Setup] completed: {s1.writes_to}")
    elif args.stage == 2:
        s2 = pipeline.run_stage2_labels(args.symbol)
        print(f"Stage 2 [Labels] completed: {s2.writes_to}")
    elif args.stage == 3:
        s3 = pipeline.run_stage3_features(args.symbol)
        print(f"Stage 3 [Features] completed: {s3.writes_to}")
    elif args.stage == 4:
        s4, diag = pipeline.run_stage4_evaluate(args.symbol)
        print(f"Stage 4 [Evaluate] completed: Mean IC={diag.mean_ic:.4f}, p={diag.hac_p_value:.4f}")
    elif args.stage == 5:
        s5, cpcv = pipeline.run_stage5_models(args.symbol)
        print(f"Stage 5 [Models] completed: CPCV AUC={cpcv.mean_auc:.3f}, WinRate={cpcv.filtered_win_rate:.1%}")
    elif args.stage == 6:
        # Requires stage 5 output
        s5, _ = pipeline.run_stage5_models(args.symbol)
        s6, bt = pipeline.run_stage6_backtest(args.symbol, s5)
        print(f"Stage 6 [Backtest] completed: Sharpe={bt['annualized_sharpe']:.2f}, Ret={bt['total_return_pct']:+.1f}%")
    elif args.stage == 7:
        s4, diag = pipeline.run_stage4_evaluate(args.symbol)
        s5, _ = pipeline.run_stage5_models(args.symbol)
        s6, bt = pipeline.run_stage6_backtest(args.symbol, s5)
        s7, synth = pipeline.run_stage7_synthesis(args.symbol, bt, diag)
        print(f"Stage 7 [Synthesis] completed: DSR Prob={synth['dsr_probability']:.1%}, Haircut Sharpe={synth['dsr_haircut_sharpe']:.2f}")


if __name__ == "__main__":
    main()
