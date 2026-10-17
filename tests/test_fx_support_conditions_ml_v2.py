"""Regression tests for immutable ML warm-up failure recovery."""

import pytest

from scripts.run_fx_support_conditions_trial import (
    MANIFEST,
    SOURCE,
    load_panel,
    ml_matrix,
)
from scripts.run_fx_support_conditions_ml_v2 import drop_nonfinite_warmup
from tests.conftest import require_path

pytestmark = pytest.mark.data


@pytest.fixture(autouse=True)
def _frozen_panel_must_exist():
    require_path(SOURCE)
    require_path(MANIFEST)


def test_only_known_nonfinite_warmup_excluded():
    source = load_panel()
    cleaned, excluded = drop_nonfinite_warmup(source)
    assert source.height == 1395
    assert cleaned.height == 1394
    assert excluded.height == 1
    assert excluded["symbol"][0] == "AUDUSD"
    assert cleaned.filter(cleaned["year"] >= 2017).height == source.filter(source["year"] >= 2017).height
    assert ml_matrix(cleaned).shape[0] == cleaned.height


def test_corrected_trial_makes_no_source_mutation():
    original = load_panel()
    cleaned, excluded = drop_nonfinite_warmup(original)
    assert original.height == 1395
    assert cleaned.height + excluded.height == original.height
    assert cleaned["event_timestamp"].max().year <= 2024
