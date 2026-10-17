"""Durable ATS-7 decision/control evidence. Native ML4T still owns the risk book."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.release_contracts import ReleaseBlocked, ReleaseManifest
from src.research_control.action_authorization import canonical_json, sha256_json


class ReleaseJournal:
    def __init__(self, path: Path, manifest: ReleaseManifest):
        self.path = path
        self.manifest = manifest
        self.connection = sqlite3.connect(path, timeout=15, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=DELETE")
        self.connection.execute("PRAGMA synchronous=EXTRA")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
              seq INTEGER PRIMARY KEY, at TEXT NOT NULL, kind TEXT NOT NULL,
              payload TEXT NOT NULL, previous TEXT NOT NULL, digest TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS events_kind_sequence ON events(kind,seq);
            CREATE TABLE IF NOT EXISTS decisions (
              identity TEXT PRIMARY KEY, request TEXT NOT NULL, digest TEXT NOT NULL,
              state TEXT NOT NULL, order_id TEXT);
        """)
        with self.transaction():
            existing = self.connection.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()
            if existing is None:
                self.connection.execute("INSERT INTO metadata VALUES ('manifest',?)", (manifest.identity,))
                self._append("release_bound", {"manifest": manifest.model_dump(mode="json")})
            elif existing[0] != manifest.identity:
                raise ReleaseBlocked("RISK_DOMAIN_ALREADY_BOUND_TO_ANOTHER_RELEASE")
        self.verify()
        with self.transaction():
            rows = self.connection.execute("SELECT identity FROM decisions WHERE state='DISPATCHING'").fetchall()
            for row in rows:
                self._finish(row[0], "UNKNOWN", None, {"reason": "process_interrupted"})
            if rows:
                self._append("halt", {"reason": "UNKNOWN_EXPOSURE_AFTER_RESTART"})

    @contextmanager
    def transaction(self):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    def _append(self, kind: str, payload: dict[str, Any]) -> None:
        last = self.connection.execute("SELECT seq,digest FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        seq, previous = (last[0] + 1, last[1]) if last else (1, "0" * 64)
        at = datetime.now(UTC).isoformat()
        encoded = canonical_json(payload).decode()
        digest = sha256_json([seq, at, kind, encoded, previous])
        self.connection.execute("INSERT INTO events VALUES (?,?,?,?,?,?)",
                                (seq, at, kind, encoded, previous, digest))

    def record(self, kind: str, payload: dict[str, Any]) -> None:
        with self.transaction():
            self._append(kind, payload)

    def events(self, kind: str | None = None) -> list[dict[str, Any]]:
        sql, args = ("SELECT * FROM events ORDER BY seq", ())
        if kind:
            sql, args = "SELECT * FROM events WHERE kind=? ORDER BY seq", (kind,)
        return [{**dict(r), "payload": json.loads(r["payload"])}
                for r in self.connection.execute(sql, args)]

    @property
    def halted(self) -> bool:
        row = self.connection.execute(
            "SELECT kind FROM events WHERE kind IN ('halt','resume') ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        return row is not None and row[0] == "halt"

    @property
    def unknown(self) -> int:
        return self.connection.execute(
            "SELECT count(*) FROM decisions WHERE state IN ('UNKNOWN','DISPATCHING')"
        ).fetchone()[0]

    def halt(self, reason: str) -> None:
        self.record("halt", {"reason": reason})

    def stage(self, identity: str, request: dict[str, Any]) -> None:
        encoded, digest = canonical_json(request).decode(), sha256_json(request)
        with self.transaction():
            row = self.connection.execute("SELECT digest,state FROM decisions WHERE identity=?", (identity,)).fetchone()
            if row:
                reason = "DUPLICATE_DECISION" if row[0] == digest else "CONFLICTING_DECISION"
                raise ReleaseBlocked(reason + ":" + row[1])
            if request["action"] == "open" and (self.halted or self.unknown):
                raise ReleaseBlocked("HALTED_OR_UNKNOWN_EXPOSURE")
            self.connection.execute("INSERT INTO decisions VALUES (?,?,?,'DISPATCHING',NULL)",
                                    (identity, encoded, digest))
            self._append("decision_committed", {"identity": identity, "request": request})

    def _finish(self, identity: str, state: str, order_id: str | None, evidence: dict) -> None:
        self.connection.execute("UPDATE decisions SET state=?,order_id=? WHERE identity=?",
                                (state, order_id, identity))
        self._append("decision_observed", {"identity": identity, "state": state,
                                          "order_id": order_id, "evidence": evidence})

    def finish(self, identity: str, state: str, order_id: str | None, evidence: dict) -> None:
        if state not in {"ACKNOWLEDGED", "LOCAL_FILLED", "REJECTED_BEFORE_EFFECT", "UNKNOWN"}:
            raise ValueError("invalid observation classification")
        with self.transaction():
            if self.connection.execute("SELECT 1 FROM decisions WHERE identity=?", (identity,)).fetchone() is None:
                raise ReleaseBlocked("MISSING_DURABLE_DECISION")
            self._finish(identity, state, order_id, evidence)
            if state == "UNKNOWN":
                self._append("halt", {"reason": "UNKNOWN_EXECUTION_OUTCOME"})

    def verify(self) -> None:
        previous, expected_seq = "0" * 64, 1
        projection: dict[str, tuple] = {}
        for row in self.connection.execute("SELECT * FROM events ORDER BY seq"):
            expected = sha256_json([row["seq"], row["at"], row["kind"], row["payload"], previous])
            if row["seq"] != expected_seq or row["previous"] != previous or row["digest"] != expected:
                raise ReleaseBlocked("RELEASE_JOURNAL_INTEGRITY")
            payload = json.loads(row["payload"])
            if row["kind"] == "release_bound" and sha256_json(payload["manifest"]) != self.manifest.identity:
                raise ReleaseBlocked("RELEASE_BINDING_INTEGRITY")
            if row["kind"] == "decision_committed":
                request = payload["request"]
                projection[payload["identity"]] = (canonical_json(request).decode(), sha256_json(request),
                                                    "DISPATCHING", None)
            if row["kind"] == "decision_observed":
                key = payload["identity"]
                if key not in projection:
                    raise ReleaseBlocked("OBSERVATION_WITHOUT_INTENT")
                old = projection[key]
                projection[key] = (*old[:2], payload["state"], payload["order_id"])
            previous, expected_seq = row["digest"], expected_seq + 1
        actual = {r["identity"]: (r["request"], r["digest"], r["state"], r["order_id"])
                  for r in self.connection.execute("SELECT * FROM decisions")}
        if actual != projection:
            raise ReleaseBlocked("RELEASE_PROJECTION_INTEGRITY")

    def verify_native_references(self, native_journal: Path) -> None:
        # Detect restoring only an older release database beside a newer native
        # journal. Native ML4T validates its own journal's cryptographic chain.
        known = {r[0] for r in self.connection.execute("SELECT identity FROM decisions")}
        if native_journal.exists():
            for line in native_journal.read_text().splitlines():
                row = json.loads(line)
                event = row.get("entry", row)
                if (event.get("event") == "ats7_decision_committed"
                        and event["payload"]["execution_identity"] not in known):
                    raise ReleaseBlocked("STALE_RELEASE_JOURNAL")

    def close(self) -> None:
        self.connection.close()


def execution_identity(manifest_sha: str, decision_time: str, ordinal: int, action: str) -> str:
    # 32 characters fit provider client-order identifiers. Payload is checked
    # separately so a changed request cannot become a second order on retry.
    return hashlib.sha256(canonical_json([manifest_sha, decision_time, ordinal, action])).hexdigest()[:32]
