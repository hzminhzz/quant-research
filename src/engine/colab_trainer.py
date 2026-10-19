"""Remote model training worker via Google Colab CLI.

Strict governance:
1. Only development training data (windows.train.start to windows.train.end) is uploaded.
2. Validation and protected holdout data are NEVER loaded or uploaded.
3. Trained artifacts are hashed (SHA-256) and verified in run_log/python_features/<sha256>.pkl.
4. Sessions are ephemeral; try/finally guarantees VM termination to prevent orphaned billable compute.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import polars as pl

from src.data_vault import DataVault
from src.data_vault.panel_builder import CANONICAL_COLUMNS

from .common import QuantError, file_hash, write_json
from .feature_compiler import MODEL_CONTRACT_SCHEMA, MODEL_ROW_KEYS
from .spec_parser import CandidateSpec, PythonFeatureArtifact, export_spec, parse_spec

REPO = Path(__file__).resolve().parents[2]


class ColabTrainer:
    """Manages ephemeral Google Colab GPU training jobs with fail-closed safety."""

    def __init__(
        self,
        spec: CandidateSpec | str | Path,
        *,
        run_log: str | Path = REPO / "run_log",
        colab_bin: str | Path | None = None,
    ):
        self.spec = parse_spec(spec) if isinstance(spec, (str, Path)) else spec
        self.run_log = Path(run_log).resolve()
        found = (
            colab_bin
            or shutil.which("colab")
            or (Path("/home/quant/.local/bin/colab") if Path("/home/quant/.local/bin/colab").is_file() else None)
        )
        self.colab_bin = str(found or "colab")

    def prepare_training_data(self, output_file: Path) -> dict[str, Any]:
        """Load and export strictly the training window data. Never touches validation/holdout."""
        vault = DataVault(self.spec.panel_root)
        train_start = self.spec.windows.train.start
        train_end = self.spec.windows.train.end

        # Fail-closed temporal boundary check
        if train_end > self.spec.windows.validation.start:
            raise QuantError("INVALID_SPEC", "Train window end overlaps validation window start")
        if train_end > self.spec.windows.protected.start:
            raise QuantError("INVALID_SPEC", "Train window touches protected holdout boundary")

        df = vault.load(start=train_start, end=train_end)
        if df.is_empty():
            raise QuantError("BLOCKED_DATA", f"No training data found in vault between {train_start} and {train_end}")

        # Enforce both half-open bounds, independently of the vault adapter.
        leak_count = df.filter(pl.col("timestamp") >= train_end).height
        if leak_count > 0:
            raise QuantError("INVALID_EVIDENCE", f"Data contains {leak_count} rows at or beyond train_end: {train_end}")
        early_count = df.filter(pl.col("timestamp") < train_start).height
        if early_count > 0:
            raise QuantError("INVALID_EVIDENCE", f"Data contains {early_count} rows before train_start: {train_start}")

        output_file.parent.mkdir(parents=True, exist_ok=True)
        df.write_ipc(output_file)
        return {
            "rows": df.height,
            "symbols": df["symbol"].n_unique(),
            "start": train_start.isoformat(),
            "end": train_end.isoformat(),
            "sha256": file_hash(output_file),
        }

    def training_contract(self) -> dict[str, Any]:
        """Serializable train-only contract for any remote training script."""
        return {
            "schema": "model_training_contract_v1",
            "signal": self.spec.signal,
            "baseline": self.spec.baseline,
            "atr_feature": self.spec.allocation.atr_feature,
            "train_start": self.spec.windows.train.start.isoformat(),
            "train_end": self.spec.windows.train.end.isoformat(),
            "validation_start": self.spec.windows.validation.start.isoformat(),
            "label_horizon_bars": self.spec.label_horizon_bars,
            "bar_seconds": self.spec.bar_seconds,
            "seed": self.spec.seed,
            "declared_features": [feature.name for feature in self.spec.features],
        }

    def model_contract(self, artifact_sha256: str, *,
                       training_provenance: dict[str, Any] | None = None) -> dict[str, Any]:
        """Explicit output contract stored beside the immutable model bytes."""
        aliases = ({"lgb_return_pred": self.spec.signal}
                   if self.spec.signal == "lgb_signal" else {})
        payload = {
            "schema": MODEL_CONTRACT_SCHEMA,
            "model_sha256": artifact_sha256,
            "signal": self.spec.signal,
            "baseline": self.spec.baseline,
            "atr_feature": self.spec.allocation.atr_feature,
            "row_keys": list(MODEL_ROW_KEYS),
            "predictor_output": self.spec.signal,
            "legacy_output_aliases": aliases,
            "canonical_columns": list(CANONICAL_COLUMNS),
        }
        if training_provenance is not None:
            payload["training_provenance"] = training_provenance
        return payload

    def write_model_contract(self, artifact_sha256: str,
                             directory: str | Path | None = None,
                             *, training_provenance: dict[str, Any] | None = None) -> Path:
        """Write/verify the deterministic contract sidecar for an artifact hash."""
        folder = Path(directory) if directory is not None else self.run_log / "python_features"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{artifact_sha256}.json"
        payload = self.model_contract(artifact_sha256,
                                      training_provenance=training_provenance)
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != payload:
                raise QuantError("INVALID_EVIDENCE",
                                 "Existing model contract differs from the frozen specification")
        else:
            write_json(path, payload)
        return path

    def train(
        self,
        training_script: str | Path | None = None,
        *,
        gpu: Literal["T4", "L4", "A100"] = "T4",
        timeout: int = 3600,
        output_candidate_path: str | Path | None = None,
    ) -> tuple[PythonFeatureArtifact, CandidateSpec]:
        """Execute remote GPU training session and attach artifact to CandidateSpec."""
        session_id = f"ats-train-{uuid4().hex[:8]}"
        if not (shutil.which(self.colab_bin) or Path(self.colab_bin).is_file()):
            raise QuantError("BLOCKED_COMPUTE", f"colab executable not found: {self.colab_bin}")
        script_path = (
            Path(training_script).resolve()
            if training_script
            else (Path(__file__).parent / "default_train_script.py")
        )
        if not script_path.is_file():
            raise QuantError("INVALID_SPEC", f"Training script not found: {script_path}")

        features_dir = self.run_log / "python_features"
        features_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="colab-train-") as tmpdir:
            tmppath = Path(tmpdir)
            train_arrow = tmppath / "train.arrow"
            train_receipt = self.prepare_training_data(train_arrow)
            provenance = {
                "training_data_sha256": train_receipt["sha256"],
                "training_rows": train_receipt["rows"],
                "training_symbols": train_receipt.get("symbols"),
                "training_script_sha256": file_hash(script_path),
            }
            train_meta = tmppath / "train_meta.json"
            write_json(train_meta, {**self.training_contract(), **provenance})

            remote_arrow = "/content/train.arrow"
            remote_meta = "/content/train_meta.json"
            remote_model = "/content/model.pkl"
            local_model = tmppath / "model.pkl"

            try:
                # 1. Allocate VM
                cmd_new = [self.colab_bin, "new", "-s", session_id, "--gpu", gpu]
                res_new = subprocess.run(cmd_new, capture_output=True, text=True, check=False)
                if res_new.returncode != 0:
                    err_msg = res_new.stderr.strip() or res_new.stdout.strip()
                    raise QuantError("BLOCKED_COMPUTE", f"Failed to allocate Colab {gpu} session: {err_msg}")

                # 2. Upload the train-only partition and its explicit contract.
                for source, remote in ((train_arrow, remote_arrow), (train_meta, remote_meta)):
                    cmd_up = [self.colab_bin, "upload", "-s", session_id, str(source), remote]
                    res_up = subprocess.run(cmd_up, capture_output=True, text=True, check=False)
                    if res_up.returncode != 0:
                        err_msg = res_up.stderr.strip() or res_up.stdout.strip()
                        raise QuantError("BLOCKED_COMPUTE",
                                         f"Failed to upload {source.name} to Colab: {err_msg}")

                # 3. Execute training script
                cmd_exec = [
                    self.colab_bin,
                    "exec",
                    "-s",
                    session_id,
                    "-f",
                    str(script_path),
                    "--timeout",
                    str(float(timeout)),
                ]
                try:
                    res_exec = subprocess.run(
                        cmd_exec,
                        capture_output=True,
                        text=True,
                        timeout=timeout + 60,
                        check=False,
                    )
                except subprocess.TimeoutExpired as exc:
                    raise QuantError("BLOCKED_COMPUTE", f"Remote Colab training exceeded timeout ({timeout}s)") from exc

                if res_exec.returncode != 0:
                    err_msg = res_exec.stderr.strip() or res_exec.stdout.strip()
                    raise QuantError("BLOCKED_COMPUTE", f"Remote Colab training execution failed: {err_msg}")

                # 4. Download model.pkl
                cmd_dl = [self.colab_bin, "download", "-s", session_id, remote_model, str(local_model)]
                res_dl = subprocess.run(cmd_dl, capture_output=True, text=True, check=False)
                if res_dl.returncode != 0 or not local_model.is_file():
                    err_msg = res_dl.stderr.strip() or res_dl.stdout.strip()
                    raise QuantError("BLOCKED_COMPUTE", f"Failed to download trained model from Colab: {err_msg}")
                size = local_model.stat().st_size
                if size <= 0 or size > 2 * 1024**3:
                    raise QuantError("INVALID_FEATURE",
                                     f"Downloaded model artifact has invalid size: {size} bytes")

                # 5. Cryptographic hash, immutable storage and explicit contract.
                sha = file_hash(local_model)
                permanent_path = features_dir / f"{sha}.pkl"
                if permanent_path.exists():
                    if file_hash(permanent_path) != sha:
                        raise QuantError("INVALID_EVIDENCE",
                                         "Existing model artifact differs from downloaded bytes")
                else:
                    with permanent_path.open("xb") as handle:
                        handle.write(local_model.read_bytes())
                contract_file = self.write_model_contract(
                    sha, features_dir, training_provenance=provenance)

                rel_path = f"python_features/{sha}.pkl"
                artifact = PythonFeatureArtifact(path=rel_path, sha256=sha,
                                                 contract_sha256=file_hash(contract_file))

                # Attach to candidate spec
                updated_spec = self.spec.model_copy(
                    update={"python_feature_artifact": artifact}
                )
                updated_spec._base_dir = self.run_log

                if output_candidate_path:
                    out_p = Path(output_candidate_path).resolve()
                    export_spec(updated_spec, out_p)
                    # Return the portable, re-parsed identity that callers will load.
                    updated_spec = parse_spec(out_p)

                return updated_spec.python_feature_artifact, updated_spec

            finally:
                # Guaranteed cleanup: always terminate session
                cmd_stop = [self.colab_bin, "stop", "-s", session_id]
                subprocess.run(cmd_stop, capture_output=True, check=False)
