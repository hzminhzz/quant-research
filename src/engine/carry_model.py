"""Modeled carry for price-proxy sleeves: explicit, hashed, never a zero fill.

The sidecar emits one settlement event per symbol per day with an explicit
`funding_rate` and the causal `mark_price` known at that instant, matching the
native runner's funding-event contract. The rate is derived from a named
government curve, adjusted by the product's declared income or lease assumption.

Sign convention, fixed and tested: `cashflow = -quantity * mark_price * rate`, so
a positive rate charges longs and pays shorts. A series whose price already
embeds financing (continuous futures) is rejected rather than double-charged.
Missing data -- no curve, no mark, or a metal without a defensible lease proxy --
is `BLOCKED_DATA`, never a synthetic zero series.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import polars as pl
from pydantic import Field, field_validator, model_validator

from .common import QuantError, digest, file_hash, safe_name, utc, write_json
from .spec_parser import Model


class CarryProduct(Model):
    """One instrument's declared carry economics."""
    symbol: str
    class_name: Literal['indices', 'metals']
    kind: Literal['spot_cfd', 'continuous_future']
    income_yield_bps: float = 0.0
    lease_rate_bps: float | None = None

    def annual_carry(self, risk_free: float) -> float:
        if self.class_name == 'indices':
            return risk_free - self.income_yield_bps / 10_000
        if self.lease_rate_bps is None:
            raise QuantError(
                'BLOCKED_DATA',
                f'{self.symbol}: no defensible lease-rate proxy; modeled carry is not a zero fill',
            )
        return risk_free - self.lease_rate_bps / 10_000


class CarryConfig(Model):
    curve_name: str
    tenor: Literal['US10Y', 'US2Y']
    settlement_hour_utc: int = Field(default=0, ge=0, le=23)
    days_per_year: int = Field(default=365, ge=1)
    annual_rate_is_percent: bool = True

    @field_validator('curve_name')
    @classmethod
    def safe_curve(cls, value: str) -> str:
        return safe_name(value)

    @model_validator(mode='after')
    def tenor_matches_curve(self):
        if self.curve_name in ('US10Y', 'US2Y') and self.tenor != self.curve_name:
            raise ValueError('tenor must match the named government curve')
        return self


@dataclass(frozen=True)
class CarrySidecar:
    events: pl.DataFrame
    metadata: dict
    sha256: str

    def write(self, directory: str | Path) -> dict:
        """Persist events and metadata; all validation happened before this call."""
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        events_path = target / 'carry_events.parquet'
        temporary = target / '.carry_events.tmp.parquet'
        self.events.write_parquet(temporary)
        temporary.replace(events_path)
        payload = {
            **self.metadata,
            'events_sha256': self.sha256,
            'events_file_sha256': file_hash(events_path),
        }
        metadata_path = target / 'carry_metadata.json'
        write_json(metadata_path, payload)
        return {'events': str(events_path), 'metadata': str(metadata_path),
                'events_sha256': self.sha256, 'events_file_sha256': payload['events_file_sha256']}


def carry_cashflow(quantity: float, mark_price: float, rate: float,
                   multiplier: float = 1.0) -> float:
    """Positive rate charges longs and pays shorts."""
    return -quantity * multiplier * mark_price * rate


def load_rate_curve(store: str | Path, name: str, *, start: datetime,
                    end: datetime) -> pl.DataFrame:
    """Read a named daily government curve as `timestamp, rate_pct`, no future rows."""
    safe_name(name)
    root = Path(store).resolve() / f'bonds_daily_{name}'
    files = sorted(root.glob('year=*/month=*/data.parquet'))
    if not files:
        raise QuantError('BLOCKED_DATA', f'Rate curve dataset is absent: {root}')
    frame = (pl.concat([pl.read_parquet(path) for path in files])
             .select('timestamp', pl.col('close').alias('rate_pct'))
             .filter((pl.col('timestamp') >= utc(start)) & (pl.col('timestamp') < utc(end)))
             .sort('timestamp')
             .unique('timestamp', keep='last'))
    if frame.is_empty():
        raise QuantError('BLOCKED_DATA', f'Rate curve {name} has no observations in the window')
    if frame.select(pl.col('rate_pct').is_null().any() | pl.col('rate_pct').is_finite().not_().any()).item():
        raise QuantError('BLOCKED_DATA', f'Rate curve {name} contains null or nonfinite yields')
    return frame


def _settlement_grid(start: datetime, end: datetime, hour: int) -> list[datetime]:
    first = utc(start)
    last = utc(end)
    day = first.date()
    grid = []
    while day < last.date():
        instant = datetime(day.year, day.month, day.day, hour, tzinfo=UTC)
        if instant >= first:
            grid.append(instant)
        day += timedelta(days=1)
    return grid


