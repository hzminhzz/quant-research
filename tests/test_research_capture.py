from __future__ import annotations

import json
import stat
import warnings
import zipfile
from pathlib import Path

import pytest

from src.engine.common import QuantError, digest, file_hash
from src.engine.research_capture import capture_archive, capture_source, verify_capture

ROOT = Path(__file__).resolve().parents[1]
IDS = (
    "audusd_policy_carry_cfd_v1",
    "dax_monthend_liquidity_rebound_cfd_20261015_v1",
    "fomc_overnight_uncertainty_premium_us500_cfd_20261015_v1",
    "gbpusd_weekend_gap_reversal_cfd_20261015_v1",
    "hanna_spy_bear_gap_fade_us500_cfd_20261017_1600_v1",
    "oil_to_cad_daily_delayed_adjustment_20261015_v1",
    "us500_european_open_uncertainty_resolution_cfd_v1",
)


def test_published_handoffs_capture_without_executable_promotion(tmp_path):
    results = [capture_source(ROOT / "research_inbox" / name, tmp_path / "captures") for name in IDS]
    assert len(results) == 7
    assert all(item.status == "THESIS_CAPTURED" and not item.executable for item in results)
    assert all(item.unresolved for item in results)
    assert all(verify_capture(item.report_path)["executable"] is False for item in results)


def test_nested_placeholder_blocks_readiness_and_bytes_are_preserved(tmp_path):
    source = tmp_path / "thesis.yaml"
    source.write_text("economic_thesis:\n  claim: meaningful\n  caveat: TBD\n")
    result = capture_source(source, tmp_path / "out")
    assert result.status == "THESIS_CAPTURED"
    data = json.loads(Path(result.report_path).read_text())
    archived = Path(data["provenance"]["preserved_source_bytes"]["thesis.yaml"]["path"])
    assert archived.read_bytes() == source.read_bytes()


def test_report_and_source_tampering_are_detected(tmp_path):
    source = tmp_path / "thesis.yaml"
    source.write_text("economic_thesis: claim\n")
    result = capture_source(source, tmp_path / "out")
    report = Path(result.report_path)
    doc = json.loads(report.read_text())
    doc["status"] = "RESEARCH_READY"
    report.write_text(json.dumps(doc))
    with pytest.raises(QuantError, match="report was modified"):
        verify_capture(report)


def test_existing_report_is_not_overwritten(tmp_path):
    source = tmp_path / "thesis.txt"
    source.write_text("hypothesis")
    first = capture_source(source, tmp_path / "out")
    report = Path(first.report_path)
    report.write_text("{}")
    with pytest.raises(QuantError, match="modified"):
        capture_source(source, tmp_path / "out")


@pytest.mark.parametrize("contents", ["a: 1\na: 2\n", "!!python/object/apply:os.system ['echo bad']\n"])
def test_yaml_rejects_duplicate_keys_and_unsafe_tags(tmp_path, contents):
    source = tmp_path / "bad.yaml"
    source.write_text(contents)
    with pytest.raises(QuantError):
        capture_source(source, tmp_path / "out")


def test_archive_and_symlink_rejected(tmp_path):
    archive = tmp_path / "payload.zip"
    archive.write_bytes(b"not even a zip")
    with pytest.raises(QuantError, match="archive"):
        capture_source(archive, tmp_path / "out")
    source = tmp_path / "good.txt"
    source.write_text("text")
    link = tmp_path / "link.txt"
    link.symlink_to(source)
    with pytest.raises(QuantError, match="symlink"):
        capture_source(link, tmp_path / "out")


def _zip(path: Path, members: list[tuple[str, bytes | zipfile.ZipInfo]]) -> Path:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, value in members:
                if isinstance(value, zipfile.ZipInfo):
                    archive.writestr(value, b"link-target")
                else:
                    archive.writestr(name, value)
    return path


def _nested_pair(folder: str, candidate: str) -> list[tuple[str, bytes]]:
    thesis = "\n".join([
        "identity:", f"  candidate_id: {candidate}",
        "  thesis: Monthly rebalancing may capture a persistent risk premium.",
        "markets_and_data:", "  instruments:", "    symbols: [ABC]",
        "  required_sources:", "    - timestamp", "    - close",
        "deterministic_strategy_specification:", "  entry: prior session close",
        "  exit: month end", "  stop: TBD", "",
    ]).encode()
    brief = f"# {candidate}\nA descriptive research handoff.\n".encode()
    return [(f"{folder}/thesis.yaml", thesis), (f"{folder}/brief.md", brief)]


def test_zip_archive_captures_all_nested_hypotheses_with_field_evidence(tmp_path):
    archive = _zip(tmp_path / "all.zip", _nested_pair("cycle_a", "nested_a")
                   + _nested_pair("cycle_b", "nested_b"))
    results = capture_archive(archive, tmp_path / "out")
    assert [item.candidate_id for item in results] == ["nested_a", "nested_b"]
    assert all(item.status == "THESIS_CAPTURED" and not item.executable for item in results)
    for result in results:
        report = json.loads(Path(result.report_path).read_text())
        evidence = report["provenance"]["nested_field_evidence"]
        assert "identity.thesis" in evidence
        assert "markets_and_data.instruments" in evidence
        assert any(clause["clause"] == "economic_thesis" and clause["present"]
                   and not clause["resolved"] and "semantic equivalence" in clause["unresolved_reason"]
                   for clause in report["clauses"])
        assert verify_capture(result.report_path)["executable"] is False
    archive_hash = results[0].provenance["archive_sha256"]
    assert (tmp_path / "out" / "archives" / f"{archive_hash}.zip").read_bytes() == archive.read_bytes()


