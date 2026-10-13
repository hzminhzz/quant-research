"""Pinned CFD source and managed feature parity without external data."""
from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from src.research_control.dukascopy_migration import (
    DATA_SYMBOL,
    SOURCE_SHA256,
    checked_source,
    dukascopy_feature_contract,
    features_for_legacy_rules,
    strict_sessions,
)


def synthetic_cfds(count=90):
    start = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    return pl.DataFrame({
        "timestamp": [start + timedelta(minutes=i) for i in range(count)],
        "symbol": [DATA_SYMBOL] * count,
        "open": [100 + 0.1 * i for i in range(count)],
        "high": [101 + 0.1 * i for i in range(count)],
        "low": [99 + 0.1 * i for i in range(count)],
        "close": [100.5 + 0.1 * i for i in range(count)],
        "volume": [float(i % 17 + 20) for i in range(count)],
    })


def test_managed_dukascopy_native_adx_vwap_and_legacy_entry_level_parity():
    source = synthetic_cfds()
    contract = dukascopy_feature_contract("dukascopy-migration-synthetic")
    assert contract.dataset.source_symbol == "USATECH.IDX/USD"
    assert contract.dataset.volume_semantics == "broker_tick_or_quote_proxy"
    result, proof = features_for_legacy_rules(source, contract)
    assert proof.proof.checks["native_execution_through_engineer"]
    assert proof.proof.checks["completed_bar_availability"]

    old_tp = source.select(pl.col("high").rolling_max(5))["high"]
    old_sl = source.select(pl.col("low").rolling_min(20))["low"]
    for idx in range(30, source.height):
        assert result["next_tp"][idx] == pytest.approx(old_tp[idx])
        assert result["next_sl"][idx] == pytest.approx(old_sl[idx])
        vwap = sum(
            ((source["high"][j] + source["low"][j] + source["close"][j]) / 3)
            * source["volume"][j] for j in range(idx + 1)
        ) / sum(source["volume"][j] for j in range(idx + 1))
        assert result["vwap"][idx] == pytest.approx(vwap)
        assert result["available_at"][idx] == source["timestamp"][idx] + timedelta(minutes=1)
        assert result["prior_adx"][idx] == pytest.approx(result["adx"][idx - 1])
    assert result["or_count"][0] == 30
    assert result["or_high"][0] == pytest.approx(max(source["high"][:30]))


def test_unapproved_cme_source_and_missing_cfd_data_block(tmp_path):
    contract = dukascopy_feature_contract("dukascopy-migration-synthetic")
    raw = contract.model_dump(mode="json")
    raw["dataset"]["source_symbol"] = "NQ.F"
    from src.research_control.contracts import ResearchContractV1
    with pytest.raises(ValueError, match="not Dukascopy"):
        ResearchContractV1.model_validate(raw)

    file = tmp_path / "cfds.parquet"
    synthetic_cfds().write_parquet(file)
    with pytest.raises(ValueError, match="SOURCE_IDENTITY_CONFLICT"):
        checked_source(file)
    data = synthetic_cfds().with_columns(pl.lit("NQ.F").alias("symbol"))
    data.write_parquet(file)
    import hashlib
    with pytest.raises(ValueError, match="SOURCE_IDENTITY_CONFLICT"):
        checked_source(file, expected_sha256=hashlib.sha256(file.read_bytes()).hexdigest())


def test_session_cutoff_requires_actual_1514_and_no_retune_or_holdout():
    frame, _ = features_for_legacy_rules(
        synthetic_cfds(), dukascopy_feature_contract("dukascopy-migration-synthetic")
    )
    selected, metadata = strict_sessions(frame, date(2026, 1, 5), date(2026, 1, 5))
    assert selected.is_empty()
    assert metadata["excluded_days"]["2026-01-05"] == "INCOMPLETE_CFD_GRID"
    assert metadata["hard_flat_at"].startswith("15:14")
    assert metadata["source_sha256"] == SOURCE_SHA256
    assert not metadata["cme_volume_verified"]
    with pytest.raises(ValueError, match="HOLDOUT_EXPOSED"):
        strict_sessions(frame, date(2026, 1, 5), date(2026, 11, 1))
