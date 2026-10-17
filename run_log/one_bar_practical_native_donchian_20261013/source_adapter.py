"""Source loader bridge used by the 2026-10-13 annual replay.

The frozen store has year/month/day/data.parquet partitions. The retained
annual runner's built-in file discovery expects monthly partitions, so the
replay installed these manifest-backed callables in memory. Strategy and
Engine code were not changed.
"""

import json
from pathlib import Path
from typing import Any


def install_source_adapter(runner: Any, output_dir: Path) -> None:
    """Install the frozen daily manifest loader on the annual runner."""
    output_dir = Path(output_dir)
    store = Path(runner.STORE)
    manifest = output_dir / "source_manifest.json"
    records = json.loads(manifest.read_text())
    paths = [store / row["path"] for row in records]

    def files_for_year(year: int) -> list[Path]:
        selected = []
        for path in paths:
            source_year = int(path.parents[2].name.split("=")[1])
            source_month = int(path.parents[1].name.split("=")[1])
            if (source_year == year
                    or (source_year == year - 1 and source_month == 12)
                    or (source_year == year + 1 and source_month == 1)):
                selected.append(path)
        return selected

    def source_files() -> list[Path]:
        return paths

    def verify_source() -> dict[str, object]:
        spec = json.loads((output_dir / "frozen_spec.json").read_text())
        expected_hash = spec["source"]["manifest_sha256"]
        if runner.sha256(manifest) != expected_hash:
            raise ValueError("Frozen daily source manifest hash mismatch")
        total_bytes = 0
        for path, row in zip(paths, records, strict=True):
            if (path.relative_to(store).as_posix() != row["path"]
                    or path.stat().st_size != row["size_bytes"]
                    or runner.sha256(path) != row["sha256"]):
                raise ValueError(f"Frozen daily source partition mismatch: {path}")
            total_bytes += row["size_bytes"]
        return {
            "manifest": str(manifest),
            "manifest_sha256": expected_hash,
            "partition_count": len(paths),
            "verified_bytes": total_bytes,
            "protected_after": spec["source"]["protected_after"],
            "all_partition_hashes_match": True,
        }

    runner.source_files = source_files
    runner.files_for_year = files_for_year
    runner.verify_source = verify_source
