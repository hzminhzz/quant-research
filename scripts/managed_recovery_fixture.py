"""Bounded synthetic worker used by the managed recovery qualification test."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.research_control.attempts import AttemptLedger, tmux_sessions


def pause(root: Path, session_id: str, attempt_id: str, ready: Path,
          partial: Path, release: Path, pid_file: Path) -> int:
    ledger = AttemptLedger(root, session_id, list_jobs=tmux_sessions)
    with ledger.worker_lease(attempt_id):
        if ledger.latest()[attempt_id]["status"] == "PLANNED":
            ledger.transition(attempt_id, "RUNNING", detail="synthetic worker started")
        partial.parent.mkdir(parents=True, exist_ok=True)
        payload = {"fixture": "m8-c-recovery-v1", "completed_units": 1}
        partial.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        import hashlib

        digest = hashlib.sha256(partial.read_bytes()).hexdigest()
        ledger.record_checkpoint(
            attempt_id,
            progress=1,
            artifacts={partial.relative_to(root).as_posix(): digest},
        )
        pid_file.write_text(str(os.getpid()), encoding="utf-8")
        print(json.dumps({"event": "CHECKPOINTED", "attempt_id": attempt_id,
                          "pid": os.getpid(), "progress": 1}), flush=True)
        ready.touch()
        deadline = time.monotonic() + 30
        while not release.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        return 0 if release.exists() else 3


def finish(root: Path, session_id: str, attempt_id: str,
           partial: Path, result: Path) -> int:
    ledger = AttemptLedger(root, session_id, list_jobs=tmux_sessions)
    with ledger.worker_lease(attempt_id):
        current = ledger.latest()[attempt_id]
        parent_id = current.get("parent_attempt_id")
        if not parent_id or current.get("status") != "PLANNED":
            return 4
        if not partial.is_file() or not ledger._verified_checkpoint(ledger.latest()[parent_id]):
            return 5
        checkpoint = json.loads(
            (root / ledger.latest()[parent_id]["checkpoint_path"]).read_text(encoding="utf-8")
        )
        expected = {"fixture": "m8-c-recovery-v1", "completed_units": 1}
        if (json.loads(partial.read_text(encoding="utf-8")) != expected or
            checkpoint["artifacts"].get(partial.relative_to(root).as_posix()) is None):
            return 6
        ledger.transition(attempt_id, "RUNNING", detail="successor replay started")
        result.parent.mkdir(parents=True, exist_ok=True)
        result.write_text(json.dumps({
            "fixture": "m8-c-recovery-result-v1",
            "attempt_id": attempt_id,
            "parent_attempt_id": parent_id,
            "run_id": current["run_id"],
            "fingerprints": current["fingerprints"],
            "completed_units": 2,
        }, sort_keys=True) + "\n", encoding="utf-8")
        import hashlib

        ledger.record_checkpoint(
            attempt_id,
            progress=2,
            artifacts={result.relative_to(root).as_posix(): hashlib.sha256(result.read_bytes()).hexdigest()},
        )
        ledger.transition(attempt_id, "COMPLETED", detail="synthetic output independently verifiable")
        print(json.dumps({"event": "COMPLETED", "attempt_id": attempt_id,
                          "parent_attempt_id": parent_id}), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("pause", "finish"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--ready", type=Path)
    parser.add_argument("--partial", type=Path, required=True)
    parser.add_argument("--release", type=Path)
    parser.add_argument("--pid-file", type=Path)
    parser.add_argument("--result", type=Path)
    args = parser.parse_args()
    if args.mode == "pause":
        if not all((args.ready, args.release, args.pid_file)):
            parser.error("pause mode needs --ready, --release and --pid-file")
        return pause(args.root, args.session_id, args.attempt_id,
                     args.ready, args.partial, args.release, args.pid_file)
    if args.result is None:
        parser.error("finish mode needs --result")
    return finish(args.root, args.session_id, args.attempt_id,
                  args.partial, args.result)


if __name__ == "__main__":
    raise SystemExit(main())