def test_zip_archive_captures_all_62_folder_pairs(tmp_path):
    members = []
    for index in range(62):
        members.extend(_nested_pair(f"cycle_{index:02}", f"candidate_{index:02}"))
    results = capture_archive(_zip(tmp_path / "62.zip", members), tmp_path / "out")
    assert len(results) == 62
    assert {item.candidate_id for item in results} == {f"candidate_{index:02}" for index in range(62)}
    assert all(item.status == "THESIS_CAPTURED" for item in results)


@pytest.mark.parametrize("kind", ["traversal", "duplicate", "symlink", "bomb", "utf8", "large", "incomplete"])
def test_zip_rejects_all_unsafe_batches_before_writing(tmp_path, kind):
    pair = _nested_pair("bad", "bad")
    if kind == "traversal":
        pair = [("../bad/thesis.yaml", pair[0][1]), ("../bad/brief.md", pair[1][1])]
    elif kind == "duplicate":
        pair = pair + [pair[0]]
    elif kind == "symlink":
        link = zipfile.ZipInfo("bad/thesis.yaml")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        pair = [(link.filename, link), pair[1]]
    elif kind == "bomb":
        pair = [(pair[0][0], b"A" * 100_000), pair[1]]
    elif kind == "utf8":
        pair = [pair[0], (pair[1][0], b"\xff\xfe")]
    elif kind == "large":
        pair = [(pair[0][0], b"x" * (512_000 + 1)), pair[1]]
    elif kind == "incomplete":
        pair = pair[:1]
    archive = _zip(tmp_path / f"{kind}.zip", pair)
    out = tmp_path / f"out-{kind}"
    with pytest.raises(QuantError):
        capture_archive(archive, out)
    assert not (out / "archives").exists()
    assert not (out / "archive_sources").exists()


def test_zip_rejects_casefold_duplicate(tmp_path):
    pair = _nested_pair("same", "same")
    archive = _zip(tmp_path / "duplicate.zip", pair + [("SAME/thesis.yaml", pair[0][1])])
    with pytest.raises(QuantError, match="duplicate"):
        capture_archive(archive, tmp_path / "out")


@pytest.mark.parametrize("limit, value", [
    ("_MAX_ARCHIVE_BYTES", 10),
    ("_MAX_ARCHIVE_FILES", 1),
    ("_MAX_ARCHIVE_TOTAL_BYTES", 10),
])
def test_zip_archive_wide_limits_are_enforced(tmp_path, monkeypatch, limit, value):
    import src.engine.research_capture as capture

    archive = _zip(tmp_path / "limited.zip", _nested_pair("cycle", "candidate"))
    monkeypatch.setattr(capture, limit, value)
    with pytest.raises(QuantError, match="limit|size|many"):
        capture.capture_archive(archive, tmp_path / "out")
    assert not (tmp_path / "out" / "archives").exists()


def test_zip_rejects_unsupported_compression(tmp_path):
    archive = tmp_path / "bzip2.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_BZIP2) as target:
        for name, data in _nested_pair("cycle", "candidate"):
            target.writestr(name, data)
    with pytest.raises(QuantError, match="unsupported ZIP compression"):
        capture_archive(archive, tmp_path / "out")


def test_default_output_does_not_mutate_source_and_repeated_capture_is_idempotent(tmp_path):
    handoff = tmp_path / "candidate"
    handoff.mkdir()
    (handoff / "thesis.yaml").write_text("candidate_id: safe_candidate\neconomic_thesis: test\n")
    (handoff / "brief.md").write_text("# Safe candidate\n")
    first = capture_source(handoff)
    second = capture_source(handoff)
    assert first.report_path == second.report_path
    assert first.captured_at == second.captured_at
    assert {item.name for item in handoff.iterdir()} == {"thesis.yaml", "brief.md"}
    assert verify_capture(second.report_path)["status"] == "THESIS_CAPTURED"


def test_capture_rejects_extra_directory_without_losing_evidence(tmp_path):
    source = tmp_path / "thesis"
    source.mkdir()
    (source / "thesis.yaml").write_text("economic_thesis: documented\n")
    (source / "brief.md").write_text("# Documentation\n")
    (source / "attachments").mkdir()
    with pytest.raises(QuantError, match="unexpected entries"):
        capture_source(source, tmp_path / "out")


def test_symlinked_archive_output_components_are_rejected(tmp_path):
    archive = _zip(tmp_path / "theses.zip", _nested_pair("cycle", "candidate"))
    output = tmp_path / "out"
    output.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (output / "archives").symlink_to(outside, target_is_directory=True)
    with pytest.raises(QuantError, match="symlinked output"):
        capture_archive(archive, output)
    assert not list(outside.iterdir())


def test_external_report_pin_detects_rehashed_status_tampering(tmp_path):
    source = tmp_path / "thesis.txt"
    source.write_text("A potentially useful economic mechanism")
    result = capture_source(source, tmp_path / "out")
    pinned = file_hash(Path(result.report_path))
    doc = json.loads(Path(result.report_path).read_text())
    doc["status"] = "RESEARCH_READY"
    doc["report_hash"] = digest({key: value for key, value in doc.items() if key != "report_hash"})
    Path(result.report_path).write_text(json.dumps(doc))
    with pytest.raises(QuantError, match="independently pinned"):
        verify_capture(result.report_path, expected_report_sha256=pinned)


def test_structural_completeness_cannot_self_promote_to_research_ready(tmp_path):
    from src.engine.research_capture import _REQUIRED_CLAUSES

    source = tmp_path / "complete.yaml"
    source.write_text("\n".join(f"{name}: fully_declared" for name in _REQUIRED_CLAUSES))
    result = capture_source(source, tmp_path / "out")
    assert result.provenance["descriptive_sections_complete"]
    assert result.status == "THESIS_CAPTURED" and not result.executable
