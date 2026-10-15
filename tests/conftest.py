"""Shared pytest infrastructure for the quant-research test suite.

Marker lanes
------------
``data``
    Needs gitignored artifacts under ``data/`` or ``run_log/``. The test skips
    when the artifact is absent, so a fresh clone stays green.
``e2e``
    Drives a pipeline end to end instead of one function in isolation.
``slow``
    Runs longer than a few seconds.

Fast lane: ``uv run pytest -m "not data and not slow"``
Full lane: ``uv run pytest``

Data-dependent tests must both carry ``@pytest.mark.data`` and call
``require_path`` so they skip instead of failing when artifacts are absent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "data: requires gitignored artifacts under data/ or run_log/",
    )
    config.addinivalue_line("markers", "e2e: drives a pipeline end to end")
    config.addinivalue_line("markers", "slow: runs longer than a few seconds")


def resolve_artifact(path: str | Path) -> Path:
    """Resolve a repo-relative path; leave an absolute path untouched."""
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def require_path(path: str | Path) -> Path:
    """Return the artifact path, or skip the calling test when it is absent.

    Call this at the top of a data-dependent test, or from an autouse fixture
    when a whole module needs the artifact. A module-scoped fixture must call
    this function directly, because it cannot depend on a function-scoped
    fixture.
    """
    resolved = resolve_artifact(path)
    if not resolved.exists():
        pytest.skip(f"artifact not present: {resolved}")
    return resolved


@pytest.fixture
def repo_root() -> Path:
    """Absolute path to the repository root."""
    return REPO_ROOT
