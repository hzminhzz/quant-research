"""Bybit Demo read-only capability capture. Never acquire a trading-state writer."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from connectors.bybit.client import BybitClient
from connectors.bybit.config import BybitConfig, Environment, Mode

from src.research_control.ats3_bybit_archive import ROOT, _create_private_file


async def capture(destination: Path):
    if destination.exists() or not destination.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError("fresh private ATS3 evidence destination required")
    cfg = BybitConfig.from_env()
    if cfg.environment is not Environment.DEMO or cfg.mode is not Mode.READ_ONLY:
        raise ValueError("explicit Demo/read-only required")
    destination.mkdir(parents=True, mode=0o700)
    client = BybitClient(cfg)
    client.exchange.userAgent = "OpenAI File Downloader, XaiImageApiFetch/1.0"
    evidence, errors = {}, {}
    try:
        await client.connect()
        for label, method, params in [
            ("instrument", "public_get_v5_market_instruments_info", {"category": "linear", "symbol": "BTCUSDT"}),
            ("time", "public_get_v5_market_time", {}),
            ("account_info", "private_get_v5_account_info", {}),
            ("fee_rate", "private_get_v5_account_fee_rate", {"category": "linear", "symbol": "BTCUSDT"}),
        ]:
            started = datetime.now(UTC)
            try:
                raw = await getattr(client.exchange, method)(params)
                received = datetime.now(UTC)
                if raw.get("retCode") not in (0, "0"):
                    raise ValueError("provider response failed:" + label)
                value = {"method": method, "parameters": params, "request_at": started.isoformat(),
                         "received_at": received.isoformat(), "raw": raw}
                evidence[label] = _create_private_file(destination, label + ".json", value)
            except Exception as exc:  # noqa: BLE001 - retain redacted provider failure evidence
                code = re.search(r'"retCode"\s*:\s*(-?[0-9]+)', str(exc))
                errors[label] = {"method": method, "error": type(exc).__name__,
                                 "retCode": int(code.group(1)) if code else None}
                evidence[label + "_error"] = _create_private_file(destination, label + "_error.json", errors[label])
        positions = await client.fetch_demo_positions()
        orders = await client.fetch_demo_open_orders()
        specs = json.loads((destination / "instrument.json").read_text())["raw"]["result"]["list"][0]
        account = json.loads((destination / "account_info.json").read_text())["raw"]["result"]
        fees = (json.loads((destination / "fee_rate.json").read_text())["raw"]["result"]["list"]
                if "fee_rate" in evidence else None)
        summary = {
            "status": "READ_ONLY_CAPABILITIES_OBSERVED", "environment": "PROVIDER_DEMO",
            "private_rest": client.demo_identity_evidence.get("private_rest"),
            "authenticated_uid_matches_expected": client.demo_identity_evidence.get("authenticated_uid_matches_expected"),
            "key_is_read_only": client.demo_identity_evidence.get("key_is_read_only"),
            "submitted_orders": 0, "cancelled_orders": 0,
            "positions_count": len(positions), "pending_count": len(orders),
            "account_ref": "sha256:" + hashlib.sha256(cfg.expected_demo_uid.encode()).hexdigest(),
            "instrument": {k: specs[k] for k in ("symbol", "contractType", "status", "settleCoin",
                                                  "priceFilter", "lotSizeFilter", "leverageFilter", "fundingInterval")},
            "margin_mode": account.get("marginMode"), "fee_rates": fees,
            "captured_at": datetime.now(UTC).isoformat(), "evidence": evidence, "errors": errors,
            "limitations": ["read-only observation is not an execution test",
                            "existing position preserved", "no new release authorization",
                            "provider rulebook observed, strategy funding economics unqualified"],
        }
        _create_private_file(destination, "manifest.json", summary)
        return summary
    finally:
        await client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(capture(args.output))
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:  # noqa: BLE001 - do not expose credential-bearing provider errors
        print(json.dumps({"status": "BLOCKED", "reason": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
