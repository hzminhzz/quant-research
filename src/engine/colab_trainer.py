"""Remote model training worker via Google Colab CLI.

Strict governance:
1. Only development training data (windows.train.start to windows.train.end) is uploaded.
2. Validation and protected holdout data are NEVER loaded or uploaded.
3. Trained artifacts are hashed (SHA-256) and verified in run_log/python_features/<sha256>.pkl.
4. Sessions are ephemeral; try/finally guarantees VM termination to prevent orphaned billable compute.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import polars as pl

from src.data_vault import DataVault

from .common import QuantError, file_hash
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

        # Ensure no timestamp in dataframe exceeds train_end
        leak_count = df.filter(pl.col("timestamp") >= train_end).height
        if leak_count > 0:
            raise QuantError("INVALID_EVIDENCE", f"Data contains {leak_count} rows at or beyond train_end: {train_end}")

        output_file.parent.mkdir(parents=True, exist_ok=True)
        df.write_ipc(output_file)
        return {
            "rows": df.height,
            "symbols": df["symbol"].n_unique(),
            "start": train_start.isoformat(),
            "end": train_end.isoformat(),
            "sha256": file_hash(output_file),
        }

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
            self.prepare_training_data(train_arrow)

            remote_arrow = "/content/train.arrow"
            remote_model = "/content/model.pkl"
            local_model = tmppath / "model.pkl"

            try:
                # 1. Allocate VM
                cmd_new = [self.colab_bin, "new", "-s", session_id, "--gpu", gpu]
                res_new = subprocess.run(cmd_new, capture_output=True, text=True, check=False)
                if res_new.returncode != 0:
                    err_msg = res_new.stderr.strip() or res_new.stdout.strip()
                    raise QuantError("BLOCKED_COMPUTE", f"Failed to allocate Colab {gpu} session: {err_msg}")

                # 2. Upload training partition
                cmd_up = [self.colab_bin, "upload", "-s", session_id, str(train_arrow), remote_arrow]
                res_up = subprocess.run(cmd_up, capture_output=True, text=True, check=False)
                if res_up.returncode != 0:
                    err_msg = res_up.stderr.strip() or res_up.stdout.strip()
                    raise QuantError("BLOCKED_COMPUTE", f"Failed to upload training data to Colab: {err_msg}")

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

                # 5. Cryptographic hash and permanent storage
                sha = file_hash(local_model)
                permanent_path = features_dir / f"{sha}.pkl"
                if not permanent_path.exists():
                    shutil.copy2(local_model, permanent_path)

                rel_path = f"python_features/{sha}.pkl"
                artifact = PythonFeatureArtifact(path=rel_path, sha256=sha)

                # Attach to candidate spec
                updated_spec = self.spec.model_copy(
                    update={"python_feature_artifact": artifact}
                )
                updated_spec._base_dir = self.run_log

                if output_candidate_path:
                    out_p = Path(output_candidate_path).resolve()
                    export_spec(updated_spec, out_p)

                return artifact, updated_spec

            finally:
                # Guaranteed cleanup: always terminate session
                cmd_stop = [self.colab_bin, "stop", "-s", session_id]
                subprocess.run(cmd_stop, capture_output=True, check=False)
