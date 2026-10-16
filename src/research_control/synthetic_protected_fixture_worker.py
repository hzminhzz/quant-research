"""Private, fixed Bubblewrap worker: consume synthetic bytes, emit digest only."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

MAGIC = b"ATS2_SYNTHETIC_PROTECTED_V1:"


def main() -> int:
    if len(sys.argv) != 6:
        return 2
    source = Path(sys.argv[1])
    output = Path(sys.argv[2])
    expected = sys.argv[3]
    issuer_path = Path(sys.argv[4])
    policy_path = Path(sys.argv[5])
    if (source != Path("/work/fixture.bin") or output != Path("/work/out/digest.json")
        or source.is_symlink() or not source.is_file() or output.exists()):
        return 3
    # The host key and trust policy are intentionally *not mounted*.
    key_visible = issuer_path.exists()
    policy_visible = policy_path.exists()
    if key_visible or policy_visible:
        return 4
    raw = source.read_bytes()
    if len(raw) != len(MAGIC) + 32 or not raw.startswith(MAGIC):
        return 5
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected:
        return 6
    doc = {
        "schema_version": 1, "operation": "synthetic_protected_fixture_read",
        "bytes_read": len(raw), "sha256": digest, "issuer_key_visible": False,
        "trust_policy_visible": False,
    }
    flags = os.O_CREAT | os.O_WRONLY | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(output, flags, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode() + b"\n")
        out.flush()
        os.fsync(out.fileno())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
