#!/usr/bin/env python3
"""Copy immutable one-bar evidence and completed annual slices into this package."""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def copy_file(source: Path, destination: Path, records: dict[str, dict]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    before = sha256(source)
    shutil.copy2(source, destination)
    copied = sha256(destination)
    after = sha256(source)
    if before != copied or copied != after:
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"Source changed while copying: {source}")
    records[destination.relative_to(PACKAGE).as_posix()] = {
        "sha256": copied,
        "source": source.relative_to(ROOT).as_posix(),
        "source_sha256": after,
    }


def copy_tree(source: Path, destination: Path, records: dict[str, dict]) -> None:
    for path in sorted(source.rglob("*")):
        if any(part.startswith("superseded_") for part in path.relative_to(source).parts):
            continue
        if not path.is_file() or path.suffix in {".log", ".sh"} or path.name in {"agent.log", "timing_agent.log"}:
            continue
        copy_file(path, destination / path.relative_to(source), records)


def completed_years(ledger: dict) -> list[int]:
    running = next((item for item in ledger.get("attempts", [])
                    if item.get("years") and item.get("status") in {"RUNNING", "completed", "COMPLETED"}), None)
    years = []
    if running is None:
        return years
    for item in running.get("years", []):
        year = item.get("year")
        names = {trial.get("name"): trial.get("status") for trial in item.get("trials", [])}
        source = ROOT / "run_log/one_bar_practical_1m_20261012/by_year" / str(year)
        summary = source / "year_summary.json"
        if (item.get("status") == "completed" and names.get("native_zero_cost") == "completed"
                and names.get("native_full_tick_cost") == "completed" and summary.is_file()
                and json.loads(summary.read_text()).get("status") == "completed"):
            required = [source / trial / filename for trial in ("native_zero_cost", "native_full_tick_cost")
                        for filename in ("metrics.json", "trades.csv", "fills.csv", "daily_equity.csv")]
            if all(path.is_file() for path in required):
                years.append(int(year))
    return years


