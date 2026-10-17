"""Independent raw Bybit Demo evidence judge; imports no ATS-3 reconciliation code.

No network, broker imports, credentials or order capability. Fail closed on
economic inconsistencies. Writes only a private, aggregate verification report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import defaultdict
from decimal import Decimal
from pathlib import Path


def number(value: str) -> Decimal:
    item = Decimal(str(value))
    if not item.is_finite():
        raise ValueError("NONFINITE_PROVIDER_NUMBER")
    return item


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _intents_reconciled(path: Path | None) -> bool:
    if path is None or path.is_symlink() or not path.is_file():
        return False
    evidence = json.loads(path.read_text(encoding="utf-8"))
    local = evidence.get("local_intent_evidence", {})
    outcomes = local.get("reconciled_intents", [])
    documented = len(outcomes) + local.get("submitted_count", 0)
    return (local.get("intent_count") == 9 and documented == 9
            and local.get("unmatched_intent_count") == 0
            and not local.get("unknowns"))


def judge(directory: Path, *, waive_read_only_key: bool = False,
          intent_evidence: Path | None = None) -> dict:
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    require(manifest["environment"] == "demo" and manifest["status"] == "ARCHIVE_COMPLETE",
            "INVALID_DEMO_ARCHIVE")
    if waive_read_only_key:
        require(manifest.get("read_only_collector") is True,
                "COLLECTOR_NOT_STRICTLY_READ_ONLY")
        require(manifest.get("provider_host") == "api-demo.bybit.com",
                "WRONG_DEMO_ENDPOINT")
        require(str(manifest.get("account_uid_private")) == "593641111",
                "WRONG_DEMO_ACCOUNT")
        required_reads = {"orders", "executions", "transactions", "closed_pnl"}
        require(required_reads <= set(manifest.get("files", {})),
                "READ_ONLY_ENDPOINT_SET_INCOMPLETE")
    raw = {}
    for name in ("orders", "executions", "transactions", "snapshot"):
        info = manifest["files"][name]
        data = (directory / (name + ".json")).read_bytes()
        require(hashlib.sha256(data).hexdigest() == info["sha256"],
                "SOURCE_TAMPER:" + name)
        raw[name] = json.loads(data)

    trades = sorted([row for row in raw["executions"] if row["execType"] == "Trade"],
                    key=lambda row: (int(row["execTime"]), row["execId"]))
    funds = [r for r in raw["executions"] if r["execType"] == "Funding"]
    require(len({t["execId"] for t in raw["executions"]}) == len(raw["executions"]),
            "DUPLICATE_EXECUTION_ID")

    order_fills: dict[str, Decimal] = defaultdict(Decimal)
    position: Decimal = Decimal(0)
    avg_price: Decimal = Decimal(0)
    realized = Decimal(0)
    for fill in trades:
        require(fill["symbol"] == "BTCUSDT", "UNSUPPORTED_INSTRUMENT")
        qty = number(fill["execQty"])
        px = number(fill["execPrice"])
        require(qty > 0 and px > 0 and fill["side"] in ("Buy", "Sell"),
                "BAD_PROVIDER_FILL")
        order_fills[fill["orderId"]] += qty
        signed = qty if fill["side"] == "Buy" else -qty
        if position == 0 or position * signed > 0:
            next_position = position + signed
            avg_price = (abs(position) * avg_price + qty * px) / abs(next_position)
            position = next_position
        else:
            close_quantity = min(abs(position), qty)
            realized += close_quantity * (px - avg_price) * (1 if position > 0 else -1)
            next_position = position + signed
            if next_position == 0:
                avg_price = Decimal(0)
            elif position * next_position < 0:
                avg_price = px
            position = next_position
    for order in raw["orders"]:
        require(number(order["cumExecQty"]) == order_fills[order["orderId"]],
                "INDEPENDENT_ORDER_FILL_MISMATCH")

    transactions = sorted(raw["transactions"],
                          key=lambda row: (int(row["transactionTime"]), row["id"]))
    require(len({row["id"] for row in transactions}) == len(transactions),
            "DUPLICATE_TRANSACTION_ID")
    previous: Decimal | None = None
    opening: Decimal | None = None
    paid_fees = Decimal(0)
    signed_funding = Decimal(0)
    realized_from_cashflow = Decimal(0)
    transfers = Decimal(0)
    for tx in transactions:
        require(tx["currency"] == "USDT", "FOREIGN_CURRENCY_UNSUPPORTED")
        change = number(tx["change"])
        cash_flow = number(tx["cashFlow"])
        fee = number(tx["fee"])
        funding = number(tx["funding"])
        require(change == cash_flow + funding - fee, "TRANSACTION_COMPONENT_MISMATCH")
        observed = number(tx["cashBalance"])
        if previous is None:
            opening = observed - change
            previous = opening
        require(previous + change == observed, "INDEPENDENT_TRANSACTION_BALANCE_MISMATCH")
        previous = observed
        paid_fees += fee
        signed_funding += funding
        if tx["type"] == "TRADE":
            realized_from_cashflow += cash_flow
        if tx["type"] in ("TRANSFER_IN", "TRANSFER_OUT"):
            transfers += cash_flow
    require(opening is not None and previous is not None, "NO_TRANSACTION_BASELINE")
    require(realized_from_cashflow == realized, "INDEPENDENT_REALIZED_PNL_MISMATCH")
    require(paid_fees == sum((number(t["execFee"]) for t in trades), Decimal(0)),
            "INDEPENDENT_COMMISSION_MISMATCH")
    require(-signed_funding == sum((number(t["execFee"]) for t in funds), Decimal(0)),
            "INDEPENDENT_FUNDING_MISMATCH")

    wallet = raw["snapshot"]["raw_wallet"]["result"]["list"][0]
    require(wallet["accountType"] == "UNIFIED", "NOT_UNIFIED_ACCOUNT")
    coin = wallet["coin"]
    require(len(coin) == 1 and coin[0]["coin"] == "USDT", "MULTI_COIN_NOT_SUPPORTED")
    pos = raw["snapshot"]["positions"]
    require(len(pos) == 1 and pos[0]["symbol"] == "BTCUSDT", "NON_BTC_POSITION")
    require(position == number(pos[0]["size"]), "INDEPENDENT_POSITION_MISMATCH")
    require(abs(avg_price - number(pos[0]["avgPrice"])) < Decimal("0.01"),
            "INDEPENDENT_ENTRY_PRICE_MISMATCH")
    upl = position * (number(pos[0]["markPrice"]) - avg_price)
    require(abs(upl - number(pos[0]["unrealisedPnl"])) < Decimal("0.1"),
            "INDEPENDENT_MARK_PNL_MISMATCH")
    require(previous == number(coin[0]["walletBalance"]),
            "INDEPENDENT_END_CASH_MISMATCH")
    require(number(coin[0]["walletBalance"]) + number(coin[0]["unrealisedPnl"])
            == number(coin[0]["equity"]), "INDEPENDENT_USDT_EQUITY_MISMATCH")
    require(abs(number(wallet["totalEquity"]) - number(coin[0]["usdValue"]))
            < Decimal("0.001"), "INDEPENDENT_USD_CONVERSION_MISMATCH")
    require(abs(number(wallet["totalWalletBalance"]) + number(wallet["totalPerpUPL"])
                - number(wallet["totalEquity"])) < Decimal("0.001"),
            "INDEPENDENT_WALLET_COMPONENT_MISMATCH")
    return {
        "status": "INDEPENDENT_BROKER_ECONOMICS_PASS",
        "full_ats3_qualified": False,
        "source_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "orders": len(raw["orders"]), "trade_fills": len(trades),
        "funding_events": len(funds), "transactions": len(transactions),
        "initial_wallet_usdt": str(opening),
        "transfers_usdt": str(transfers),
        "trading_fees_usdt": str(paid_fees),
        "funding_usdt": str(signed_funding),
        "realized_pnl_usdt": str(realized),
        "ending_wallet_usdt": str(previous),
        "open_position_btc": str(position),
        "unrealized_pnl_usdt": str(upl),
        "provider_equity_usd": str(wallet["totalEquity"]),
        "audit_credential_status": "WAIVED_BY_OPERATOR" if waive_read_only_key else
                                   ("READ_ONLY" if manifest.get("collector_key_is_read_only") else "UNVERIFIED"),
        "intent_dispositions_reconciled": _intents_reconciled(intent_evidence),
        "caveat": "Provider USD collateral valuation is checked for arithmetic, not externally priced.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--waive-read-only-audit-key", action="store_true")
    parser.add_argument("--intent-evidence", type=Path, default=None)
    args = parser.parse_args()
    try:
        result = judge(args.archive.resolve(strict=True),
                       waive_read_only_key=args.waive_read_only_audit_key,
                       intent_evidence=args.intent_evidence)
        if args.output:
            target = args.output.resolve()
            if target.exists() or not target.parent.is_dir():
                raise ValueError("OUTPUT_EXISTS_OR_PARENT_MISSING")
            descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "INDEPENDENT_BROKER_ECONOMICS_FAIL",
                          "reason": type(exc).__name__ + ":" + str(exc)[:150]}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
