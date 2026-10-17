"""Issue #44: credentialed Bybit Demo READ-ONLY native ML4T SafeBroker preflight.

No submission, cancellation, amendment, strategy engine, or order API calls.
Run only with a separately created Demo key and an independently checked Demo UID.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from connectors.bybit import __file__ as bybit_package_file
from connectors.bybit.broker import BybitLiveBroker
from connectors.bybit.client import BybitClient
from connectors.bybit.config import BybitConfig, Environment, Mode
from connectors.bybit.journal import BybitIntentJournal
from connectors.bybit.models import BybitSnapshotError
from ml4t.live import LiveRiskConfig, SafeBroker

REPO_ROOT = Path(__file__).resolve().parents[1]
CONNECTOR_ROOT = Path(bybit_package_file).resolve().parents[2]


def _outside_repo(path: Path) -> bool:
    resolved = path.resolve()
    return not (resolved.is_relative_to(REPO_ROOT) or resolved.is_relative_to(CONNECTOR_ROOT))


def _count(report: dict[str, Any], name: str) -> int:
    value = report.get(name)
    return len(value) if isinstance(value, (list, dict)) else 0


async def inspect(config: BybitConfig, state_file: Path) -> dict[str, Any]:
    """Run only the native preflight; produce an account-ID-free operational summary."""
    if version("ml4t-live") != "0.1.2":
        raise BybitSnapshotError("native_runtime: ml4t-live 0.1.2 required")
    if config.environment is not Environment.DEMO or config.mode is not Mode.READ_ONLY:
        raise BybitSnapshotError("operator_config: explicit Demo/read_only is mandatory")
    if not config.api_key or not config.api_secret or not config.expected_demo_uid:
        raise BybitSnapshotError("operator_config: Demo key/secret/expected UID are required")
    if config.api_key == os.getenv("BYBIT_API_KEY"):
        raise BybitSnapshotError("operator_config: Demo key matches Mainnet key")
    if config.default_type != "swap":
        raise BybitSnapshotError("operator_config: only linear swaps are supported")
    if not _outside_repo(state_file):
        raise BybitSnapshotError("operator_config: risk state must be outside the repository")

    state_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    journal = BybitIntentJournal(state_file.with_suffix(".bybit-intents.sqlite"))
    client = BybitClient(config)
    raw = BybitLiveBroker(client=client, journal=journal)
    safe: SafeBroker | None = None
    try:
        safe = SafeBroker(
            raw,
            LiveRiskConfig(
                execution_mode="paper",
                fail_on_reconciliation_mismatch=True,
                fail_on_journal_error=True,
                state_file=str(state_file),
            ),
        )
        native = await safe.preflight_async()
        reconciliation = native["reconciliation"]
        persistence = safe.persistence_status
        unknown_intents = journal.has_unknown()
        identity = client.demo_identity_evidence or client.preflight_identity_evidence
        clean = bool(
            native["passed"]
            and reconciliation["clean"]
            and identity.get("authenticated_uid_matches_expected") is True
            and not unknown_intents
            and not persistence["state_error"]
            and not persistence["journal_error"]
        )
        return {
            "status": "PASS" if clean else "BLOCKED",
            "reason": None if clean else "reconciliation_or_persistence_uncertain",
            "identity": identity,
            "broker_connected_during_preflight": bool(native["broker_connected"]),
            "account": {
                "equity_usd": native["account_value"],
                "available_usd": native["cash"],
                "amounts_are_private": True,
            },
            "positions": {"count": _count(reconciliation, "live_positions")},
            "pending_orders": {"count": _count(reconciliation, "live_pending_orders")},
            "reconciliation": {
                "clean": bool(reconciliation["clean"]),
                "missing_positions": _count(reconciliation, "missing_positions"),
                "unexpected_positions": _count(reconciliation, "unexpected_positions"),
                "quantity_mismatches": _count(reconciliation, "quantity_mismatches"),
                "missing_pending_orders": _count(reconciliation, "missing_pending_orders"),
                "unexpected_pending_orders": _count(reconciliation, "unexpected_pending_orders"),
                "unresolved_replacement_gaps": _count(reconciliation, "unresolved_replacement_gaps"),
            },
            "persistence": {
                "state_error": persistence["state_error"],
                "journal_error": persistence["journal_error"],
                "journal_required": persistence["journal_required"],
                "state_schema_version": persistence["state_schema_version"],
            },
            "connector_unknown_intents": unknown_intents,
            "scope": "V5 UNIFIED wallet; all linear USDT/USDC positions/orders; unsupported other active categories block",
        }
    finally:
        if safe is not None:
            safe.close_persistence()
        if client.is_connected or raw.is_connected:
            await raw.disconnect()
        else:
            await client.close()
        journal.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state-file", required=True, type=Path,
        help="Exclusive native risk state path outside repository (not a disposable file)",
    )
    parser.add_argument(
        "--evidence-file", type=Path, default=None,
        help="Optional local-only redacted JSON summary outside repository",
    )
    args = parser.parse_args()
    record: dict[str, Any] = {
        "issue": "hzminhzz/quant-research#44",
        "checked_at": datetime.now(UTC).isoformat(),
        "status": "BLOCKED",
        "environment": "demo",
        "mode": "read_only",
        "native_execution_mode": "paper",
        "ml4t_live_version": version("ml4t-live"),
        "submitted_orders": 0,
    }
    try:
        config = BybitConfig.from_env()
        record.update(asyncio.run(inspect(config, args.state_file)))
    except Exception as exc:  # noqa: BLE001 - fail closed on every native/provider failure
        # Never print raw CCXT errors, API keys, account IDs or unredacted snapshots.
        record["status"] = "BLOCKED"
        record["reason"] = str(exc) if isinstance(exc, BybitSnapshotError) else type(exc).__name__

    encoded = json.dumps(record, sort_keys=True, indent=2)
    print(encoded)
    if args.evidence_file is not None:
        if not _outside_repo(args.evidence_file):
            print("Evidence path inside repository rejected", file=sys.stderr)
            return 2
        args.evidence_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(args.evidence_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(encoded + "\n")
    return 0 if record["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
