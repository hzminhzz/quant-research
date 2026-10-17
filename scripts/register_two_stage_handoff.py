"""Stage 5 Handoff Certificate: Two-Stage Funnel TSMOM with Stop Market & Maker Execution."""

import hashlib
import json
from pathlib import Path
import sqlite3
from datetime import datetime, timezone

HANDOFF_PATH = Path("run_log/stage5_handoffs/crypto_tsmom_two_stage_funnel_stop_exec_v1.json")
DB_PATH = Path("run_log/registry.db")

handoff_payload = {
    "handoff_schema_version": "stage5-handoff-v3",
    "strategy_id": "crypto_tsmom_two_stage_funnel_stop_exec_v1",
    "version": "1.0.0",
    "status": "ACCEPTED_FOR_STAGE5_EXECUTION",
    "created_at": datetime.now(timezone.utc).isoformat(),
    "research_lane": "empirical_thesis_driven",
    "architecture": "Two-Stage Funnel (Liquidity Screen + EMA200 Structural Trend Gate + Risk-Adjusted Momentum Ranking)",
    "execution_models": {
        "primary_recommended": {
            "type": "PASSIVE_MAKER_LIMIT",
            "commission_rate": 0.00018,
            "slippage_rate": 0.0,
            "development_metrics": {"sharpe": 0.630, "return_pct": 17.63, "max_dd_pct": 12.89, "costs": 477.69},
            "holdout_metrics": {"return_pct": 18.65, "max_dd_pct": 20.45, "sharpe": 0.55, "alpha_vs_bnh_pct": 81.80}
        },
        "breakout_alternative": {
            "type": "STOP_MARKET_ORDER",
            "order_type": "OrderType.STOP",
            "trigger_offset": "Close * 1.002",
            "commission_rate": 0.00045,
            "slippage_rate": 0.00015,
            "development_metrics": {"sharpe": 0.311, "return_pct": 7.76, "max_dd_pct": 14.95, "costs": 1430.31},
            "holdout_metrics": {"return_pct": 12.71, "max_dd_pct": 22.95, "sharpe": 0.42, "alpha_vs_bnh_pct": 75.86}
        }
    },
    "stress_testing": {
        "terra_luna_may_2022": {"market_drop_pct": -52.06, "strategy_loss_pct": -0.22, "survived": True},
        "ftx_collapse_nov_2022": {"market_drop_pct": -34.99, "strategy_loss_pct": -0.99, "survived": True}
    },
    "multiple_testing": {
        "total_trials_evaluated": 24,
        "peak_development_sharpe": 1.940,
        "deflated_sharpe_ratio": 0.9991
    },
    "production_guardrails": {
        "max_gross_leverage": 1.0,
        "max_single_weight": 0.20,
        "kill_switch_drawdown": 0.15,
        "kill_switch_action": "HALT_AND_FLATTEN_ALL_POSITIONS"
    }
}

with HANDOFF_PATH.open("w") as f:
    json.dump(handoff_payload, f, indent=2)

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.execute("""
    INSERT OR REPLACE INTO strategy_registry VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (
    "crypto_tsmom_two_stage_funnel_stop_exec_v1",
    hashlib.sha256(json.dumps(handoff_payload).encode()).hexdigest()[:16],
    "git_commit_frozen",
    "1.0.0",
    "FROZEN_STAGE5_ACCEPTED",
    "config/research_sessions/crypto_tsmom_two_stage_funnel_stop_exec.yaml",
    "src/strategies/two_stage_funnel_tsmom.py",
    str(HANDOFF_PATH),
    json.dumps(handoff_payload["execution_models"]),
    json.dumps(handoff_payload["production_guardrails"]),
    datetime.now(timezone.utc).isoformat(),
))
conn.commit()
conn.close()

print(f"Saved Stage 5 handoff to {HANDOFF_PATH}")
print(f"Registered in {DB_PATH}")
