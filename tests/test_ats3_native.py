"""Real saved native records, independent arithmetic, and adversarial integrity checks."""
from pathlib import Path

import polars as pl
import pytest

from src.research_control.ats3_native import audit_native

SAMPLE = Path("/home/quant/.devspace/worktrees/quant-research-25440f7a/run_log/dual_mode_runtime_smoke/20261016T075418661458")


def test_actual_native_accounting_and_independent_arithmetic():
    if not SAMPLE.is_dir():
        pytest.skip("External saved native evidence unavailable")
    result = audit_native(SAMPLE)
    assert result["authority"] == "ML4T_NATIVE_SIMULATION_NOT_BROKER"
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["comparison"]["numerical_status"] == "PASS"
    assert abs(result["comparison"]["difference"]) < 1e-6
    assert "BROKER_EXECUTION_NOT_OBSERVED" in result["unknowns"]
    assert any("ACK_UNKNOWN" in x for x in result["unknowns"])
    fills = pl.read_parquet(SAMPLE / "fills.parquet")
    funding = pl.read_parquet(SAMPLE / "funding.parquet")
    starting = pl.read_parquet(SAMPLE / "equity.parquet")["equity"][0]
    # Independent signed trading-cash formula, no use of the ATS-3 projector.
    cash = starting
    for fill in fills.iter_rows(named=True):
        direction = 1 if fill["side"] == "buy" else -1
        cash -= direction * fill["quantity"] * fill["price"] + fill["commission"]
    cash += funding["cashflow"].sum()
    assert abs(cash - result["comparison"]["reconstructed_final_cash"]) < 1e-6


def test_corrupted_fill_changes_cash_and_fails_against_native_equity(tmp_path):
    if not SAMPLE.is_dir():
        pytest.skip("External saved native evidence unavailable")
    for name in ("fills", "funding", "equity"):
        (tmp_path / (name + ".parquet")).write_bytes((SAMPLE / (name + ".parquet")).read_bytes())
    fills = pl.read_parquet(tmp_path / "fills.parquet")
    qty = fills["quantity"].to_list()
    qty[0] += 0.1
    fills.with_columns(pl.Series("quantity", qty)).write_parquet(tmp_path / "fills.parquet")
    result = audit_native(tmp_path)
    # The adapter never reports VERIFIED for gaps, so the meaningful check is
    # that the reconstructed cash disagrees with the native ending equity.
    assert result["comparison"].get("numerical_status") != "PASS"


def test_missing_native_authority_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="NATIVE_AUTHORITY_MISSING"):
        audit_native(tmp_path)


def _snapshot(directory: Path) -> dict:
    state = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            stat = path.stat()
            state[str(path.relative_to(directory))] = (
                stat.st_mtime_ns, stat.st_size, path.read_bytes()[:64])
        elif path.is_dir():
            state[str(path.relative_to(directory)) + "/"] = None
    return state


def test_projection_never_writes_and_is_deterministic(tmp_path):
    if not SAMPLE.is_dir():
        pytest.skip("External saved native evidence unavailable")
    target = tmp_path / "sample"
    target.mkdir()
    for name in ("fills", "funding", "equity"):
        (target / (name + ".parquet")).write_bytes((SAMPLE / (name + ".parquet")).read_bytes())
    before = _snapshot(target)
    first = audit_native(target)
    second = audit_native(target)
    assert first["provenance"] == second["provenance"]
    assert first["comparison"]["difference"] == second["comparison"]["difference"]
    assert _snapshot(target) == before
