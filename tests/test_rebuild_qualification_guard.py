"""Regression guards for incomplete qualification and synthetic refit mechanics."""

from types import SimpleNamespace

import numpy as np
import pytest

from src.validation import oracle
from tests.test_oracle_policy import _oracle_input


def _high_diagnostic_scores(monkeypatch):
    # Deliberately perfect diagnostics must never upgrade missing provenance.
    monkeypatch.setattr(oracle, "compute_pbo", lambda train, test: SimpleNamespace(pbo=0.0))
    monkeypatch.setattr(
        oracle, "deflated_sharpe_ratio",
        lambda *args, **kwargs: SimpleNamespace(
            n_trials_raw=2, n_trials_effective=2.0, probability=1.0,
            has_adequate_sample=True,
        ),
    )
    monkeypatch.setattr(
        oracle, "compute_return_statistics", lambda returns: (float(np.mean(returns)),)
    )


def test_500_synthetic_refits_cannot_grant_qualification(monkeypatch):
    inputs = _oracle_input()
    _high_diagnostic_scores(monkeypatch)
    inputs["permutations"] = 500
    original = inputs["refit"]
    calls = []

    def counted_refit(target, splits):
        calls.append(target.copy())
        return original(target, splits)

    inputs["refit"] = counted_refit
    result = oracle.evaluate_phase3(**inputs)
    assert len(calls) == 501  # Observed refit plus all 500 target permutations.
    assert np.array_equal(calls[0], inputs["targets"])
    assert any(not np.array_equal(target, calls[0]) for target in calls[1:])
    assert result.diagnostic_thresholds_passed
    assert result.status == "INCONCLUSIVE"
    assert not result.holdout_access
    assert "GLOBAL_LEDGER_COVERAGE_NOT_DERIVED" in result.qualification_blockers
    assert "JOINT_IC_AND_NET_SHARPE_ENDPOINTS_NOT_BOUND" in result.qualification_blockers
    assert "OOS_PATH_RETURN_DISTRIBUTION_NOT_ASSEMBLED" in result.qualification_blockers


def test_p_value_threshold_is_strict(monkeypatch):
    inputs = _oracle_input()
    _high_diagnostic_scores(monkeypatch)
    first = oracle.evaluate_phase3(**inputs)
    inputs["alpha"] = first.selected_p
    second = oracle.evaluate_phase3(**inputs)
    assert second.selected_p == first.selected_p
    assert not second.diagnostic_thresholds_passed
    assert second.status == "INCONCLUSIVE"


def test_tied_pbo_scores_are_inconclusive_not_column_order_success():
    inputs = _oracle_input()
    original = inputs["refit"]

    def tied_refit(target, splits):
        result = original(target, splits)
        return oracle.RefitResult(
            result.statistics, result.returns,
            np.ones_like(result.train_scores), result.test_scores,
        )

    inputs["refit"] = tied_refit
    with pytest.raises(oracle.OracleContractError, match="tie policy"):
        oracle.evaluate_phase3(**inputs)


def test_public_catalog_uses_one_certificate_implementation():
    from src.data_plane import catalog, certificate

    assert catalog.certify is certificate.certify_frame
    assert catalog.verify is certificate.verify_certificate
    assert catalog.view_asof is certificate.asof_frame


@pytest.mark.parametrize("field", [
    "product_class", "role", "volume_semantics", "revision_policy",
])
def test_matching_catalog_does_not_validate_unknown_policy_values(field):
    import polars as pl
    from src.data_plane.catalog import CertificateError, certify
    from tests.test_data_plane_certificate import fixture_data

    policy, catalog, row = fixture_data(**{field: "unrecognized"})
    with pytest.raises(CertificateError, match=f"unsupported {field}"):
        certify(pl.DataFrame([row]), catalog=catalog, policy=policy)
