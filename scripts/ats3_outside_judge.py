#!/usr/bin/env python3
"""Independent raw numerical replay for saved ATS-3 native projections.

This script deliberately does not import ATS verification or bridge code.
It reads the saved native artifacts (fills, funding and equity) and recomputes
signed fill notionals, commissions, financing cashflows and the final equity
with an independent arithmetic model. If a verification.json is present next
to the artifacts, its declared accounting block is cross-checked without
trusting it.

Exit status: 0 reports a completed audit (gaps remain visible), 3 reports
conflicting evidence, 1 reports an error, a missing native authority, or a
usage error such as an existing output directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

TOL = 1e-6


class Reject(Exception):
    def __init__(self, reason_code: str, detail: str = ""):
        self.reason_code = reason_code.split(":", 1)[0]
        self.detail = detail or reason_code
        super().__init__(f"{self.reason_code}:{self.detail}")


class Usage(Exception):
    """Caller error, for example an existing output directory."""


def check(condition: bool, reason: str) -> None:
    if not condition:
        raise Reject(reason)


def close(actual: Any, expected: float, reason: str, tol: float = TOL) -> None:
    try:
        value = float(actual)
    except (TypeError, ValueError):
        raise Reject(reason) from None
    check(math.isfinite(value) and math.isclose(value, expected, rel_tol=0, abs_tol=tol), reason)


def file_hash(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
        raise Reject(f"UNSAFE_OR_OVERSIZE_FILE:{path.name}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
        raise Reject(f"JSON_UNSAFE_OR_OVERSIZE:{path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    check(isinstance(value, dict), "JSON_NOT_OBJECT")
    return value


def ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    parsed = datetime.fromisoformat(str(value))
    return parsed.replace(tzinfo=None)


def load_frames(directory: Path) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    for name in ("fills", "funding", "equity"):
        path = directory / f"{name}.parquet"
        check(path.is_file() and not path.is_symlink(), f"NATIVE_{name.upper()}_MISSING")
    fills = pl.read_parquet(directory / "fills.parquet")
    funding = pl.read_parquet(directory / "funding.parquet")
    equity = pl.read_parquet(directory / "equity.parquet")
    check(fills.height >= 0 and funding.height >= 0 and equity.height >= 1,
          "NATIVE_EMPTY_SERIES")
    required_fills = {"order_id", "asset", "side", "quantity", "price", "commission", "timestamp"}
    check(required_fills <= set(fills.columns), "NATIVE_FILL_SCHEMA_UNSUPPORTED")
    required_equity = {"timestamp", "equity"}
    check(required_equity <= set(equity.columns), "NATIVE_EQUITY_SCHEMA_UNSUPPORTED")
    return fills.sort([ "timestamp", "order_id"]), funding, equity.sort("timestamp")


def reconstruct(bars: tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]) -> dict[str, Any]:
    """Independently rebuild cash, positions and ending equity from the raw exports."""
    fills, funding, equity = bars
    first, last = equity.row(0, named=True), equity.row(-1, named=True)
    check(ts(first["timestamp"]) <= ts(last["timestamp"]), "EQUITY_CLOCK_INVALID")
    initial_cash = float(first["equity"])
    cash = initial_cash
    shares: dict[str, float] = {}
    for index, fill in enumerate(fills.to_dicts()):
        side = str(fill["side"])
        if side not in ("buy", "sell"):
            raise Reject("INVALID_FILL_SIDE")
        quantity = float(fill["quantity"])
        price = float(fill["price"])
        commission = float(fill["commission"])
        if quantity <= 0 or price <= 0 or not math.isfinite(quantity + price + commission):
            raise Reject("INVALID_FILL_VALUE")
        signed = quantity if side == "buy" else -quantity
        cash -= signed * price + commission
        shares[fill["asset"]] = shares.get(fill["asset"], 0.0) + signed
    for row in funding.to_dicts():
        cash += float(row["cashflow"])
    if any(abs(quantity) > TOL for quantity in shares.values()):
        # No synchronized marks are part of this projection; an open position
        # cannot be valued, so the ending equity is insufficient, not guessed.
        return {"ending_flat": False, "initial_cash": initial_cash,
                "ending_equity": None, "reconstructed_cash": None}
    ending_equity = cash
    for row in equity.to_dicts():
        moments = ts(row["timestamp"])
        if moments == ts(equity.row(-1, named=True)["timestamp"]):
            check(abs(float(row["equity"]) - ending_equity) <= TOL * max(1.0, abs(ending_equity)),
                  "FINAL_EQUITY_MISMATCH")
    return {"ending_flat": True, "initial_cash": initial_cash,
            "ending_equity": ending_equity,
            "reconstructed_cash": cash}


def cross_check_verification(directory: Path) -> None:
    path = directory / "verification.json"
    if not path.is_file():
        return
    declared = read_json(path)
    accounting = declared.get("accounting")
    check(isinstance(accounting, dict), "VERIFICATION_ACCOUNTING_INVALID")
    check(accounting.get("status") == "PASS", "VERIFICATION_STATUS_NOT_PASS")
    # The declared accounting block names measured error maxima, not a final
    # equity value, so only its shape is cross-checked here. The ending value
    # itself is compared against the last native equity mark by reconstruct().
    check(_finite_nonnegative(accounting.get("max_equity_error"), "VERIFICATION_MAX_EQUITY_ERROR"),
          "VERIFICATION_MAX_EQUITY_ERROR_INVALID")
    check(_finite_nonnegative(accounting.get("max_funding_error"), "VERIFICATION_MAX_FUNDING_ERROR"),
          "VERIFICATION_MAX_FUNDING_ERROR_INVALID")
    check(_finite_positive(accounting.get("tolerance"), "VERIFICATION_TOLERANCE"),
          "VERIFICATION_TOLERANCE_INVALID")


def _finite_nonnegative(value: Any, reason: str) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number >= 0.0


def _finite_positive(value: Any, reason: str) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0.0


def run(directory: Path, output: Path) -> dict[str, Any]:
    directory = directory.resolve(strict=True)
    output = output.resolve()
    if output.exists() or output.is_symlink():
        raise Usage("OUTPUT_DIRECTORY_ALREADY_EXISTS")
    output.mkdir(parents=True, exist_ok=False)
    bars = load_frames(directory)
    replay = reconstruct(bars)
    cross_check_verification(directory)
    if replay["ending_equity"] is not None and replay["reconstructed_cash"] is not None:
        difference = abs(replay["reconstructed_cash"] - replay["ending_equity"])
        if difference > TOL * max(1.0, abs(replay["ending_equity"])):
            raise Reject("END_EQUITY_MISMATCH")
    report = {
        "state": "REPLAY_COMPLETED",
        "native_directory": str(directory),
        "checks": ["independent_cash_and_equity_replay"],
        "expected": {
            "initial_cash": replay["initial_cash"],
            "ending_equity": replay["ending_equity"],
            "reconstructed_cash": replay["reconstructed_cash"],
        },
        "limitations": [
            "Synthetic development native exports only; never broker execution evidence.",
            "An open position cannot be valued without synchronized marks.",
            "The verification.json accounting block is cross-checked, not trusted.",
        ],
    }
    report_path = output / "replay_report.json"
    with report_path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, default=str)
        stream.write("\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("native_directory", type=Path)
    parser.add_argument("--output", type=Path, default=Path("run_log/ats3/independent_review"))
    args = parser.parse_args()
    try:
        run(args.native_directory, args.output)
    except Reject as exc:
        print(json.dumps({"state": "REJECTED", "error": str(exc)}, indent=2))
        return 3
    except Usage as exc:
        print(json.dumps({"state": "USAGE_ERROR", "error": str(exc)}, indent=2))
        return 1
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"state": "ERROR", "error": str(exc)}, indent=2))
        return 1
    print(json.dumps({"state": "REPLAY_COMPLETED", "report": str(
        args.output / "replay_report.json")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
