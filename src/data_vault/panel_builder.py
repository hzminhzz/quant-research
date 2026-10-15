"""Incremental, schema-driven local ingestion. No network or current-universe filter.

The twelve columns are a consumer view. Manifest/source hashes and funding event
sidecars retain provenance. Historical event availability is an explicit source
assumption, not a fabricated historical ingestion timestamp.
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pyarrow.parquet as pq

from src.engine.common import QuantError, digest, file_hash, safe_name, utc, write_json

CANONICAL_COLUMNS = ['timestamp', 'symbol', 'open', 'high', 'low', 'close', 'volume',
                     'carry_rate', 'spread_bps', 'session_id', 'bar_in_session', 'is_tradable']
SCHEMA = {'timestamp': pl.Datetime('us', 'UTC'), 'symbol': pl.String,
          **{k: pl.Float64 for k in ('open', 'high', 'low', 'close', 'volume', 'carry_rate', 'spread_bps')},
          'session_id': pl.String, 'bar_in_session': pl.Int32, 'is_tradable': pl.Boolean}


@dataclass(frozen=True)
class Source:
    symbol: str
    prices: str
    funding: str | None
    source_bar_seconds: int
    venue: str
    product: str = 'perpetual'


def parquet_bounds(path: Path) -> tuple[datetime, datetime]:
    parquet = pq.ParquetFile(path)
    timestamp_type = parquet.schema_arrow.field('timestamp').type
    if not getattr(timestamp_type, 'tz', None):
        raise QuantError('BLOCKED_DATA', f'Source timestamp must have an explicit timezone: {path}')
    metadata = parquet.metadata
    index = next((i for i in range(metadata.num_columns)
                  if metadata.schema.column(i).name == 'timestamp'), None)
    if index is None or not metadata.num_row_groups:
        raise QuantError('BLOCKED_DATA', f'No timestamp row-group statistics: {path}')
    lower, upper = [], []
    for i in range(metadata.num_row_groups):
        stats = metadata.row_group(i).column(index).statistics
        if stats is None or not stats.has_min_max:
            raise QuantError('BLOCKED_DATA', f'Timestamp statistics required: {path}')
        lower.append(utc(stats.min)); upper.append(utc(stats.max))
    return min(lower), max(upper)


def validate_panel(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.columns != CANONICAL_COLUMNS:
        raise QuantError('BLOCKED_DATA', 'Canonical panel requires the exact ordered twelve columns')
    timestamp_dtype = frame.schema['timestamp']
    if not isinstance(timestamp_dtype, pl.Datetime) or timestamp_dtype.time_zone is None:
        raise QuantError('BLOCKED_DATA', 'Canonical timestamps require an explicit timezone; naive source clocks are not silently relabeled UTC')
    frame = frame.cast(SCHEMA, strict=True).sort('symbol', 'timestamp')
    if frame.is_empty():
        raise QuantError('BLOCKED_DATA', 'Empty canonical panel')
    if any(frame[c].null_count() for c in CANONICAL_COLUMNS):
        raise QuantError('BLOCKED_DATA', 'Null canonical fields; missing funding is not zero funding')
    if frame.select(pl.struct('timestamp', 'symbol').n_unique()).item() != frame.height:
        raise QuantError('BLOCKED_DATA', 'Duplicate symbol/timestamp rows')
    numeric = ['open', 'high', 'low', 'close', 'volume', 'carry_rate', 'spread_bps']
    if frame.select(pl.any_horizontal([~pl.col(c).is_finite() for c in numeric]).any()).item():
        raise QuantError('BLOCKED_DATA', 'Nonfinite canonical values')
    bad = ((pl.min_horizontal('open', 'high', 'low', 'close') <= 0)
           | (pl.col('high') < pl.max_horizontal('open', 'close'))
           | (pl.col('low') > pl.min_horizontal('open', 'close'))
           | (pl.col('volume') < 0) | (pl.col('spread_bps') < 0))
    if frame.filter(bad).height:
        raise QuantError('BLOCKED_DATA', 'Invalid OHLC, volume, or spread')
    return frame


class PanelBuilder:
    def __init__(self, store: str | Path, output: str | Path,
                 protected_test_start: str | datetime = '2026-01-01T00:00:00Z', *,
                 funding_time_tolerance_ms: int = 1000,
                 funding_mark_policy: str = 'trade_open_proxy'):
        self.store, self.output = Path(store).resolve(), Path(output).resolve()
        self.cutoff = utc(protected_test_start)
        if not 0 <= funding_time_tolerance_ms <= 60000:
            raise QuantError('INVALID_SPEC', 'Funding boundary tolerance must be between zero and 60000 milliseconds')
        if funding_mark_policy not in ('observed_only', 'trade_open_proxy'):
            raise QuantError('INVALID_SPEC', 'Unknown funding mark policy')
        self.funding_time_tolerance_ms = funding_time_tolerance_ms
        self.funding_mark_policy = funding_mark_policy

    def discover(self) -> list[Source]:
        """Include historical-only source directories; deterministic resolution priority."""
        funding = {p.name.removeprefix('crypto_futures_funding_').removesuffix('_PERP'): p
                   for p in self.store.glob('crypto_futures_funding_*_PERP') if p.is_dir()}
        found: dict[str, tuple[int, Path, int, str]] = {}
        consolidated = self.store / 'crypto_futures_ohlcv_1h_BINANCE_UM_PERP'
        for path in sorted(consolidated.glob('symbol=*')):
            if path.is_dir():
                found[path.name.removeprefix('symbol=')] = (0, path, 3600, 'BINANCE_UM')
        for prefix, priority, seconds in [('crypto_futures_hourly_', 1, 3600),
                                          ('crypto_futures_minute_', 2, 60)]:
            for path in sorted(self.store.glob(prefix + '*_PERP')):
                symbol = path.name.removeprefix(prefix).removesuffix('_PERP')
                if symbol not in found:
                    found[symbol] = (priority, path, seconds, 'STORE_METADATA_REQUIRED')
        return [Source(s + '_PERP', str(row[1]), str(funding[s]) if s in funding else None,
                       row[2], row[3]) for s, row in sorted(found.items())]

    def discovery_report(self) -> dict[str, Any]:
        sources = self.discover()
        return {'store': str(self.store), 'price_symbols': len(sources),
                'funding_directories': sum(p.is_dir() for p in self.store.glob('crypto_futures_funding_*_PERP')),
                'matched_symbols': sum(s.funding is not None for s in sources),
                'sources': [asdict(s) for s in sources],
                'survivorship_free_source_coverage': 'not_established_by_directory_discovery'}

    def _files(self, root: Path, start: datetime, end: datetime, *, protected: bool) -> list[Path]:
        result = []
        for path in sorted(root.rglob('*.parquet')):
            # Prune Hive paths before even reading Parquet footer metadata.
            years = [int(p[5:]) for p in path.parts if re.fullmatch(r'year=\d{4}', p)]
            if years and (years[-1] < start.year or years[-1] > (end - timedelta(microseconds=1)).year):
                continue
            lo, hi = parquet_bounds(path)
            if hi < start or lo >= end:
                continue
            if not protected and hi >= self.cutoff:
                raise QuantError('BLOCKED_DATA', 'Mixed raw holdout file requires a separate trusted partitioning job')
            result.append(path)
        if not result:
            raise QuantError('BLOCKED_DATA', f'No source files in declared window: {root}')
        return result

    def build(self, *, start: str | datetime, end: str | datetime,
              symbols: list[str] | None = None, bar_seconds: int = 3600,
              spread_bps: float = 0.0, spread_assumption: str,
              allow_unverified_venue: bool = False, trusted_partitioning: bool = False) -> dict[str, Any]:
        start, end = utc(start), utc(end)
        if start >= end or (end > self.cutoff and not trusted_partitioning):
            raise QuantError('BLOCKED_DATA', 'Protected ingestion requires explicit trusted_partitioning; research readers cannot request it')
        if bar_seconds < 60 or bar_seconds % 60 or spread_bps < 0:
            raise QuantError('INVALID_SPEC', 'Invalid bar duration/spread')
        if not spread_assumption:
            raise QuantError('INVALID_SPEC', 'Declare observed or assumed spread semantics')
        selected = self.discover()
        if symbols is not None:
            wanted = {s if s.endswith('_PERP') else s + '_PERP' for s in symbols}
            selected = [s for s in selected if s.symbol in wanted]
            if wanted != {s.symbol for s in selected}:
                raise QuantError('BLOCKED_DATA', 'Requested price sources were not all discovered')
        entries, excluded = [], []
        segments = [('development', start, min(end, self.cutoff))]
        if end > self.cutoff:
            segments.append(('protected', max(start, self.cutoff), end))
        for source in selected:
            for kind, first, last in segments:
                if first >= last:
                    continue
                try:
                    if source.venue == 'STORE_METADATA_REQUIRED' and not allow_unverified_venue:
                        raise QuantError('BLOCKED_SOURCE', 'Standalone store venue needs explicit qualification')
                    frame, funding, provenance = self._build_symbol(source, first, last, bar_seconds,
                                                                    spread_bps, spread_assumption,
                                                                    trusted_partitioning=trusted_partitioning)
                    entries.extend(self.publish(frame, funding=funding, provenance=provenance, write_manifest=False))
                except QuantError as exc:
                    excluded.append({'symbol': source.symbol, 'partition': kind, 'status': exc.status, 'reason': exc.reason})
        if not entries:
            raise QuantError('BLOCKED_DATA', f'No matched source passed ingestion: {excluded[:5]}')
        manifest = self._manifest(entries, excluded, bar_seconds)
        write_json(self.output / 'manifest.json', manifest)
        return manifest

    def build_cfd(self, *, source_root: str | Path, symbol: str, source_identity: str,
                  start: str | datetime, end: str | datetime, exchange_calendar: str,
                  source_bar_seconds: int = 60, bar_seconds: int = 3600,
                  spread_bps: float, spread_assumption: str,
                  volume_semantics: str = 'broker_tick_or_quote_proxy',
                  carry_assumption: str, swap_events: pl.DataFrame | None = None) -> dict[str, Any]:
        """Compile an explicit CFD cash-session research view using a real calendar.

        Calendar choice describes the requested research view, not the broker's
        complete dealing hours. CFD volume is never reclassified as exchange
        turnover. Asymmetric swaps need a directional execution adapter; this
        twelve-column symmetric view refuses to invent one from a single rate.
        """
        import importlib.metadata

        import exchange_calendars as xcals
        import pandas as pd
        safe_name(symbol)
        first, last = utc(start), utc(end)
        if first >= last or last > self.cutoff:
            raise QuantError('BLOCKED_DATA', 'CFD development ingestion must end before protected start')
        if not source_identity or not spread_assumption or not carry_assumption:
            raise QuantError('INVALID_SPEC', 'CFD source, spread and carry assumptions must be explicit')
        if volume_semantics not in ('broker_tick_or_quote_proxy', 'absent'):
            raise QuantError('INVALID_SPEC', 'CFD bars cannot claim exchange-traded volume')
        if (bar_seconds < source_bar_seconds or source_bar_seconds < 1
            or bar_seconds % source_bar_seconds or not math.isfinite(spread_bps) or spread_bps < 0):
            raise QuantError('INVALID_SPEC', 'Invalid CFD cadence or spread')
        if exchange_calendar not in xcals.get_calendar_names():
            raise QuantError('BLOCKED_DATA', 'Unknown exchange calendar for the CFD research view')
        calendar = xcals.get_calendar(exchange_calendar, start=first.date(), end=last.date())
        files = self._files(Path(source_root), first, last, protected=False)
        schema = pl.scan_parquet(files, hive_partitioning=False).collect_schema()
        volume = pl.col('volume') if 'volume' in schema and volume_semantics != 'absent' else pl.lit(0.).alias('volume')
        raw = (pl.scan_parquet(files, hive_partitioning=False)
               .filter((pl.col('timestamp') >= first) & (pl.col('timestamp') < last))
               .select(pl.col('timestamp').cast(pl.Datetime('us', 'UTC')),
                       'open', 'high', 'low', 'close', volume).collect(engine='streaming').sort('timestamp'))
        if raw.is_empty() or raw['timestamp'].n_unique() != raw.height:
            raise QuantError('BLOCKED_DATA', 'CFD source has no rows or duplicate timestamps')
        groups, schedule_evidence = [], []
        expected = bar_seconds // source_bar_seconds
        for session in calendar.sessions_in_range(first.date(), (last - timedelta(microseconds=1)).date()):
            opening = calendar.session_open(session).to_pydatetime()
            closing = calendar.session_close(session).to_pydatetime()
            segments = [(opening, closing)]
            break_start, break_end = calendar.session_break_start(session), calendar.session_break_end(session)
            if not pd.isna(break_start):
                segments = [(opening, break_start.to_pydatetime()), (break_end.to_pydatetime(), closing)]
            bar_offset = 0
            for left, right in segments:
                schedule_evidence.append({'session': str(session.date()), 'open': left, 'close': right})
                segment = raw.filter((pl.col('timestamp') >= left) & (pl.col('timestamp') < right))
                if segment.is_empty():
                    bar_offset += int((right - left).total_seconds()) // bar_seconds
                    continue
                segment = segment.with_columns(((pl.col('timestamp') - left).dt.total_seconds() // bar_seconds).alias('__bucket'))
                aggregated = segment.group_by('__bucket').agg(
                    pl.col('open').sort_by('timestamp').first(), pl.col('high').max(), pl.col('low').min(),
                    pl.col('close').sort_by('timestamp').last(), pl.col('volume').sum(),
                    pl.len().alias('__count'), pl.col('timestamp').min().alias('__first'), pl.col('timestamp').max().alias('__last'))
                aggregated = aggregated.with_columns((pl.lit(left) + pl.duration(seconds=pl.col('__bucket') * bar_seconds))
                                                      .cast(pl.Datetime('us', 'UTC')).alias('timestamp'))
                aggregated = aggregated.with_columns(pl.lit(symbol).alias('symbol'), pl.lit(0.).alias('carry_rate'),
                    pl.lit(spread_bps).alias('spread_bps'), pl.lit(str(session.date())).alias('session_id'),
                    (pl.col('__bucket') + bar_offset).cast(pl.Int32).alias('bar_in_session'),
                    ((pl.col('__count') == expected) & (pl.col('__first') == pl.col('timestamp'))
                     & (pl.col('__last') == pl.col('timestamp') + pl.duration(seconds=bar_seconds - source_bar_seconds))
                     & (pl.col('timestamp') + pl.duration(seconds=bar_seconds) <= right)).alias('is_tradable'))
                groups.append(aggregated.select(CANONICAL_COLUMNS))
                bar_offset += int((right - left).total_seconds()) // bar_seconds
        if not groups:
            raise QuantError('BLOCKED_DATA', 'No bars intersect the declared CFD research sessions')
        panel = pl.concat(groups).sort('symbol', 'timestamp')
        if swap_events is not None:
            required = {'timestamp', 'symbol', 'funding_rate', 'mark_price'}
            if not required <= set(swap_events.columns) or {'long_rate', 'short_rate'} & set(swap_events.columns):
                raise QuantError('BLOCKED_DATA', 'Asymmetric or point-denominated CFD swaps need an explicit directional adapter')
            events = swap_events.filter((pl.col('timestamp') >= first) & (pl.col('timestamp') < last))
            events = events.with_columns(pl.col('timestamp').cast(pl.Datetime('us', 'UTC')))
            if events.filter(pl.col('symbol') != symbol).height:
                raise QuantError('BLOCKED_DATA', 'Swap symbol differs from the certified CFD')
            if events.join(panel.select('timestamp', 'symbol'), on=['timestamp', 'symbol'], how='anti').height:
                raise QuantError('BLOCKED_DATA', 'Swap event needs a native event outside the selected cash-session view')
            panel = panel.drop('carry_rate').join(events.select('timestamp', 'symbol',
                            pl.col('funding_rate').alias('carry_rate')), on=['timestamp', 'symbol'], how='left')
            panel = panel.with_columns(pl.col('carry_rate').fill_null(0.)).select(CANONICAL_COLUMNS)
        else:
            events = None
        provenance = {'source_identity': source_identity, 'source_root': str(Path(source_root).resolve()),
                      'source_files': {str(p): file_hash(p) for p in files}, 'product': 'cfd',
                      'exchange_calendar': exchange_calendar, 'calendar_version': importlib.metadata.version('exchange_calendars'),
                      'schedule_sha256': digest(schedule_evidence), 'timezone': str(calendar.tz),
                      'event_time': 'bar open UTC', 'available_time': f'bar open + {bar_seconds}s',
                      'volume_semantics': volume_semantics, 'spread_assumption': spread_assumption,
                      'carry_assumption': carry_assumption, 'historical_recorded_time': 'unavailable',
                      'research_view': 'cash session only; not the complete CFD broker dealing calendar'}
        entries = self.publish(validate_panel(panel), funding=events, provenance=provenance,
                               write_manifest=False, bar_seconds=bar_seconds)
        manifest = self._manifest(entries, [], bar_seconds)
        write_json(self.output / 'manifest.json', manifest)
        return manifest

    def _build_symbol(self, source: Source, start: datetime, end: datetime, bar_seconds: int,
                      spread: float, spread_assumption: str, *, trusted_partitioning: bool = False):
        if source.funding is None:
            raise QuantError('BLOCKED_DATA', 'Missing funding source; cannot zero-fill')
        price_files = self._files(Path(source.prices), start, end, protected=trusted_partitioning)
        funding_files = self._files(Path(source.funding), start - timedelta(days=2), end, protected=trusted_partitioning)
        raw = (pl.scan_parquet(price_files, hive_partitioning=False)
               .filter((pl.col('timestamp') >= start) & (pl.col('timestamp') < end))
               .select('timestamp', 'open', 'high', 'low', 'close', 'volume')
               .collect(engine='streaming').sort('timestamp'))
        if raw.is_empty() or raw['timestamp'].n_unique() != raw.height:
            raise QuantError('BLOCKED_DATA', 'Empty or duplicate price rows')
        if bar_seconds < source.source_bar_seconds or bar_seconds % source.source_bar_seconds:
            raise QuantError('BLOCKED_DATA', 'Cannot upsample prices or use fractional source intervals')
        expected = bar_seconds // source.source_bar_seconds
        bars = raw.group_by_dynamic('timestamp', every=f'{bar_seconds}s', closed='left', label='left').agg(
            pl.col('open').first(), pl.col('high').max(), pl.col('low').min(),
            pl.col('close').last(), pl.col('volume').sum(), pl.len().alias('_count'))
        funding = (pl.scan_parquet(funding_files, hive_partitioning=False)
                   .filter((pl.col('timestamp') >= start - timedelta(days=2)) & (pl.col('timestamp') < end))
                   .select('timestamp', 'funding_rate', 'funding_interval_hours', 'mark_price')
                   .collect(engine='streaming').sort('timestamp'))
        if funding.is_empty() or funding['timestamp'].n_unique() != funding.height:
            raise QuantError('BLOCKED_DATA', 'Empty or duplicate funding events')
        if funding.select((pl.col('funding_rate').is_null() | ~pl.col('funding_rate').is_finite()
                           | (pl.col('funding_interval_hours') <= 0)).any()).item():
            raise QuantError('BLOCKED_DATA', 'Invalid funding rate/interval')
        funding = funding.with_columns(pl.col('timestamp').cast(pl.Datetime('us', 'UTC')).alias('source_event_at'))
        offset_us = pl.col('timestamp').dt.epoch('us') % (bar_seconds * 1000000)
        if funding.filter(offset_us > self.funding_time_tolerance_ms * 1000).height:
            raise QuantError('BLOCKED_DATA', 'Funding event is outside the declared opening-boundary tolerance')
        funding = funding.with_columns(pl.col('timestamp').dt.truncate(f'{bar_seconds}s').cast(pl.Datetime('us', 'UTC')))
        if funding['timestamp'].n_unique() != funding.height:
            raise QuantError('BLOCKED_DATA', 'Multiple settlements normalize to the same bar')
        # A later funding gap or delisting must NEVER remove earlier valid rows.
        # Validity is derived as-of from the last observed settlement and its
        # declared interval. A missed expected event invalidates subsequent bars
        # until a new settlement arrives; no whole-history survivor selection.
        events = funding.filter(pl.col('timestamp') >= start).with_columns(
            pl.lit(source.symbol).alias('symbol'), pl.col('timestamp').cast(pl.Datetime('us', 'UTC')))
        bars = bars.with_columns(pl.col('timestamp').cast(pl.Datetime('us', 'UTC')))
        events = events.join(bars.select('timestamp', pl.col('open').alias('__open_proxy')), on='timestamp', how='left')
        observed_mark = pl.col('mark_price').is_not_null() & pl.col('mark_price').is_finite() & (pl.col('mark_price') > 0)
        events = events.with_columns(pl.when(observed_mark).then(pl.lit('observed_settlement_mark'))
                                     .otherwise(pl.lit('trade_open_proxy' if self.funding_mark_policy == 'trade_open_proxy' else 'missing')).alias('mark_source'))
        if self.funding_mark_policy == 'trade_open_proxy':
            events = events.with_columns(pl.when(observed_mark).then(pl.col('mark_price')).otherwise(pl.col('__open_proxy')).alias('mark_price'))
        events = events.drop('__open_proxy')
        known_funding = funding.with_columns(pl.col('timestamp').cast(pl.Datetime('us', 'UTC'))).select(
            pl.col('timestamp').alias('__last_settlement'),
            (pl.col('timestamp') + pl.duration(hours=pl.col('funding_interval_hours'))).alias('__next_expected'))
        bars = bars.join_asof(known_funding, left_on='timestamp', right_on='__last_settlement', strategy='backward')
        frame = (bars.join(events.select('timestamp', pl.col('funding_rate').alias('carry_rate')),
                           on='timestamp', how='left')
                 .with_columns(pl.lit(source.symbol).alias('symbol'), pl.col('carry_rate').fill_null(0.0),
                               pl.lit(spread).alias('spread_bps'),
                               pl.col('timestamp').dt.strftime('%Y-%m-%d').alias('session_id'),
                               ((pl.col('timestamp').dt.hour() * 3600 + pl.col('timestamp').dt.minute() * 60)
                                // bar_seconds).cast(pl.Int32).alias('bar_in_session'),
                               ((pl.col('_count') == expected) & pl.col('__last_settlement').is_not_null()
                                & (pl.col('timestamp') < pl.col('__next_expected'))).fill_null(False).alias('is_tradable'))
                 .select(CANONICAL_COLUMNS))
        provenance = {'source': asdict(source), 'source_files': {str(p): file_hash(p) for p in price_files + funding_files},
                      'event_time': 'bar open UTC', 'available_time': f'bar open + {bar_seconds}s',
                      'funding_available_time': 'original source_event_at; features usable only after the containing bar closes',
                      'funding_time_policy': {'model': 'pre-open settlement at nearby bar boundary',
                                              'tolerance_ms': self.funding_time_tolerance_ms,
                                              'venue_boundary_eligibility': 'approximation, not a guarantee of exchange settlement ordering'},
                      'funding_mark_policy': self.funding_mark_policy,
                      'funding_coverage_policy': 'last observed interval is a causal staleness bound, not a guaranteed future settlement schedule or proof of archive completeness',
                      'funding_mark_proxy_events': events.filter(pl.col('mark_source') == 'trade_open_proxy').height,
                      'recorded_time': 'ingestion timestamp only; historical recording time unavailable',
                      'vintage_policy': 'immutable source-file snapshot; no reconstructed revision history',
                      'spread_assumption': spread_assumption, 'volume_semantics': 'base traded quantity',
                      'source_survival_coverage': 'historical directories included; completeness unverified',
                      'untradable_rows': frame.filter(~pl.col('is_tradable')).height,
                      'carry_zero_semantics': 'non-event zero only on is_tradable rows; unknown coverage rows are ineligible'}
        return validate_panel(frame), events, provenance

    def publish(self, panel: pl.DataFrame, *, funding: pl.DataFrame | None = None,
                provenance: dict[str, Any], write_manifest: bool = True,
                bar_seconds: int = 3600) -> list[dict[str, Any]]:
        """Trusted ingestion only: physically separate files on both sides of cutoff.

        This operation may receive protected data; unlike DataVault.load, it is
        not a research callback. Never call it in an untrusted feature worker.
        """
        panel = validate_panel(panel)
        self.output.mkdir(parents=True, exist_ok=True)
        entries = []
        for kind, condition in [('development', pl.col('timestamp') < self.cutoff),
                                ('protected', pl.col('timestamp') >= self.cutoff)]:
            part = panel.filter(condition)
            if part.is_empty():
                continue
            for group in part.partition_by('symbol', maintain_order=True):
                symbol = safe_name(group['symbol'][0])
                folder = self.output / kind / symbol
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / 'panel.parquet'
                if path.exists():
                    raise QuantError('BLOCKED_DATA', 'Immutable panel already exists; use a new snapshot output directory')
                group.write_parquet(path, statistics=True)
                item = {'path': str(path.relative_to(self.output)), 'kind': kind, 'table': 'prices',
                        'symbol': symbol, 'rows': group.height, 'sha256': file_hash(path),
                        'start': group['timestamp'].min().isoformat(), 'last': group['timestamp'].max().isoformat(),
                        'provenance': provenance}
                entries.append(item)
                if funding is not None:
                    side = funding.filter(condition & (pl.col('symbol') == symbol))
                    if side.height:
                        fp = folder / 'funding.parquet'
                        side.write_parquet(fp, statistics=True)
                        entries.append({'path': str(fp.relative_to(self.output)), 'kind': kind,
                                        'table': 'funding', 'symbol': symbol, 'rows': side.height,
                                        'sha256': file_hash(fp), 'start': side['timestamp'].min().isoformat(),
                                        'last': side['timestamp'].max().isoformat()})
        if write_manifest:
            write_json(self.output / 'manifest.json', self._manifest(entries, [], bar_seconds))
        return entries

    def _manifest(self, entries, excluded, bar_seconds):
        manifest = {'schema_version': 1, 'columns': CANONICAL_COLUMNS,
                    'protected_test_start': self.cutoff.isoformat(), 'bar_seconds': bar_seconds,
                    'ingested_at': datetime.now(UTC).isoformat(), 'entries': entries, 'excluded': excluded,
                    'bitemporal_scope': 'event/availability semantics plus immutable ingestion snapshot; historical vintages unavailable'}
        manifest['manifest_hash'] = digest(manifest)
        return manifest
