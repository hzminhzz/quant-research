"""Fail-closed publication of committed descriptive ATS source pairs.

No scientific factory, protected partition, or broker APIs are imported here.
This CLI proves only that a bounded source pair was committed and pushed to a
research branch. It grants no ingestion, training, backtest, holdout or
deployment authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import yaml

# Direct ``python scripts/...`` execution must not depend on the caller's
# PYTHONPATH (CI exports only the pinned connector path). Bootstrap this
# checkout the same way the other repository CLIs do, before importing src.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.engine.research_handoff import _UniqueKeyLoader, validate_handoff
from src.research_control.research_inbox_queue import (
    NESTED_SECTIONS,
    _brief_links_source,
    _valid_nested_source_anchors,
    _validate_flat_capture,
)

ID = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)*\Z")
BRANCH = re.compile(r"research/[a-zA-Z0-9][a-zA-Z0-9_./-]*\Z")
SAFE_RUN = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,100}\Z")
MAX_BYTES = 256_000
GIT_TIMEOUT = 75
MAX_TRANSPORT_ATTEMPTS = 3


class PublicationError(RuntimeError):
    pass


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["git", "-C", str(root), *args], text=True,
                            capture_output=True, timeout=GIT_TIMEOUT, check=False)
    if check and result.returncode:
        raise PublicationError(f"git {args[0]} failed (exit {result.returncode}): "
                               + result.stderr.strip()[-350:])
    return result


def git_bytes(root: Path, *args: str) -> bytes:
    """Run git without text decoding so content hashes cover exact blob bytes."""
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                            timeout=GIT_TIMEOUT, check=False)
    if result.returncode:
        raise PublicationError(f"git {args[0]} failed (exit {result.returncode}): "
                               + result.stderr.decode("utf-8", "replace").strip()[-350:])
    return result.stdout


def blob(root: Path, rev: str, path: str) -> bytes:
    return git_bytes(root, "cat-file", "blob", f"{rev}:{path}")


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def receipt(root: Path, factory: str, run_id: str, data: dict) -> Path:
    directory = root / factory
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{run_id}-{uuid4().hex}.json"
    payload = dict(data)
    payload["receipt_path"] = str(path)
    raw = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    dfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)
    return path


def pair_check(root: Path, candidate: str) -> dict:
    if not ID.fullmatch(candidate):
        raise PublicationError("invalid candidate identity")
    folder = root / "research_inbox" / candidate
    if folder.is_symlink() or not folder.is_dir():
        raise PublicationError(f"candidate directory missing or symlinked: {candidate}")
    paths = sorted(folder.iterdir())
    if {p.name for p in paths} != {"thesis.yaml", "brief.md"} or any(
        p.is_symlink() or not p.is_file() or p.stat().st_size > MAX_BYTES for p in paths
    ):
        raise PublicationError(f"candidate pair must be bounded regular files: {candidate}")
    try:
        doc = yaml.load((folder / "thesis.yaml").read_text("utf-8"), Loader=_UniqueKeyLoader)
        brief = folder / "brief.md"
        if not isinstance(doc, dict):
            raise PublicationError("YAML mapping expected")
        if set(doc) == NESTED_SECTIONS:
            identity = doc.get("identity")
            if not isinstance(identity, dict) or identity.get("candidate_id") != candidate:
                raise PublicationError("nested source identity mismatch")
            refs = identity.get("source_references")
            if not _valid_nested_source_anchors(refs) or not _brief_links_source(candidate, brief, refs):
                raise PublicationError("nested source anchors invalid")
            kind = "THESIS_CAPTURED_NESTED"
        elif doc.get("status") in {"THESIS_CAPTURED", "DRAFT_UNVERIFIED"}:
            _validate_flat_capture(doc, candidate, brief)
            kind = "THESIS_CAPTURED_FLAT"
        else:
            result = validate_handoff(folder)
            if result.get("status") != "HANDOFF_VALID_UNVERIFIED":
                raise PublicationError("unexpected handoff validation result")
            kind = "HANDOFF_VALID_UNVERIFIED"
    except (yaml.YAMLError, UnicodeError, ValueError, OSError) as exc:
        raise PublicationError(f"source admission failed for {candidate}: {exc}") from exc
    return {"candidate_id": candidate, "validation": kind,
            "sha256": {p.name: sha(p.read_bytes()) for p in paths}}


def repository_root(root: Path) -> None:
    top = git(root, "rev-parse", "--show-toplevel").stdout.strip()
    if not top or Path(top).resolve() != root:
        raise PublicationError("--repo must be the root of a git checkout")


def remote_sha(root: Path, ref: str) -> str | None:
    fields = git(root, "ls-remote", "--heads", "origin", ref).stdout.split()
    return fields[0] if fields else None


def verify_published_blobs(root: Path, target: str, published: str,
                           candidates: list[dict]) -> None:
    """Read the fetched remote commit; report failures as publication errors."""
    git(root, "fetch", "--no-tags", "origin", target)
    fetched = git(root, "rev-parse", "FETCH_HEAD").stdout.strip()
    if fetched != published:
        raise PublicationError("remote readback did not resolve to the published commit")
    for cand in candidates:
        for filename, digest in cand["sha256"].items():
            path = f"research_inbox/{cand['candidate_id']}/{filename}"
            if sha(blob(root, published, path)) != digest:
                raise PublicationError("remote source byte readback mismatch")


def run(root: Path, args: argparse.Namespace, result: dict) -> dict:
    if args.action == "no-op":
        if not args.reason or not args.reason.strip():
            raise PublicationError("no-op requires a factual --reason")
        result.update(status="NO_NOVEL_SOURCE", reason=args.reason.strip(), transport_attempts=0)
        return result

    repository_root(root)
    head = git(root, "rev-parse", "HEAD").stdout.strip()
    branch = git(root, "symbolic-ref", "--quiet", "--short", "HEAD", check=False).stdout.strip()
    result.update(local_head=head, branch=branch)
    if (not BRANCH.fullmatch(branch) or ".." in branch or "//" in branch
            or branch.endswith(("/", ".", ".lock"))):
        raise PublicationError("publication requires task-owned research/* branch")
    if git(root, "status", "--porcelain", "--untracked-files=no").stdout.strip():
        raise PublicationError("tracked worktree is dirty")
    base = git(root, "rev-parse", "refs/remotes/origin/main").stdout.strip()
    result["origin_main_sha"] = base
    if git(root, "merge-base", base, head).stdout.strip() != base:
        raise PublicationError("branch does not descend from origin/main")
    history = git(root, "rev-list", "--parents", f"{base}..{head}").stdout.splitlines()
    if not history:
        raise PublicationError("no committed source changes")
    if len(history) > 4:
        raise PublicationError("source publication branch contains more than four commits")
    if any(len(line.split()) > 2 for line in history):
        raise PublicationError("merge commits not allowed in source publication branch")
    # Do not publish from an out-of-date base.
    if remote_sha(root, "refs/heads/main") != base:
        raise PublicationError("origin/main is stale; re-inspect, do not auto-rebase")
    changes = git(root, "diff", "--name-status", f"{base}..{head}").stdout.splitlines()
    ids: set[str] = set()
    for line in changes:
        parts = line.split("\t")
        if len(parts) != 2 or parts[0] != "A":
            raise PublicationError("only newly added files may be published")
        p = parts[1]
        m = re.fullmatch(r"research_inbox/([a-z0-9_]+)/((?:thesis\.yaml)|(?:brief\.md))", p)
        if not m:
            raise PublicationError(f"out-of-scope committed path: {p}")
        ids.add(m.group(1))
    if not 1 <= len(ids) <= 8 or len(changes) != 2 * len(ids):
        raise PublicationError("require 1-8 complete source pairs")
    result["candidates"] = [pair_check(root, candidate) for candidate in sorted(ids)]
    # Ensure working-directory source is byte-identical to immutable committed HEAD.
    for cand in result["candidates"]:
        for filename, digest in cand["sha256"].items():
            path = f"research_inbox/{cand['candidate_id']}/{filename}"
            if sha(blob(root, "HEAD", path)) != digest:
                raise PublicationError("source contents differ from committed HEAD")

    # Refresh only remote tracking research refs, not any checked-out user branch.
    git(root, "fetch", "--no-tags", "--prune", "origin",
        "+refs/heads/research/*:refs/remotes/origin/research/*")
    own = f"refs/remotes/origin/{branch}"
    remote_refs = git(root, "for-each-ref", "--format=%(refname)",
                      "refs/remotes/origin/research").stdout.splitlines()
    for remote in remote_refs:
        if remote == own:
            continue
        for cand in sorted(ids):
            found = git(root, "ls-tree", "--name-only", f"{remote}:research_inbox/{cand}",
                        check=False)
            if found.returncode == 0 and found.stdout.strip():
                raise PublicationError(f"candidate already exists on published branch: {cand}")
    target = f"refs/heads/{branch}"
    for attempt in range(1, MAX_TRANSPORT_ATTEMPTS + 1):
        result["transport_attempts"] = attempt
        current = remote_sha(root, target)
        if current and current != head:
            raise PublicationError("remote branch exists at different SHA; refusing overwrite")
        if not current:
            pushed = git(root, "push", "origin", f"{head}:{target}", check=False)
            result["last_transport_exit"] = pushed.returncode
            # An ambiguous or failed transport response is reconciled below, never assumed.
            current = remote_sha(root, target)
        if current == head:
            # Independently read back the exact remote SHA and both pair blobs.
            verify_published_blobs(root, target, current, result["candidates"])
            result.update(status="REMOTE_PUBLICATION_VERIFIED",
                          remote_sha=current, readback_verified=True,
                          reason="remote SHA and pair hashes match")
            return result
    raise PublicationError("push unresolved after three reconciled attempts")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("publish", "no-op"))
    p.add_argument("--factory", required=True, choices=("general", "crypto", "ml"))
    p.add_argument("--run-id", required=True)
    p.add_argument("--reason")
    p.add_argument("--repo", type=Path, default=Path.cwd())
    p.add_argument("--receipt-root", type=Path,
                   default=Path("/home/quant/dev/quant/quant-research/run_log/source_publications"))
    args = p.parse_args(argv)
    if not SAFE_RUN.fullmatch(args.run_id):
        p.error("unsafe --run-id")
    result = {"schema_version": 1, "factory": args.factory, "run_id": args.run_id,
              "invocation_utc": datetime.now(UTC).isoformat(), "status": "NOT_PUBLISHED",
              "transport_attempts": 0, "candidates": [], "readback_verified": False,
              "scope": {"scientific_trials": 0, "protected_reads": 0, "orders": 0},
              "authorization": {"ingestion": False, "training": False, "backtest": False,
                                "holdout_read": False, "deployment": False}}
    code = 2
    try:
        run(args.repo.resolve(), args, result)
        code = 0
    except (PublicationError, subprocess.TimeoutExpired, OSError, ValueError) as exc:
        result.update(status="NOT_PUBLISHED", reason=str(exc)[:500],
                      error_type=type(exc).__name__)
    except Exception as exc:  # noqa: BLE001 - every failure still leaves an immutable receipt
        result.update(status="NOT_PUBLISHED", reason=str(exc)[:500],
                      error_type=type(exc).__name__)
    try:
        path = receipt(args.receipt_root, args.factory, args.run_id, result)
        result["receipt_path"] = str(path)
    except OSError as exc:
        print(json.dumps({"status": "RECEIPT_FAILED", "factory": args.factory,
                          "run_id": args.run_id, "error": str(exc)[:500]}), file=sys.stderr)
        return 3
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
