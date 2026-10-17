"""Authorized holdout exposure guardrails; reuse original source without parameter tuning."""
from datetime import datetime, timezone
import pytest
from scripts.mechanicalpremia_authorized_2025_2026_adapter import (
    HOLDOUT, FILES, H_ASSETS, D_ASSETS, load_development,
    TRIAL_WEIGHTS,
)
def test_new_common_market_cutoff():
    assert HOLDOUT == datetime(2026, 10, 12, tzinfo=timezone.utc)
    assert set(FILES) == {"US500","US100","DE30","EU50"}
    assert H_ASSETS == {"US500","US100","DE30"}
    assert D_ASSETS == {"US500","US100","DE30","EU50"}
def test_only_authorized_periods():
    with pytest.raises(ValueError):
        load_development("US500",from_year=2024,until_year=2024)
    with pytest.raises(ValueError):
        load_development("US500",from_year=2027,until_year=2027)
    with pytest.raises(ValueError):
        load_development("US500",from_year=2025,until_year=2026)
def test_original_portfolio_weights_unchanged():
    a=TRIAL_WEIGHTS["PORTFOLIO-SOURCE-RISK"]
    assert (a.h, a.d) == (0.2336, 0.7664)
    b=TRIAL_WEIGHTS["PORTFOLIO-EQUAL-RISK"]
    assert (b.h,b.d)==(0.5,0.5)
