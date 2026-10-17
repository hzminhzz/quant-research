"""Independent tests for Tokyo calendar boundaries and inference failure modes."""
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from scripts.run_tokyo_alpha_map_program1_v1 import coefficient, controls, fit_hac, source_paths
from scripts.verify_tokyo_alpha_map_program1_v1 import verify_calendar

ROOT = Path(__file__).resolve().parents[1]


def test_calendar_roll_boundary_and_official_exception_dates():
    folder = ROOT / 'run_log/tokyo_fix_alpha_map_program1_20261010/calendar_audit_v1'
    if not folder.exists():
        pytest.skip('Mission calendar evidence absent')
    result = verify_calendar(folder)
    assert result['business_days'] == 1627
    assert result['nominal_events'] == 473


def test_singular_design_is_inconclusive():
    y = np.arange(40, dtype=float)
    x = np.ones((40, 2))
    result = coefficient(fit_hac(y, x))
    assert result['status'] == 'INCONCLUSIVE'
    assert result['p'] == 1
    assert result['estimate'] is None


def test_hac_translation_preserves_uncertainty_and_cost_units():
    rng = np.random.default_rng(42)
    y = rng.normal(3, 10, size=300)
    gross = coefficient(fit_hac(y))
    net = coefficient(fit_hac(y - 1.4))
    assert net['estimate'] == pytest.approx(gross['estimate'] - 1.4)
    np.testing.assert_allclose(net['ci95'], np.array(gross['ci95']) - 1.4)


def test_calendar_controls_use_reference_categories_without_collinearity():
    frame = pl.DataFrame({'weekday': [0, 1, 2, 3, 4] * 20, 'year': [2020] * 50 + [2021] * 50})
    treatment = np.array(([1, 0, 0, 1, 0] + [0, 1, 1, 0, 1]) * 10)
    x = controls(frame, treatment)
    assert x.shape == (100, 7)
    assert np.linalg.matrix_rank(x) == x.shape[1]


def test_source_partition_selector_excludes_holdout_before_read():
    paths = source_paths()
    if not paths:
        pytest.skip('Canonical local provider store absent')
    for path in paths:
        year = int(path.parents[2].name.split('=')[1])
        month = int(path.parents[1].name.split('=')[1])
        day = int(path.parent.name.split('=')[1])
        assert date(2020, 1, 1) <= date(year, month, day) < date(2026, 9, 1)