def build_carry_sidecar(prices: pl.DataFrame, curve: pl.DataFrame,
                        products: list[CarryProduct], config: CarryConfig,
                        *, start: datetime, end: datetime) -> CarrySidecar:
    """Join the curve and marks causally and emit one event per symbol per day."""
    for product in products:
        if product.kind == 'continuous_future':
            raise QuantError(
                'INVALID_SPEC',
                f'{product.symbol}: continuous futures already embed financing; '
                'an extra carry cashflow would double-charge',
            )
    if curve.is_empty():
        raise QuantError('BLOCKED_DATA', 'Carry requires a non-empty rate curve')
    if not {'timestamp', 'symbol', 'close'} <= set(prices.columns):
        raise QuantError('BLOCKED_DATA', 'Carry marks require timestamp, symbol and close')
    grid = _settlement_grid(start, end, config.settlement_hour_utc)
    if not grid:
        raise QuantError('INVALID_SPEC', 'Carry window produces no settlement instants')
    # Bar-start convention: a bar timestamped T only reveals its close after the
    # bar ends, so settlement lookups use observations strictly before T.
    settlements = (pl.DataFrame({'timestamp': grid})
                   .with_columns((pl.col('timestamp') - pl.duration(microseconds=1)).alias('join_at')))
    rate = (curve.select('timestamp', pl.col('rate_pct').alias('curve_rate_pct'),
                         pl.col('timestamp').alias('curve_at'))
            .rename({'timestamp': 'curve_key'}).sort('curve_key'))
    curve_joined = settlements.join_asof(rate, left_on='join_at', right_on='curve_key',
                                         strategy='backward')
    curve_sha256 = digest(rate.select('curve_at', 'curve_rate_pct').to_dicts())
    events = []
    for product in products:
        marks = (prices.filter(pl.col('symbol') == product.symbol)
                 .select('timestamp', pl.col('close').alias('mark_price'),
                         pl.col('timestamp').alias('mark_at'))
                 .rename({'timestamp': 'mark_key'}).sort('mark_key'))
        if marks.is_empty():
            raise QuantError('BLOCKED_DATA', f'{product.symbol}: no marks inside the carry window')
        joined = curve_joined.join_asof(marks, left_on='join_at', right_on='mark_key',
                                        strategy='backward')
        joined = joined.filter(pl.col('curve_rate_pct').is_not_null() & pl.col('mark_price').is_not_null())
        for row in joined.iter_rows(named=True):
            risk_free = row['curve_rate_pct'] / 100 if config.annual_rate_is_percent else row['curve_rate_pct']
            annual = product.annual_carry(risk_free)
            rate_daily = annual / config.days_per_year
            if not all(map(math.isfinite, (annual, rate_daily, row['mark_price']))):
                raise QuantError('BLOCKED_DATA', f'{product.symbol}: nonfinite carry input')
            events.append({
                'timestamp': row['timestamp'],
                'symbol': product.symbol,
                'funding_rate': rate_daily,
                'mark_price': row['mark_price'],
                'curve_at': row['curve_at'],
                'mark_at': row['mark_at'],
                'curve_name': config.curve_name,
            })
    if not events:
        raise QuantError('BLOCKED_DATA', 'Carry produced no settlement events')
    frame = (pl.DataFrame(events)
             .unique(['timestamp', 'symbol'], keep='last', maintain_order=True)
             .sort('timestamp', 'symbol'))
    metadata = {
        'status': 'MODELED',
        'formula': 'rate_daily = (risk_free - income_or_lease) / days_per_year; '
                   'cashflow = -quantity * mark_price * rate_daily',
        'sign_convention': 'positive_rate_charges_longs',
        'curve': {'name': config.curve_name, 'tenor': config.tenor,
                  'sha256': curve_sha256,
                  'scope': 'selected rows in window; source partitions not byte-hashed',
                  'annual_rate_is_percent': config.annual_rate_is_percent},
        'settlement_hour_utc': config.settlement_hour_utc,
        'days_per_year': config.days_per_year,
        'products': [product.model_dump(mode='json') for product in products],
        'assumptions': [
            'Daily settlement accrual; no compounding inside a day.',
            'Government yield is a modeled risk-free proxy, not observed broker financing.',
            'Mark price is the last close at or before the settlement instant.',
        ],
        'window': {'start': utc(start).isoformat(), 'end': utc(end).isoformat()},
    }
    sha256 = digest({'metadata': metadata, 'events': frame.to_dicts()})
    return CarrySidecar(events=frame, metadata=metadata, sha256=sha256)