def main() -> None:
    records: dict[str, dict] = {}
    source_files = {
        "src/run_one_bar_50breakout_20261011.py": "scripts/run_one_bar_50breakout_20261011.py",
        "src/run_one_bar_dukascopy_2013_2026_20261011.py": "scripts/run_one_bar_dukascopy_2013_2026_20261011.py",
        "src/run_one_bar_dukascopy_phase567_20261011.py": "scripts/run_one_bar_dukascopy_phase567_20261011.py",
        "src/run_one_bar_execution_remediation_20261012.py": "scripts/run_one_bar_execution_remediation_20261012.py",
        "src/run_one_bar_practical_1m_20261012.py": "scripts/run_one_bar_practical_1m_20261012.py",
        "src/run_one_bar_practical_yearly_20261012.py": "scripts/run_one_bar_practical_yearly_20261012.py",
        "tests/test_one_bar_50breakout_20261011.py": "tests/test_one_bar_50breakout_20261011.py",
        "tests/test_one_bar_dukascopy_2013_2026_20261011.py": "tests/test_one_bar_dukascopy_2013_2026_20261011.py",
        "tests/test_one_bar_dukascopy_phase567_20261011.py": "tests/test_one_bar_dukascopy_phase567_20261011.py",
        "tests/test_one_bar_execution_remediation_20261012.py": "tests/test_one_bar_execution_remediation_20261012.py",
        "tests/test_one_bar_practical_yearly_20261012.py": "tests/test_one_bar_practical_yearly_20261012.py",
    }
    for target, original in source_files.items():
        copy_file(ROOT / original, PACKAGE / target, records)

    runs = {
        "backtests/lse_2026": "run_log/one_bar_50breakout_20261011",
        "backtests/dukascopy_long_history": "run_log/one_bar_dukascopy_2013_2026_20261011",
        "backtests/phase567": "run_log/one_bar_dukascopy_phase567_20261011",
        "backtests/remediation": "run_log/one_bar_execution_remediation_20261012",
    }
    for target, original in runs.items():
        copy_tree(ROOT / original, PACKAGE / target, records)

    yearly_root = ROOT / "run_log/one_bar_practical_1m_20261012"
    ledger = json.loads((yearly_root / "trial_ledger.json").read_text())
    for name in ("frozen_spec.json", "recovery_spec.json", "trial_ledger.json"):
        path = yearly_root / name
        if path.is_file():
            copy_file(path, PACKAGE / "backtests/practical_yearly" / name, records)
    for relative in ("validation", "errors"):
        for path in (yearly_root / relative).rglob("*"):
            if path.is_file():
                copy_file(path, PACKAGE / "backtests/practical_yearly" / path.relative_to(yearly_root), records)
    for year in completed_years(ledger):
        copy_tree(yearly_root / "by_year" / str(year), PACKAGE / "backtests/practical_yearly/by_year" / str(year), records)

    for original in (
        "docs/audit/one_bar_50breakout_20261011_plan.md",
        "docs/audit/one_bar_50breakout_20261011_independent_review.md",
        "docs/audit/one_bar_dukascopy_2013_2026_20261011.md",
        "docs/audit/one_bar_dukascopy_2013_2026_20261011_independent_review.md",
        "docs/audit/one_bar_dukascopy_phase567_20261011.md",
        "docs/audit/one_bar_dukascopy_phase567_20261011_independent.md",
        "docs/audit/one_bar_execution_remediation_20261012.md",
        "run_log/one_bar_50breakout_20261011_mission.md",
        "run_log/one_bar_dukascopy_2013_2026_20261011_mission.md",
        "run_log/one_bar_dukascopy_phase567_20261011_mission.md",
        "run_log/one_bar_execution_remediation_20261012_mission.md",
        "run_log/one_bar_execution_remediation_20261012_timing_review.md",
        "run_log/one_bar_practical_1m_20261012_mission.md",
        "run_log/one_bar_practical_1m_20261012_recovery_mission.md",
    ):
        source = ROOT / original
        if source.is_file():
            copy_file(source, PACKAGE / "audits" / Path(original).name, records)

    for path in sorted(PACKAGE.rglob("*")):
        if path.is_file() and path.relative_to(PACKAGE).as_posix() not in records and path.name != "manifest.json":
            records[path.relative_to(PACKAGE).as_posix()] = {"sha256": sha256(path), "source": None}
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_git_head": __import__("subprocess").check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "package_root": "promote/one_bar_nq_30m",
        "file_count_excluding_manifest": len(records),
        "files": records,
        "external_references": {
            "canonical_market_data": "/home/quant/dev/quant/ml4t-data/.data/store/index_minute_NQ",
            "excluded_superseded_attempts": [
                "run_log/one_bar_dukascopy_2013_2026_20261011/superseded_wall_clock_attempt",
                "run_log/one_bar_dukascopy_phase567_20261011/superseded_duplicate_oco_diagnostics",
                "run_log/one_bar_dukascopy_phase567_20261011/superseded_pre_oco_cap_accounting",
            ],
        },
        "copied_completed_practical_years": completed_years(ledger),
    }
    annual_status = ledger.get("status", "UNKNOWN")
    active = next((item for item in ledger.get("attempts", [])
                   if item.get("years") and item.get("status") in {"RUNNING", "completed", "COMPLETED"}), None)
    completed = completed_years(ledger)
    pending = [year for year in range(2013, 2027) if year not in completed]
    status_text = (
        "# Packaging status snapshot\n\n"
        f"Captured at {datetime.now(timezone.utc).isoformat()}. The source annual ledger status is `{annual_status}`.\n\n"
        f"Annual trial: `{active.get('trial_id') if active else 'none'}` (`{active.get('status') if active else 'unknown'}`).\n\n"
        f"Completed annual outputs copied: {', '.join(map(str, completed)) or 'none'}. Each copied year has a completed summary and both completed trial ledgers.\n\n"
        f"Years not copied: {', '.join(map(str, pending)) or 'none'}. The package excludes every year without a completed summary and both complete trial output sets.\n\n"
        "The canonical yearly runner and output directory were not edited or moved. Re-run `python promote/one_bar_nq_30m/scripts/refresh_completed_runs.py` after completion to add newly completed years.\n"
    )
    (PACKAGE / "STATUS.md").write_text(status_text)
    records["STATUS.md"] = {"sha256": sha256(PACKAGE / "STATUS.md"), "source": None}
    (PACKAGE / "provenance").mkdir(exist_ok=True)
    (PACKAGE / "provenance/manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"Copied {len(records)} files; annual completed years: {manifest['copied_completed_practical_years']}")


if __name__ == "__main__":
    main()
