import numpy as np

from scripts.run_crypto_tsmom_flow_diagnostics import paired_rank_ic_hac


def test_identical_scores_have_zero_paired_hac_difference() -> None:
    rng = np.random.default_rng(73)
    baseline = rng.integers(-1, 2, size=400).astype(np.float64)
    outcome = rng.normal(size=400)

    result, influence = paired_rank_ic_hac(
        baseline, baseline.copy(), outcome, label_horizon=24
    )

    assert result["paired_rank_ic_delta"] == 0.0
    assert np.all(influence == 0.0)
    assert result["paired_delta_hac"]["ci95_lower"] == 0.0
    assert result["paired_delta_hac"]["ci95_upper"] == 0.0
    assert result["paired_delta_hac"]["effective_lags"] >= 23
