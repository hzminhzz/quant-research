"""Offline ATS-3 forensic reconciliation of immutable Bybit Demo V5 evidence.

This module has no Bybit/CCXT imports and no network or credential access.
It treats USDT perpetual cash flows differently from spot inventory purchases.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


def _dec(value: Any, field: str) -> Decimal:
    if value is None or value == "":
        raise ValueError("MISSING_NUMERIC:" + field)
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("INVALID_NUMERIC:" + field) from exc
    if not result.is_finite():
        raise ValueError("NONFINITE_NUMERIC:" + field)
    return result


def _source(folder: Path, meta: dict[str, Any], name: str) -> Any:
    ref = meta["files"].get(name)
    if not isinstance(ref, dict) or ref.get("name") != name + ".json":
        raise ValueError("MISSING_SOURCE:" + name)
    path = folder / (name + ".json")
    if path.is_symlink() or not path.is_file():
        raise ValueError("SOURCE_UNSAFE:" + name)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
        raise ValueError("SOURCE_HASH_MISMATCH:" + name)
    obj = json.loads(raw)
    if isinstance(obj, list) and len(obj) != ref.get("rows"):
        raise ValueError("SOURCE_ROW_COUNT_CHANGED:" + name)
    return obj


def _unique(rows: list[dict[str, Any]], key: str, name: str) -> tuple[list[dict[str, Any]], int]:
    seen: dict[str, dict[str, Any]] = {}
    repeat = 0
    for row in rows:
        identity = str(row.get(key) or "")
        if not identity:
            raise ValueError("SOURCE_ID_MISSING:" + name)
        if identity in seen:
            if seen[identity] != row:
                raise ValueError("SOURCE_ID_CONFLICT:" + name)
            repeat += 1
        seen[identity] = row
    return list(seen.values()), repeat


def _approx(actual: Decimal, expected: Decimal, label: str, tolerance=Decimal("0.0000001")):
    if abs(actual - expected) > tolerance:
        raise ValueError("NUMERICAL_DISCREPANCY:" + label)



def _local_journal(path: Path, account_uid: str, provider_orders: set[str],
                   window_start: str, window_end: str, *,
                   sqlite_journal: Path | None = None,
                   drill_evidence: Path | None = None,
                   waive_read_only_key: bool = False) -> dict[str, Any]:
    """Validate existing native SafeBroker hash-linked intent/route evidence."""
    expected = "bybit-demo-account-" + account_uid + "-journal.jsonl"
    if path.is_symlink() or path.name != expected or not path.is_file():
        raise ValueError("JOURNAL_ACCOUNT_BINDING_FAILED")
    blob = path.read_bytes()
    if not blob.endswith(b"\n"):
        raise ValueError("JOURNAL_TRUNCATED_RECORD")
    rows = [json.loads(line) for line in blob.decode("utf-8").splitlines()
            if line.strip()]
    if not rows:
        raise ValueError("JOURNAL_EMPTY")
    last_sequence = 0
    previous_hash = "0" * 64
    hashes: dict[int, str] = {}
    intent_count = submitted = provider_linked = cancelled = 0
    unmatched: list[dict[str, Any]] = []
    consumed: set[str] = set()
    reconciled_intents: list[dict[str, Any]] = []
    unknowns: set[str] = set()
    base = Path.home() / ".local" / "state" / "quant-research"
    if path.resolve().is_relative_to(base.resolve()):
        sqlite_journal = sqlite_journal or base / f"bybit-demo-account-{account_uid}-intents.sqlite"
        drill_evidence = drill_evidence or base / "bybit-demo-order-lifecycle-drill-evidence.json"
    sqlite_rows: list[dict[str, Any]] = []
    if sqlite_journal is not None and sqlite_journal.is_file() and not sqlite_journal.is_symlink():
        with sqlite3.connect(f"file:{sqlite_journal}?mode=ro", uri=True) as db:
            columns = [row[1] for row in db.execute("PRAGMA table_info(intents)")]
            sqlite_rows = [dict(zip(columns, row)) for row in db.execute("SELECT * FROM intents")]
            audit_columns = [row[1] for row in db.execute("PRAGMA table_info(audit)")]
            audit_rows = [dict(zip(audit_columns, row)) for row in db.execute("SELECT * FROM audit")]
    else:
        audit_rows = []
    drill_orders: set[str] = set()
    if drill_evidence is not None and drill_evidence.is_file() and not drill_evidence.is_symlink():
        drill = json.loads(drill_evidence.read_text(encoding="utf-8"))
        lifecycle = drill.get("lifecycle_drill", {}) if isinstance(drill, dict) else {}
        entries = (drill if isinstance(drill, list) else
                   [lifecycle, *drill.get("records", drill.get("drills", []))])
        drill_orders = {str(entry.get("order_id") or entry.get("exchange_order_id"))
                        for entry in entries if isinstance(entry, dict)
                        and entry.get("drill_type") == "scripted_order_cancel_reconcile"
                        and entry.get("cancelled_confirmed") is True
                        and (entry.get("order_id") or entry.get("exchange_order_id"))}
    start = datetime.fromisoformat(window_start)
    end = datetime.fromisoformat(window_end)
    for row in rows:
        seq = row.get("sequence")
        if not isinstance(seq, int) or seq != last_sequence + 1:
            raise ValueError("JOURNAL_SEQUENCE_DISCONTINUITY")
        last_sequence = seq
        if row.get("previous_hash") != previous_hash:
            raise ValueError("JOURNAL_HASH_CHAIN_BROKEN")
        current_hash = row.get("entry_hash")
        unsigned = {key: value for key, value in row.items() if key != "entry_hash"}
        verified_hash = hashlib.sha256(json.dumps(
            unsigned, allow_nan=False, ensure_ascii=False, separators=(",", ":"),
            sort_keys=True).encode("utf-8")).hexdigest()
        if current_hash != verified_hash:
            raise ValueError("JOURNAL_EVENT_HASH_INVALID")
        previous_hash = current_hash
        hashes[seq] = current_hash
        if row.get("execution_mode") != "paper" or row.get("shadow_mode") is not False:
            raise ValueError("JOURNAL_NOT_ACTUAL_DEMO_PAPER")
        timestamp = datetime.fromisoformat(str(row["timestamp"]))
        if not (start <= timestamp <= end):
            continue
        kind = row.get("event")
        payload = row.get("payload") or {}
        if kind == "order_submission_intent":
            intent_count += 1
            unmatched.append({"payload": payload, "seq": seq, "timestamp": timestamp})
        elif kind == "order_submitted":
            submitted += 1
            order_id = str(payload.get("order_id") or "")
            if order_id in provider_orders:
                provider_linked += 1
            elif order_id in drill_orders:
                reconciled_intents.append({"order_id": order_id, "disposition": "DRILL_ORDER_CANCELLED",
                                           "evidence": "scripted_order_cancel_reconcile"})
            else:
                unknowns.add("SUBMITTED_ORDER_NOT_IN_CURRENT_PROVIDER_HISTORY")
            if order_id:
                for rec in sqlite_rows:
                    if str(rec.get("exchange_order_id") or "") == order_id:
                        consumed.add(str(rec.get("id")))
            matched = False
            for ix in range(len(unmatched) - 1, -1, -1):
                old = unmatched[ix]["payload"]
                if (old.get("asset") == payload.get("asset")
                        and str(old.get("side")) == str(payload.get("side"))
                        and str(old.get("quantity")) == str(payload.get("quantity"))):
                    unmatched.pop(ix)
                    matched = True
                    break
            if not matched:
                unknowns.add("SUBMISSION_WITHOUT_MATCHED_INTENT")
        elif kind == "order_cancel_requested" and payload.get("cancelled"):
            cancelled += 1
    head_path = path.with_name(path.name + ".head")
    if head_path.is_symlink() or not head_path.is_file():
        raise ValueError("JOURNAL_HEAD_MISSING")
    head = json.loads(head_path.read_text(encoding="utf-8"))
    identity = {"schema_version": 1, "sequence": head.get("sequence"),
                "head_hash": head.get("head_hash")}
    expected_head = hashlib.sha256(json.dumps(
        identity, allow_nan=False, ensure_ascii=False, separators=(",", ":"),
        sort_keys=True).encode("utf-8")).hexdigest()
    if (head.get("schema_version") != 1 or head.get("checksum") != expected_head
            or head.get("head_hash") != hashes.get(head.get("sequence"))):
        raise ValueError("JOURNAL_HEAD_CHECKSUM_OR_CURSOR_INVALID")
    for item in list(unmatched):
        payload = item["payload"]
        item_dt = item.get("timestamp")
        candidates = []
        for record in sqlite_rows:
            rec_id = str(record.get("id"))
            if rec_id in consumed:
                continue
            if str(record.get("asset", "")).upper() != str(payload.get("asset", "")).upper():
                continue
            if str(record.get("side", "")).lower() != str(payload.get("side", "")).lower():
                continue
            if str(record.get("quantity")) != str(payload.get("quantity")):
                continue
            if str(record.get("limit_price")) != str(payload.get("limit_price")):
                continue
            # Require causal timestamp proximity (within 2 seconds)
            rec_created = float(record.get("created_at") or 0)
            if item_dt is not None and rec_created > 0:
                rec_dt = datetime.fromtimestamp(rec_created, tz=item_dt.tzinfo)
                if abs((item_dt - rec_dt).total_seconds()) > 2.0:
                    continue
            candidates.append(record)

        for record in candidates:
            exchange_id = str(record.get("exchange_order_id") or "")
            audit_match = [row for row in audit_rows
                           if str(record.get("id")) in row.get("detail", "")
                           or (exchange_id and exchange_id in row.get("detail", ""))]
            state = str(record.get("state", "")).lower()
            if state == "rejected" or (
                    state in ("cancelled", "canceled", "submitted")
                    and audit_match and any(
                        "cancel" in row.get("detail", "").lower()
                        for row in audit_match)):
                break
        else:
            continue
        disposition = str(record["state"]).upper()
        if disposition == "SUBMITTED":
            disposition = "CANCELLED_ON_PROVIDER"
        reconciled_intents.append({
            "intent_id": record.get("id"), "disposition": disposition,
            "reason": record.get("detail"),
            "evidence": "sqlite_intents_and_audit" if audit_match else "sqlite_intents"})
        consumed.add(str(record.get("id")))
        unmatched.remove(item)
    if unmatched:
        unknowns.add("INTENT_TERMINAL_REASON_NOT_RECORDED")
    return {
        "event_count": len(rows),
        "last_sequence": last_sequence,
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "intent_count": intent_count,
        "submitted_count": submitted,
        "linked_to_provider_orders": provider_linked,
        "cancel_confirmations_local": cancelled,
        "unmatched_intent_count": len(unmatched),
        "reconciled_intents": reconciled_intents,
        "unknowns": sorted(unknowns),
        "least_privilege_audit_credential": "WAIVED_BY_OPERATOR" if waive_read_only_key else None,
        "scope": "Native SafeBroker local journal; provider/history retention independently evaluated",
    }


def reconcile_archive(folder: Path, journal: Path | None = None, *,
                      sqlite_journal: Path | None = None,
                      drill_evidence: Path | None = None,
                      waive_read_only_key: bool = False) -> dict[str, Any]:
    folder = folder.resolve(strict=True)
    manifest_path = folder / "manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("MANIFEST_UNSAFE")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "ARCHIVE_COMPLETE" or manifest.get("environment") != "demo":
        raise ValueError("ARCHIVE_INCOMPLETE_OR_WRONG_ENVIRONMENT")
    names = ("orders", "executions", "transactions", "closed_pnl", "snapshot")
    raw = {name: _source(folder, manifest, name) for name in names}
    orders, d1 = _unique(raw["orders"], "orderId", "orders")
    executions, d2 = _unique(raw["executions"], "execId", "executions")
    transactions, d3 = _unique(raw["transactions"], "id", "transactions")
    duplicates = d1 + d2 + d3
    order_map = {str(row["orderId"]): row for row in orders}
    trade_exec = sorted([r for r in executions if r.get("execType") == "Trade"],
                        key=lambda r: (int(r["execTime"]), r["execId"]))
    funds_exec = [r for r in executions if r.get("execType") == "Funding"]
    trade_transactions = [r for r in transactions if r.get("type") == "TRADE"]
    settlement_transactions = [r for r in transactions if r.get("type") == "SETTLEMENT"]
    unknowns: list[str] = []
    unexpected = [r.get("execType") for r in executions if r.get("execType") not in ("Trade", "Funding")]
    if unexpected:
        unknowns.append("UNSUPPORTED_EXECUTION_TYPES:" + ",".join(sorted(set(map(str, unexpected)))))
    if len(orders) != len(order_map):
        raise ValueError("ORDER_ID_COLLISION")
    fills_per_order: dict[str, Decimal] = defaultdict(Decimal)
    for fill in trade_exec:
        oid = str(fill["orderId"])
        fills_per_order[oid] += _dec(fill["execQty"], "execQty")
        if oid not in order_map:
            unknowns.append("FILL_WITHOUT_RETRIEVED_ORDER")
        if fill.get("side") not in ("Buy", "Sell"):
            raise ValueError("INVALID_EXECUTION_SIDE")
        if _dec(fill.get("execPrice"), "execPrice") <= 0:
            raise ValueError("INVALID_EXECUTION_PRICE")
    for oid, order in order_map.items():
        expected = _dec(order.get("cumExecQty"), "cumExecQty")
        filled = fills_per_order.get(oid, Decimal(0))
        if expected != filled:
            raise ValueError("ORDER_CUM_FILL_MISMATCH")
        if order.get("orderStatus") == "Filled" and expected != _dec(order["qty"], "orderQty"):
            raise ValueError("FILLED_ORDER_QUANTITY_MISMATCH")
    trade_by_id = {str(e["execId"]): e for e in trade_exec}
    for row in trade_transactions:
        key = str(row.get("tradeId") or "")
        if key not in trade_by_id:
            unknowns.append("TRADE_TRANSACTION_UNJOINED")
            continue
        e = trade_by_id[key]
        if row.get("orderId") != e.get("orderId"):
            raise ValueError("TRADE_ORDER_LINK_MISMATCH")
        _approx(_dec(row["fee"], "tx_trade_fee"), _dec(e["execFee"], "exec_trade_fee"),
                "EXECUTION_TRANSACTION_FEE")
        if row.get("side") != e.get("side"):
            raise ValueError("TRADE_SIDE_MISMATCH")
    if len(trade_transactions) != len(trade_exec):
        unknowns.append("TRADE_TRANSACTION_COVERAGE_INCOMPLETE")
    # Derivatives do not spend their full notional from the USDT wallet.
    # Only realized PnL, funding, commissions and transfers modify the wallet.
    cash: Decimal | None = None
    first_cash: Decimal | None = None
    fees = financing = realized_cashflow = transfers = Decimal(0)
    for tx in sorted(transactions, key=lambda t: (int(t["transactionTime"]), t["id"])):
        if tx.get("currency") != "USDT":
            unknowns.append("NON_USDT_TRANSACTION_CURRENCY")
            continue
        cf = _dec(tx["cashFlow"], "cashFlow")
        funding = _dec(tx["funding"], "funding")
        fee = _dec(tx["fee"], "fee")
        change = _dec(tx["change"], "change")
        balance = _dec(tx["cashBalance"], "cashBalance")
        if change != cf + funding - fee:
            raise ValueError("TRANSACTION_COMPONENT_MISMATCH")
        if cash is None:
            first_cash = balance - change
            cash = first_cash
        _approx(cash + change, balance, "WALLET_TRANSACTION_CHAIN", Decimal("0.00000001"))
        cash = balance
        fees += fee
        financing += funding
        if tx.get("type") == "TRADE":
            realized_cashflow += cf
        elif tx.get("type") in ("TRANSFER_IN", "TRANSFER_OUT"):
            transfers += cf
        elif cf:
            unknowns.append("UNATTRIBUTED_NONTRADE_CASHFLOW")
    if cash is None:
        unknowns.append("NO_USDT_TRANSACTION_BASELINE")
    if len({str(row.get("currency")) for row in transactions}) != 1:
        unknowns.append("MULTICURRENCY_TRANSACTION_UNSUPPORTED")

    exec_fees = sum((_dec(e["execFee"], "execFee") for e in trade_exec), Decimal(0))
    _approx(exec_fees, fees, "TOTAL_TRADING_FEES")
    exec_funding_costs = sum((_dec(e["execFee"], "funding_exec_fee") for e in funds_exec),
                             Decimal(0))
    _approx(exec_funding_costs, -financing, "TOTAL_FUNDING")
    if len(funds_exec) != len(settlement_transactions):
        unknowns.append("FUNDING_EVENT_COUNT_MISMATCH")

    # Independently replay linear USDT perpetual fills using weighted entry cost.
    inventory = avg = realized = Decimal(0)
    for e in trade_exec:
        qty = _dec(e["execQty"], "fill_qty")
        price = _dec(e["execPrice"], "fill_price")
        signed = qty if e["side"] == "Buy" else -qty
        if inventory == 0 or inventory * signed > 0:
            new_inv = inventory + signed
            avg = (abs(inventory) * avg + qty * price) / abs(new_inv)
            inventory = new_inv
        else:
            closed = min(abs(inventory), qty)
            realized += closed * (price - avg) * (Decimal(1) if inventory > 0 else Decimal(-1))
            remainder = inventory + signed
            if remainder == 0:
                inventory = avg = Decimal(0)
            elif inventory * remainder < 0:
                inventory = remainder
                avg = price
            else:
                inventory = remainder
    _approx(realized, realized_cashflow, "INDEPENDENT_REALIZED_PNL")

    snapshot = raw["snapshot"]
    positions = snapshot["positions"]
    if len(positions) != 1 or positions[0].get("symbol") != "BTCUSDT":
        unknowns.append("POSITION_UNIVERSE_NOT_SINGLE_BTC")
    elif positions[0].get("side") != ("Buy" if inventory > 0 else "Sell" if inventory < 0 else ""):
        raise ValueError("POSITION_SIDE_MISMATCH")
    elif abs(inventory) != _dec(positions[0]["size"], "snapshot_size"):
        raise ValueError("POSITION_SIZE_MISMATCH")
    if len(positions) == 1 and inventory:
        _approx(avg, _dec(positions[0]["avgPrice"], "avgPrice"), "ENTRY_PRICE", Decimal("0.01"))
        expected_upl = inventory * (_dec(positions[0]["markPrice"], "markPrice") - avg)
        _approx(expected_upl, _dec(positions[0]["unrealisedPnl"], "unrealisedPnl"),
                "UNREALIZED_PNL", Decimal("0.1"))
    else:
        expected_upl = None

    account_rows = snapshot["raw_wallet"]["result"].get("list", [])
    if len(account_rows) != 1 or account_rows[0].get("accountType") != "UNIFIED":
        raise ValueError("WALLET_ACCOUNT_SHAPE_INVALID")
    acc = account_rows[0]
    coins = acc.get("coin", [])
    if len(coins) != 1 or coins[0].get("coin") != "USDT":
        unknowns.append("MULTICURRENCY_ACCOUNT_WALLET_UNSUPPORTED")
    else:
        coin = coins[0]
        if cash is not None:
            _approx(cash, _dec(coin["walletBalance"], "walletBalance"), "USDT_WALLET_BALANCE")
        _approx(_dec(coin["walletBalance"], "walletBalance") +
                _dec(coin["unrealisedPnl"], "coin_unrealisedPnl"),
                _dec(coin["equity"], "coin_equity"), "USDT_EQUITY", Decimal("0.001"))
        _approx(_dec(acc["totalEquity"], "totalEquity"),
                _dec(coin["usdValue"], "usdValue"), "USD_EQUITY_VALUE", Decimal("0.001"))
    _approx(_dec(acc["totalWalletBalance"], "totalWalletBalance") +
            _dec(acc["totalPerpUPL"], "totalPerpUPL"),
            _dec(acc["totalEquity"], "totalEquity"), "USD_ACCOUNT_EQUITY", Decimal("0.001"))
    _approx(_dec(acc["totalEquity"], "totalEquity"),
            _dec(snapshot["total_equity_usd"], "snapshot_usd"), "SNAPSHOT_PARITY", Decimal("0.5"))
    if snapshot.get("open_orders"):
        unknowns.append("NONZERO_OPEN_ORDERS_AT_SNAPSHOT")
    start = manifest["interval_start"]
    end = manifest["interval_end"]
    observed = snapshot["snapshot_at"]
    # Snapshot is collected after the query window; do not assert a continuous
    # account state if a long unsampled gap could hide additional transactions.
    delay = (datetime.fromisoformat(observed) - datetime.fromisoformat(end)).total_seconds()
    if delay > 300:
        unknowns.append("SNAPSHOT_OUTSIDE_CAPTURE_WINDOW")

    economic_unknowns = set(unknowns)
    local_audit = (_local_journal(journal, manifest["account_uid_private"], set(order_map),
                                  start, end, sqlite_journal=sqlite_journal,
                                  drill_evidence=drill_evidence,
                                  waive_read_only_key=waive_read_only_key)
                   if journal is not None else None)
    if local_audit is None:
        unknowns.append("INTENT_ROUTING_JOURNAL_NOT_BOUND")
    else:
        unknowns.extend(local_audit["unknowns"])
    output = {
        "schema": "ats3_bybit_replay_v1",
        "least_privilege_audit_credential":
            "WAIVED_BY_OPERATOR" if waive_read_only_key else None,
        "status": "INSUFFICIENT_EVIDENCE",  # Full ATS-3 attribution still needs a frozen strategy baseline.
        "provider_economics": "RECONCILED" if not economic_unknowns else "RECONCILED_WITH_GAPS",
        "input_hashes_verified": True,
        "environment": "demo",
        "source_path": str(folder),
        "source_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "source_interval": [start, end],
        "trade_fills": len(trade_exec),
        "orders": len(orders),
        "local_intent_evidence": local_audit,
        "funding_events": len(funds_exec),
        "transactions": len(transactions),
        "duplicates_deduplicated": duplicates,
        "initial_wallet_usdt": str(first_cash),
        "external_transfers_usdt": str(transfers),
        "trading_fees_usdt": str(fees),
        "funding_usdt": str(financing),
        "realized_pnl_usdt": str(realized),
        "unrealized_pnl_usdt": str(expected_upl) if expected_upl is not None else None,
        "ending_wallet_usdt": str(cash) if cash is not None else None,
        "final_position_btc": str(inventory),
        "final_average_entry": str(avg),
        "coin_equity_usdt": str(coins[0]["equity"]) if len(coins) == 1 else None,
        "total_equity_usd": str(acc["totalEquity"]),
        "implied_usdt_usd_rate": str(_dec(coins[0]["usdValue"], "usdValue") /
                                     _dec(coins[0]["equity"], "equity")) if len(coins) == 1 else None,
        "unknowns": sorted(set(unknowns) | {
            "FROZEN_STRATEGY_BASELINE_NOT_LINKED", "DELIVERY_RECEIPT_NOT_VERIFIED",
            *(["AUDITOR_PRIVILEGE_BOUNDARY_NEEDS_VERIFICATION"] if manifest.get("collector_key_is_read_only") else
              ([] if waive_read_only_key else ["READ_ONLY_AUDIT_KEY_NOT_SEPARATE"]))}),
        "caveat": "Bybit USD conversion is provider-valued; the implied rate is not an independent market FX oracle."
                 + (" Operator waived separate read-only audit-key evidence." if waive_read_only_key else ""),
    }
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--journal", type=Path, default=None)
    parser.add_argument("--sqlite-journal", type=Path, default=None)
    parser.add_argument("--drill-evidence", type=Path, default=None)
    parser.add_argument("--waive-read-only-audit-key", action="store_true")
    parser.add_argument("--output", type=Path, default=None,
                        help="Private immutable JSON report; existing paths cannot be overwritten")
    args = parser.parse_args(argv)
    try:
        target: Path | None = None
        if args.output is not None:
            root = Path.home() / ".local" / "state" / "quant-research" / "ats3"
            target_path = args.output.resolve()
            if not target_path.is_relative_to(root.resolve()) or target_path.is_symlink() or target_path.exists():
                raise ValueError("OUTPUT_NOT_PRIVATE_OR_ALREADY_EXISTS")
            target = target_path
        report = reconcile_archive(args.archive, args.journal, sqlite_journal=args.sqlite_journal,
                                   drill_evidence=args.drill_evidence,
                                   waive_read_only_key=args.waive_read_only_audit_key)
        if args.output is not None and target is not None:
            encoded = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
            descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except (ValueError, KeyError, TypeError, OSError, ZeroDivisionError) as exc:
        print(json.dumps({"status": "CONFLICTING_EVIDENCE", "reason": str(exc)[:170]}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
