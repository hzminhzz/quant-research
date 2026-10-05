from __future__ import annotations

import numpy as np

from src.orb_ml_research import risk_throttle


def test_risk_throttle_never_deletes_trades_and_is_monotonic():
    predicted = np.array([-3.0, -1.0, 0.0, 1.0, 3.0])
    sizes = risk_throttle(
        predicted,
        scale_r=1.0,
        floor=0.50,
        ceiling=1.00,
    )

    assert np.all(sizes >= 0.50)
    assert np.all(sizes <= 1.00)
    assert np.all(np.diff(sizes) > 0)
    assert np.isclose(sizes[2], 0.75)
