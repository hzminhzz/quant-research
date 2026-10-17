"""Capture immutable Bybit Demo account evidence using GET endpoints only.

This is an operator-side collector, never an order router. The collector key may
have trading permissions; a separate offline ATS-3 replay never reads credentials.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from connectors.bybit.client import BybitClient
from connectors.bybit.config import BybitConfig, Environment, Mode

ROOT = Path.home() / ".local" / "state" / "quant-research" / "ats3"
READ_METHODS = {
    "orders": "private_get_v5_order_history",
    "executions": "private_get_v5_execution_list",
    "transactions": "private_get_v5_account_transaction_log",
    "closed_pnl": "private_get_v5_position_closed_pnl",
}


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                       default=str, allow_nan=False) + "\n").encode("utf-8")


def _create_private_file(folder: Path, name: str, value: Any) -> dict[str, Any]:
    path = folder / name
    data = _json_bytes(value)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
    return {"name": name, "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data), "rows": len(value) if isinstance(value, list) else None}


def _as_ms(timestamp: str) -> int:
    dt = datetime.fromisoformat(timestamp)
    if dt.tzinfo is None:
        raise ValueError("NAIVE_CAPTURE_CLOCK")
    return int(dt.timestamp() * 1000)


async def _pages(client: BybitClient, method: str, args: dict[str, Any],
                 *, cap: int = 50) -> list[dict[str, Any]]:
    if method not in READ_METHODS.values():
        raise ValueError("UNAPPROVED_ENDPOINT")
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    request = dict(args)
    for _ in range(cap):
        payload = await getattr(client.exchange, method)(request)
        if payload.get("retCode") not in (0, "0"):
            raise ValueError("PROVIDER_RESPONSE_FAILED:" + method)
        result = payload.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("list"), list):
            raise TypeError("PROVIDER_RESULT_INVALID:" + method)
        if not all(isinstance(item, dict) for item in result["list"]):
            raise ValueError("PROVIDER_ROW_INVALID:" + method)
        output.extend(result["list"])
        cursor = result.get("nextPageCursor") or ""
        if not cursor:
            return output
        if not isinstance(cursor, str) or cursor in seen:
            raise ValueError("PROVIDER_PAGINATION_CYCLE:" + method)
        seen.add(cursor)
        request["cursor"] = cursor
    raise ValueError("PROVIDER_PAGINATION_LIMIT:" + method)


def _windows(start_ms: int, end_ms: int, max_days: int):
    step = max_days * 24 * 3600 * 1000
    cursor = start_ms
    while cursor <= end_ms:
        stop = min(end_ms, cursor + step - 1)
        yield cursor, stop
        cursor = stop + 1


async def capture(start: str, end: str, destination: Path) -> dict[str, Any]:
    if destination.exists() or destination.is_symlink():
        raise ValueError("OUTPUT_EXISTS")
    root = ROOT.resolve()
    path = destination.resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("OUTSIDE_PRIVATE_ATS3_STORAGE")
    start_ms, end_ms = _as_ms(start), _as_ms(end)
    if not 0 < end_ms - start_ms <= 7 * 86400000:
        raise ValueError("CAPTURE_WINDOW_MUST_BE_WITHIN_SEVEN_DAYS")
    if end_ms > int(datetime.now(UTC).timestamp() * 1000) + 1000:
        raise ValueError("FUTURE_CAPTURE_WINDOW")
    cfg = BybitConfig.from_env()
    if cfg.environment is not Environment.DEMO or cfg.mode is not Mode.READ_ONLY:
        raise ValueError("DEMO_READ_ONLY_MODE_REQUIRED")
    if not cfg.api_key or not cfg.api_secret or not cfg.expected_demo_uid:
        raise ValueError("DEMO_AUTHENTICATION_MISSING")
    path.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(path, 0o700)
    files: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    counts: dict[str, int] = {}
    client = BybitClient(cfg)
    client.exchange.userAgent = "OpenAI File Downloader, XaiImageApiFetch/1.0"
    try:
        await client.connect()
        if not client.demo_identity_verified or client.demo_identity_evidence.get("private_rest") != "api-demo.bybit.com":
            raise ValueError("DEMO_IDENTITY_NOT_VERIFIED")
        for name, method in READ_METHODS.items():
            try:
                items: list[dict[str, Any]] = []
                windows = _windows(start_ms, end_ms, 1 if name == "transactions" else 7)
                for lower, upper in windows:
                    params: dict[str, Any] = {"startTime": lower, "endTime": upper,
                                               "limit": 50}
                    if name == "transactions":
                        params["accountType"] = "UNIFIED"
                    else:
                        params["category"] = "linear"
                    items.extend(await _pages(client, method, params))
                files[name] = _create_private_file(path, name + ".json", items)
                counts[name] = len(items)
            except Exception as exc:  # noqa: BLE001 - retain partial evidence on API failure
                errors[name] = type(exc).__name__ + ":" + str(exc)[:120]
        try:
            summary = await client.fetch_demo_account_summary()
            raw_wallet = await client.exchange.private_get_v5_account_wallet_balance(
                {"accountType": "UNIFIED"})
            if raw_wallet.get("retCode") not in (0, "0") or not isinstance(raw_wallet.get("result"), dict):
                raise ValueError("WALLET_RESPONSE_INVALID")
            wallet_observed = datetime.now(UTC).isoformat()
            positions = await client.fetch_demo_positions()
            orders = await client.fetch_demo_open_orders()
            wallet = {"snapshot_at": datetime.now(UTC).isoformat(),
                      "wallet_observed_at": wallet_observed,
                      "raw_wallet": raw_wallet,
                      "total_equity_usd": str(summary.equity_usd),
                      "available_usd": str(summary.available_usd),
                      "positions": [p.raw for p in positions],
                      "open_orders": [o.raw for o in orders]}
            files["snapshot"] = _create_private_file(path, "snapshot.json", wallet)
            counts["positions"] = len(positions)
            counts["pending_orders"] = len(orders)
        except Exception as exc:  # noqa: BLE001 - fail closed on incomplete account
            errors["snapshot"] = type(exc).__name__ + ":" + str(exc)[:120]
        report: dict[str, Any] = {
            "schema": "ats3_bybit_demo_archive_v1",
            "environment": "demo",
            "read_only_collector": True,
            "collector_key_is_read_only": client.demo_identity_evidence.get("key_is_read_only"),
            "provider_host": "api-demo.bybit.com",
            "authenticated_demo_account": True,
            "account_uid_private": cfg.expected_demo_uid,
            "interval_start": start,
            "interval_end": end,
            "captured_at": datetime.now(UTC).isoformat(),
            "status": "ARCHIVE_COMPLETE" if not errors else "ARCHIVE_INCOMPLETE",
            "counts": counts, "files": files, "errors": errors,
            "caveat": "Not a certified opening account balance or frozen research baseline; no order creation/cancellation.",
        }
        _create_private_file(path, "manifest.json", report)
        return {"status": report["status"], "counts": counts,
                "errors": errors, "path": str(path),
                "audit_key_read_only": report["collector_key_is_read_only"]}
    finally:
        await client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, help="UTC ISO timestamp")
    parser.add_argument("--end", required=True, help="UTC ISO timestamp or now")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    end = datetime.now(UTC).isoformat() if args.end == "now" else args.end
    try:
        result = asyncio.run(capture(args.start, end, args.output))
    except Exception as exc:  # noqa: BLE001 - redacted operator boundary
        print(json.dumps({"status": "BLOCKED", "reason": type(exc).__name__ + ":" + str(exc)[:140]}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "ARCHIVE_COMPLETE" else 3


if __name__ == "__main__":
    raise SystemExit(main())
