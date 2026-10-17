from __future__ import annotations

from datetime import UTC, datetime

import polars as pl

from scripts.prepare_crypto_xs_plain_funding_phase4_20261015 import OUT


def test_phase4_output_path_is_separate_from_phase3():
    assert "phase4" in OUT.name
    assert "mvp" not in OUT.name
