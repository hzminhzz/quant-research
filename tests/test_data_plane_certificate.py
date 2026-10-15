"""Synthetic adversarial checks for in-memory Phase 1 certification."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pandas as pd
import polars as pl
import pytest

from src.data_plane import (
    CertificateError,
    DataPolicy,
    asof_frame,
    certify_frame,
    verify_certificate,
)


def fixture_data(**changes):
    policy = DataPolicy(
        dataset_key="dukascopy_usatech", catalog_identity="catalog-v1",
        source_vendor="Dukascopy", source_symbol="USATECH.IDX/USD",
        product_class="cfd", role="price_proxy", proxy_target="CME NQ futures adaptation",
        volume_semantics="broker_tick_or_quote_proxy", timezone="America/New_York",
        calendar="exchange", exchange_calendar="XNYS", revision_policy="append_only",
        bar_duration=timedelta(minutes=1),
    )
    policy = replace(policy, **changes)
    entry = {field: getattr(policy, field) for field in (
        "dataset_key", "source_vendor", "source_symbol", "product_class", "role",
        "proxy_target", "volume_semantics", "timezone", "calendar", "exchange_calendar",
        "revision_policy",
    )}
    entry.update(authority="canonical", qualification="accepted")
    catalog = {"catalog_identity": "catalog-v1", "entries": [entry]}
    event = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    row = {"symbol": policy.source_symbol, "event_at": event,
           "available_at": event + timedelta(minutes=1), "open": 100., "high": 102.,
           "low": 99., "close": 101., "volume": 12.}
    if policy.revision_policy == "revised":
        row.update(vintage_at=event, recorded_at=event + timedelta(minutes=2))
    if policy.volume_semantics == "absent":
        row.pop("volume")
    return policy, catalog, row


@pytest.mark.parametrize("backend", [pd.DataFrame, pl.DataFrame])
def test_valid_and_cache_revalidation(backend):
    policy, catalog, row = fixture_data()
    frame = backend([row])
    cert = certify_frame(frame, catalog=catalog, policy=policy)
    verify_certificate(cert, frame, catalog=catalog, policy=policy)
    assert cert.row_count == 1
    changed = backend([{**row, "close": 100.5}])
    with pytest.raises(CertificateError, match="identity drift"):
        verify_certificate(cert, changed, catalog=catalog, policy=policy)
    catalog["entries"][0]["qualification"] = "accepted_with_exclusions"
    with pytest.raises(CertificateError, match="identity drift"):
        verify_certificate(cert, frame, catalog=catalog, policy=policy)


@pytest.mark.parametrize("field,value,reason", [
    ("available_at", datetime(2026, 1, 5, 14, 30, tzinfo=UTC), "completion"),
    ("event_at", datetime(2026, 1, 5, 14, 30, tzinfo=UTC).replace(tzinfo=None), "timezone-aware"),
    ("close", 103., "OHLC"),
    ("open", float("nan"), "finite"),
    ("volume", -1., "nonnegative"),
    ("symbol", "NQ.F", "source symbol"),
    ("event_at", datetime(2026, 1, 3, 14, 30, tzinfo=UTC), "session"),
    ("event_at", datetime(2026, 1, 5, 14, 29, tzinfo=UTC), "session"),
])
def test_bad_rows_fail(field, value, reason):
    policy, catalog, row = fixture_data()
    row[field] = value
    with pytest.raises(CertificateError, match=reason):
        certify_frame(pd.DataFrame([row]), catalog=catalog, policy=policy)


def test_duplicate_unsorted_and_limit():
    policy, catalog, row = fixture_data()
    with pytest.raises(CertificateError, match="duplicate"):
        certify_frame(pd.DataFrame([row, row]), catalog=catalog, policy=policy)
    next_row = {**row, "event_at": row["event_at"] + timedelta(minutes=1),
                "available_at": row["available_at"] + timedelta(minutes=1)}
    with pytest.raises(CertificateError, match="sorted"):
        certify_frame(pd.DataFrame([next_row, row]), catalog=catalog, policy=policy)
    with pytest.raises(CertificateError, match="row limit"):
        certify_frame(pd.DataFrame([row, next_row]), catalog=catalog,
                      policy=replace(policy, max_rows=1))


def test_revisions_require_vintage_and_recorded_clock():
    policy, catalog, row = fixture_data(revision_policy="revised")
    later = {**row, "close": 100.5, "vintage_at": row["event_at"] + timedelta(minutes=2),
             "available_at": row["event_at"] + timedelta(minutes=2),
             "recorded_at": row["event_at"] + timedelta(minutes=3)}
    certify_frame(pl.DataFrame([row, later]), catalog=catalog, policy=policy)
    for edit in ({"recorded_at": row["recorded_at"]},
                 {"vintage_at": later["recorded_at"]},
                 {"recorded_at": later["available_at"] - timedelta(seconds=1)}):
        with pytest.raises(CertificateError, match="revision"):
            certify_frame(pl.DataFrame([row, {**later, **edit}]), catalog=catalog, policy=policy)
    with pytest.raises(CertificateError, match="missing required"):
        certify_frame(pd.DataFrame([row]).drop(columns="vintage_at"), catalog=catalog, policy=policy)


def test_catalog_scope_and_schema_fail_closed():
    policy, catalog, row = fixture_data()
    with pytest.raises(CertificateError, match="catalog identity"):
        certify_frame(pd.DataFrame([row]), catalog={**catalog, "catalog_identity": "v2"}, policy=policy)
    with pytest.raises(CertificateError, match="catalog entry"):
        certify_frame(pd.DataFrame([row]), catalog={**catalog, "entries": []}, policy=policy)
    with pytest.raises(CertificateError, match="declared policy"):
        certify_frame(pd.DataFrame([row]), catalog=catalog, policy=replace(policy, source_symbol="NQ.F"))
    with pytest.raises(CertificateError, match="qualification"):
        certify_frame(pd.DataFrame([row]), catalog={**catalog, "entries": [
            {**catalog["entries"][0], "qualification": "unknown"}]}, policy=policy)
    with pytest.raises(CertificateError, match="numeric dtype"):
        certify_frame(pd.DataFrame([{**row, "volume": "12"}]), catalog=catalog, policy=policy)
    with pytest.raises(CertificateError, match="missing required"):
        certify_frame(pd.DataFrame([row]).drop(columns="available_at"), catalog=catalog, policy=policy)
    with pytest.raises(CertificateError, match="CFD"):
        p, c, r = fixture_data(volume_semantics="genuine_exchange_traded")
        certify_frame(pd.DataFrame([r]), catalog=c, policy=p)


def test_calendar_dst_and_holiday():
    policy, catalog, row = fixture_data()
    row["event_at"] = datetime(2026, 1, 1, 14, 30, tzinfo=UTC)
    row["available_at"] = row["event_at"] + timedelta(minutes=1)
    with pytest.raises(CertificateError, match="session"):
        certify_frame(pd.DataFrame([row]), catalog=catalog, policy=policy)
    policy, catalog, row = fixture_data()
    # 09:30 local after spring DST switch is 13:30 UTC, not 14:30 UTC.
    row["event_at"] = datetime(2026, 3, 9, 13, 30, tzinfo=UTC)
    row["available_at"] = row["event_at"] + timedelta(minutes=1)
    certify_frame(pd.DataFrame([row]), catalog=catalog, policy=policy)


def test_null_time_and_recorded_clock():
    policy, catalog, row = fixture_data()
    with pytest.raises(CertificateError, match="timezone-aware datetime"):
        certify_frame(pd.DataFrame([{**row, "event_at": pd.NaT}]), catalog=catalog, policy=policy)
    with pytest.raises(CertificateError, match="recorded_at precedes"):
        certify_frame(pd.DataFrame([{**row, "recorded_at": row["event_at"]}]),
                      catalog=catalog, policy=policy)


@pytest.mark.parametrize("code,zone,event,break_time", [
    ("XHKG", "Asia/Hong_Kong", datetime(2026, 1, 5, 1, 30, tzinfo=UTC),
     datetime(2026, 1, 5, 4, 0, tzinfo=UTC)),
    ("XTKS", "Asia/Tokyo", datetime(2026, 1, 5, 0, 0, tzinfo=UTC),
     datetime(2026, 1, 5, 2, 30, tzinfo=UTC)),
])
def test_authoritative_lunch_breaks(code, zone, event, break_time):
    policy, catalog, row = fixture_data(exchange_calendar=code, timezone=zone)
    row.update(event_at=event, available_at=event + timedelta(minutes=1))
    certify_frame(pd.DataFrame([row]), catalog=catalog, policy=policy)
    row.update(event_at=break_time, available_at=break_time + timedelta(minutes=1))
    with pytest.raises(CertificateError, match="calendar session"):
        certify_frame(pd.DataFrame([row]), catalog=catalog, policy=policy)


def test_early_close_and_overnight():
    policy, catalog, row = fixture_data()
    # 2026-11-27 NYSE closes 13:00 ET (18:00 UTC).
    before = datetime(2026, 11, 27, 17, 59, tzinfo=UTC)
    row.update(event_at=before, available_at=before + timedelta(minutes=1))
    certify_frame(pd.DataFrame([row]), catalog=catalog, policy=policy)
    row.update(event_at=before + timedelta(minutes=1), available_at=before + timedelta(minutes=2))
    with pytest.raises(CertificateError, match="calendar session"):
        certify_frame(pd.DataFrame([row]), catalog=catalog, policy=policy)
    policy, catalog, row = fixture_data(exchange_calendar="CMES", timezone="America/Chicago",
                                        product_class="dated_future", role="tradable_product",
                                        proxy_target=None, volume_semantics="genuine_exchange_traded")
    # Sunday evening open belongs to Monday session.
    opened = datetime(2026, 1, 4, 23, tzinfo=UTC)
    row.update(event_at=opened, available_at=opened + timedelta(minutes=1))
    certify_frame(pl.DataFrame([row]), catalog=catalog, policy=policy)


def test_us_eu_dst_transition_and_coverage():
    policy, catalog, row = fixture_data()
    # US is on daylight time, UK still on standard time on March 23.
    usa = datetime(2026, 3, 23, 13, 30, tzinfo=UTC)
    row.update(event_at=usa, available_at=usa + timedelta(minutes=1))
    certify_frame(pd.DataFrame([row]), catalog=catalog, policy=policy)
    london, lon_catalog, lon_row = fixture_data(exchange_calendar="XLON", timezone="Europe/London")
    lon_row.update(event_at=datetime(2026, 3, 23, 8, tzinfo=UTC),
                   available_at=datetime(2026, 3, 23, 8, 1, tzinfo=UTC))
    cert = certify_frame(pd.DataFrame([lon_row]), catalog=lon_catalog, policy=london)
    assert cert.calendar_version and cert.tzdata_version and cert.timezone_sha256
    lon_row.update(event_at=datetime(2026, 3, 23, 7, tzinfo=UTC),
                   available_at=datetime(2026, 3, 23, 7, 1, tzinfo=UTC))
    with pytest.raises(CertificateError, match="calendar session"):
        certify_frame(pd.DataFrame([lon_row]), catalog=lon_catalog, policy=london)
    with pytest.raises(CertificateError, match="calendar coverage"):
        certify_frame(pd.DataFrame([row]), catalog=catalog,
                      policy=replace(policy, coverage_start=datetime(2030, 1, 1, tzinfo=UTC),
                                     coverage_end=datetime(2030, 1, 2, tzinfo=UTC)))


def test_missing_grid_and_asof_latest_eligible():
    policy, catalog, row = fixture_data(revision_policy="revised")
    next_event = row["event_at"] + timedelta(minutes=1)
    next_row = {**row, "event_at": next_event, "vintage_at": next_event,
                "available_at": next_event + timedelta(minutes=1),
                "recorded_at": next_event + timedelta(minutes=2)}
    later = {**row, "close": 100.5, "vintage_at": row["event_at"] + timedelta(minutes=3),
             "available_at": row["event_at"] + timedelta(minutes=3),
             "recorded_at": row["event_at"] + timedelta(minutes=4)}
    # Revisions must be contiguous by event, not interleaved.
    frame = pl.DataFrame([row, later, next_row])
    cert = certify_frame(frame, catalog=catalog, policy=policy)
    assert asof_frame(cert, frame, catalog=catalog, policy=policy,
                      decision_at=row["recorded_at"])["close"].to_list() == [101.]
    assert asof_frame(cert, frame, catalog=catalog, policy=policy,
                      decision_at=later["recorded_at"])["close"].to_list() == [100.5, 101.]
    with pytest.raises(CertificateError, match="missing bars"):
        certify_frame(pl.DataFrame([row, later]), catalog=catalog,
                      policy=replace(policy, coverage_start=row["event_at"],
                                     coverage_end=next_event + timedelta(minutes=1)))
    with pytest.raises(CertificateError, match="missing bars"):
        certify_frame(pd.DataFrame([row]), catalog=catalog,
                      policy=replace(policy, coverage_start=row["event_at"],
                                     coverage_end=next_event + timedelta(minutes=1)))


def test_tradable_spot_perpetual_and_vendor_not_inferred():
    for cls in ("spot", "perpetual"):
        policy, catalog, row = fixture_data(product_class=cls, role="tradable_product",
                                            proxy_target=None, calendar="continuous",
                                            exchange_calendar=None)
        certify_frame(pd.DataFrame([row]), catalog=catalog, policy=policy)
    policy, catalog, row = fixture_data(role="tradable_product", proxy_target=None)
    certify_frame(pl.DataFrame([row]), catalog=catalog, policy=policy)
    policy, catalog, row = fixture_data(product_class="spot", role="tradable_product",
                                        proxy_target=None, calendar="continuous", exchange_calendar=None)
    catalog["entries"][0]["product_class"] = "cfd"
    with pytest.raises(CertificateError, match="declared policy"):
        certify_frame(pd.DataFrame([row]), catalog=catalog, policy=policy)


def test_break_gap_grid_and_schedule_identity(monkeypatch):
    policy, catalog, row = fixture_data(exchange_calendar="XHKG", timezone="Asia/Hong_Kong")
    before = datetime(2026, 1, 5, 3, 59, tzinfo=UTC)
    after = datetime(2026, 1, 5, 5, tzinfo=UTC)
    first = {**row, "event_at": before, "available_at": before + timedelta(minutes=1)}
    second = {**row, "event_at": after, "available_at": after + timedelta(minutes=1)}
    frame = pd.DataFrame([first, second])
    cert = certify_frame(frame, catalog=catalog, policy=policy)
    assert asof_frame(cert, frame, catalog=catalog, policy=policy,
                      decision_at=before)["close"].empty
    import src.data_plane.certificate as certificate_module

    original = certificate_module._timezone_identity
    monkeypatch.setattr(certificate_module, "_timezone_identity",
                        lambda zone: ("changed-tzfile", original(zone)[1]))
    with pytest.raises(CertificateError, match="identity drift"):
        verify_certificate(cert, frame, catalog=catalog, policy=policy)


def test_missing_minute_between_observed_events_and_unsupported_calendar():
    policy, catalog, row = fixture_data()
    later = {**row, "event_at": row["event_at"] + timedelta(minutes=2),
             "available_at": row["available_at"] + timedelta(minutes=2)}
    with pytest.raises(CertificateError, match="missing bars"):
        certify_frame(pl.DataFrame([row, later]), catalog=catalog, policy=policy)
    policy, catalog, row = fixture_data(exchange_calendar="UNSUPPORTED")
    with pytest.raises(CertificateError, match="exchange calendar"):
        certify_frame(pd.DataFrame([row]), catalog=catalog, policy=policy)
