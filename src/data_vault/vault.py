"""Development-only reads and single-use, evidence-bound holdout release.

The cooperative Python API is not an operating-system security boundary. Run
untrusted callbacks through engine.isolation; the owner of the host filesystem
can always alter their own code/evidence. Hashes establish identity, not authority
against that owner. Prior exposure cannot be erased by a new candidate name.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from src.engine.common import (
    QuantError,
    beneath,
    digest,
    file_hash,
    read_json,
    safe_name,
    utc,
    write_json,
)

from .panel_builder import CANONICAL_COLUMNS, SCHEMA, parquet_bounds, validate_panel


class DataVault:
    def __init__(self, root: str | Path, *, run_log: str | Path = 'run_log',
                 receipt_dir: str | Path | None = None):
        self.root = Path(root).resolve()
        self.run_log = Path(run_log).resolve()
        self.receipt_dir = Path(receipt_dir).resolve() if receipt_dir is not None else None
        try:
            manifest = read_json(beneath(self.root, 'manifest.json', must_exist=True))
        except FileNotFoundError as exc:
            raise QuantError('BLOCKED_DATA', 'No canonical manifest: compile the development panel first or use --build-if-missing') from exc
        recorded = manifest.pop('manifest_hash', None)
        if recorded != digest(manifest) or manifest.get('columns') != CANONICAL_COLUMNS:
            raise QuantError('INVALID_EVIDENCE', 'Canonical manifest identity/schema mismatch')
        manifest['manifest_hash'] = recorded
        self.manifest, self.manifest_hash = manifest, recorded
        self.protected_test_start = utc(manifest['protected_test_start'])
        self.opened_files: list[str] = []

    def _load(self, start: datetime, end: datetime, *, kind: str, table: str,
              symbols: list[str] | None = None) -> pl.DataFrame:
        frames = []
        if start >= end:
            return pl.DataFrame(schema=SCHEMA) if table == 'prices' else pl.DataFrame()
        for item in self.manifest['entries']:
            if item['kind'] != kind or item['table'] != table:
                continue
            if symbols is not None and item['symbol'] not in symbols:
                continue
            lo, hi = utc(item['start']), utc(item['last'])
            if hi < start or lo >= end:
                continue
            if kind == 'development' and hi >= self.protected_test_start:
                raise QuantError('INVALID_EVIDENCE', 'Development partition straddles protected data')
            if kind == 'protected' and lo < self.protected_test_start:
                raise QuantError('INVALID_EVIDENCE', 'Protected partition straddles development data')
            path = beneath(self.root, item['path'], must_exist=True)
            if not path.is_relative_to(self.root / kind):
                raise QuantError('INVALID_PATH', 'Manifest table is outside its physical split')
            # Footer metadata is checked BEFORE decoding any data row.
            actual_lo, actual_hi = parquet_bounds(path)
            if (actual_lo, actual_hi) != (lo, hi):
                raise QuantError('INVALID_EVIDENCE', 'Parquet bounds differ from manifest')
            if kind == 'development' and actual_hi >= self.protected_test_start:
                raise QuantError('INVALID_EVIDENCE', 'Protected rows in a development file')
            if file_hash(path) != item['sha256']:
                raise QuantError('INVALID_EVIDENCE', 'Immutable panel content changed')
            self.opened_files.append(str(path))
            dtype = pl.Datetime('us', 'UTC')
            frames.append(pl.scan_parquet(path, hive_partitioning=False).filter(
                (pl.col('timestamp') >= pl.lit(start).cast(dtype))
                & (pl.col('timestamp') < pl.lit(end).cast(dtype))).collect(engine='streaming'))
        if not frames:
            return pl.DataFrame(schema=SCHEMA) if table == 'prices' else pl.DataFrame()
        result = pl.concat(frames, how='vertical_relaxed').sort('symbol', 'timestamp')
        return validate_panel(result) if table == 'prices' else result

    def load(self, start: str | datetime | None = None, end: str | datetime | None = None,
             *, symbols: list[str] | None = None) -> pl.DataFrame:
        """No permit: open ONLY certified development files, never protected files."""
        start_at = utc(start) if start is not None else datetime(1970, 1, 1, tzinfo=UTC)
        end_at = min(utc(end), self.protected_test_start) if end is not None else self.protected_test_start
        return self._load(start_at, end_at, kind='development', table='prices', symbols=symbols)

    def load_funding(self, start: str | datetime, end: str | datetime) -> pl.DataFrame:
        return self._load(utc(start), min(utc(end), self.protected_test_start),
                          kind='development', table='funding')

    def unlock_holdout(self, candidate_id: str, spec_hash: str) -> dict[str, Any]:
        """Reserve exact frozen evaluation once, after three verified stage receipts.

        Callers supply identities, not pass/fail booleans. Receipts are produced
        by the shared pipeline and bind spec/code/data and output file digests.
        Reservation remains consumed after a crash, even before data is read.
        """
        safe_name(candidate_id)
        if self.receipt_dir is None:
            raise QuantError('HOLDOUT_DENIED', 'Workbench vault has no factory receipt directory')
        from src.engine.common import runtime_identity
        current_code = runtime_identity()
        receipts = []
        for stage in (1, 2, 3):
            path = beneath(self.receipt_dir, f'stage{stage}.json', must_exist=True)
            receipt = read_json(path)
            checksum = receipt.pop('receipt_hash', None)
            if checksum != digest(receipt):
                raise QuantError('HOLDOUT_DENIED', 'Stage receipt digest mismatch')
            if (receipt.get('stage') != stage or receipt.get('status') != 'PASS'
                or receipt.get('candidate_id') != candidate_id or receipt.get('spec_hash') != spec_hash
                or receipt.get('code_hash') != current_code
                or receipt.get('panel_hash') != self.manifest_hash):
                raise QuantError('HOLDOUT_DENIED', 'Stage receipt does not match the frozen run')
            artifacts = receipt.get('artifacts', {})
            if not artifacts:
                raise QuantError('HOLDOUT_DENIED', 'Stage receipt has no evidence artifacts')
            stage_evidence = read_json(beneath(self.receipt_dir, f'stage{stage}_evidence.json', must_exist=True))
            if stage_evidence.get('status') != 'PASS':
                raise QuantError('HOLDOUT_DENIED', 'Stage evidence disagrees with the PASS receipt')
            if stage in (2, 3):
                checks = stage_evidence.get('checks', {})
                if stage == 3:
                    splits = stage_evidence.get('splits', {})
                    if set(splits) != {'train', 'validation'} or any(s.get('status') != 'PASS' for s in splits.values()):
                        raise QuantError('HOLDOUT_DENIED', 'Train and validation must each pass')
                    checks = {f'{name}.{key}': value for name, split in splits.items() for key, value in split.get('checks', {}).items()}
                if not checks or not all(value is True for value in checks.values()):
                    raise QuantError('HOLDOUT_DENIED', 'Required numerical stage checks did not all pass')
            for relative, expected in artifacts.items():
                artifact = beneath(self.receipt_dir, relative, must_exist=True)
                if file_hash(artifact) != expected:
                    raise QuantError('HOLDOUT_DENIED', 'Stage evidence was modified')
            receipts.append(checksum)
        frozen = read_json(beneath(self.receipt_dir, 'spec.json', must_exist=True))
        if digest(frozen) != spec_hash:
            raise QuantError('HOLDOUT_DENIED', 'Frozen spec was modified')
        window = frozen['windows']['protected']
        start, end = utc(window['start']), utc(window['end'])
        if start != self.protected_test_start or end <= start:
            raise QuantError('HOLDOUT_DENIED', 'Holdout does not match the vault boundary')
        # The cohort and window, not candidate name/spec, determine replay scope.
        scope = {'family': frozen['selection_family_id'], 'window': window,
                 'source_scope': sorted({e['symbol'] for e in self.manifest['entries']})}
        claim_id = digest(scope)
        claims = self.run_log / '_holdout_claims'
        if claims.is_symlink():
            raise QuantError('INVALID_PATH', 'Claim directory may not be a symlink')
        claim = {'claim_id': claim_id, 'candidate_id': candidate_id, 'spec_hash': spec_hash,
                 'code_hash': current_code, 'panel_hash': self.manifest_hash, 'scope': scope,
                 'receipt_hashes': receipts, 'reserved_at': datetime.now(UTC).isoformat(),
                 'prior_exposure': 'Not established as globally unseen; existing historical research remains exposed'}
        claim['claim_hash'] = digest(claim)
        try:
            write_json(claims / (claim_id + '.json'), claim, exclusive=True)
        except FileExistsError as exc:
            raise QuantError('HOLDOUT_ALREADY_CLAIMED', 'This selection cohort/window was already reserved') from exc
        return claim

    def load_holdout(self, claim: dict[str, Any]) -> tuple[pl.DataFrame, pl.DataFrame]:
        """Consume the reserved read once; return only the declared protected window."""
        claim_id = safe_name(claim.get('claim_id', ''))
        claims = self.run_log / '_holdout_claims'
        persisted = read_json(beneath(claims, claim_id + '.json', must_exist=True))
        check = dict(claim); checksum = check.pop('claim_hash', None)
        if persisted != claim or checksum != digest(check) or claim['panel_hash'] != self.manifest_hash:
            raise QuantError('HOLDOUT_DENIED', 'Invalid or changed claim')
        from src.engine.common import runtime_identity
        if claim['code_hash'] != runtime_identity():
            raise QuantError('HOLDOUT_DENIED', 'Code changed after holdout reservation')
        try:
            write_json(claims / (claim_id + '.consumed.json'),
                       {'claim_hash': checksum, 'consumed_at': datetime.now(UTC).isoformat()}, exclusive=True)
        except FileExistsError as exc:
            raise QuantError('HOLDOUT_ALREADY_CONSUMED', 'Protected data was already released') from exc
        window = claim['scope']['window']
        start, end = utc(window['start']), utc(window['end'])
        prices = self._load(start, end, kind='protected', table='prices')
        funding = self._load(start, end, kind='protected', table='funding')
        if prices.is_empty():
            raise QuantError('BLOCKED_DATA', 'No protected partition; claim remains consumed')
        return prices, funding
