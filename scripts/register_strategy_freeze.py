"""Register frozen strategy in SQLite Experiment Registry (ml4t-registry-system)."""

import hashlib
import json
from pathlib import Path
import sqlite3
from datetime import datetime, timezone

DB_PATH = Path("run_log/registry.db")
CONFIG_PATH = Path("config/strategies/crypto_tsmom_maker_regime_v1.yaml")
HANDOFF_PATH = Path("run_log/stage5_handoffs/crypto_tsmom_maker_regime_v1.json")
MODULE_PATH = Path("src/strategies/crypto_tsmom_maker_regime.py")


def compute_file_hash(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def register():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS strategy_registry (
            strategy_id TEXT PRIMARY KEY,
            config_hash TEXT NOT NULL,
            module_hash TEXT NOT NULL,
            version TEXT NOT NULL,
            status TEXT NOT NULL,
            config_path TEXT NOT NULL,
            module_path TEXT NOT NULL,
            handoff_path TEXT NOT NULL,
            metrics JSON NOT NULL,
            operational_contract JSON NOT NULL,
            registered_at TEXT NOT NULL
        )
    """)

    config_hash = compute_file_hash(CONFIG_PATH)
    module_hash = compute_file_hash(MODULE_PATH)

    with HANDOFF_PATH.open() as f:
        handoff = json.load(f)

    metrics_payload = handoff["empirical_scorecard"]
    contract_payload = handoff["operational_guardrails"]

    cursor.execute("""
        INSERT OR REPLACE INTO strategy_registry VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "crypto_tsmom_maker_regime_v1",
        config_hash,
        module_hash,
        "1.0.0",
        "FROZEN_STAGE5_ACCEPTED",
        str(CONFIG_PATH),
        str(MODULE_PATH),
        str(HANDOFF_PATH),
        json.dumps(metrics_payload),
        json.dumps(contract_payload),
        datetime.now(timezone.utc).isoformat(),
    ))

    conn.commit()
    conn.close()
    print(f"Strategy registered successfully in {DB_PATH}:")
    print(f"  Strategy ID: crypto_tsmom_maker_regime_v1")
    print(f"  Config SHA256: {config_hash}")
    print(f"  Module SHA256: {module_hash}")
    print(f"  Status: FROZEN_STAGE5_ACCEPTED")


if __name__ == "__main__":
    register()
