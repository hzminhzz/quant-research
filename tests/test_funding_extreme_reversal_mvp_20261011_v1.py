from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from scripts import run_funding_extreme_reversal_mvp_20261011_v1 as study
from scripts.run_funding_extreme_reversal_mvp_20261011_v1 import (
    add_prior_event_thresholds,
    crosses_settlement,
)


def test_funding_threshold_uses_only_prior_90_events():
    start = datetime(2025, 10, 1, tzinfo=UTC)
    frame = pl.DataFrame(
        {
            "timestamp": [start + timedelta(hours=8 * i) for i in range(91)],
            "funding_rate": [0.001] * 90 + [0.25],
        }
    )

    result = add_prior_event_thresholds(frame)

    assert result["prior_p90"][89] is None
    assert result["prior_p90"][90] == 0.001


def test_settlement_interval_includes_entry_and_excludes_exit():
    entry = datetime(2026, 1, 1, 9, tzinfo=UTC)
    exit_ = entry + timedelta(hours=4)

    assert crosses_settlement(entry, exit_, [entry])
    assert crosses_settlement(entry, exit_, [exit_ - timedelta(milliseconds=1)])
    assert not crosses_settlement(entry, exit_, [exit_])
    assert not crosses_settlement(entry, exit_, [entry - timedelta(milliseconds=1)])
    assert crosses_settlement(entry.replace(tzinfo=None), exit_.replace(tzinfo=None), [entry])


def test_completed_versioned_trial_cannot_be_overwritten(tmp_path, monkeypatch):
    output = tmp_path / "existing_result"
    output.mkdir()
    (output / "trial_result.json").write_text('{"protected": true}')
    monkeypatch.setattr(study, "OUT", output)
    with pytest.raises(FileExistsError, match="already exist"):
        study.run()
    assert (output / "trial_result.json").read_text() == '{"protected": true}'
