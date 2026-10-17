"""Independent data, calendar, and holdout oracle for Tokyo Program 1.

This verifier reads the task snapshots only. It does not simulate a strategy.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import numpy as np
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests
import yaml

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / 'run_log/tokyo_fix_alpha_map_program1_20261010'


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_calendar(directory: Path) -> dict:
    source = json.loads((directory / 'holidays.json').read_text())
    public = set(map(date.fromisoformat, source['public_holidays']))

    def business(d: date) -> bool:
        return d.weekday() < 5 and d not in public and (d.month, d.day) not in {(1, 1), (1, 2), (1, 3), (12, 31)}

    events = json.loads((directory / 'nominal_gotobi_events.json').read_text())
    for event in events:
        nominal = date.fromisoformat(event['nominal_date'])
        expected = nominal
        while not business(expected):
            expected -= timedelta(days=1)
        assert event['event_date'] == str(expected), event
        assert nominal.day in (5, 10, 15, 20, 25, 30)
        assert event['roll_days'] == (nominal - expected).days
    assert events[0]['event_date'] == '2019-12-30'
    with (directory / 'calendar_dates.csv').open() as file:
        days = list(csv.DictReader(file))
    expected_gotobi = {e['event_date'] for e in events}
    for row in days:
        d = date.fromisoformat(row['date'])
        assert (row['tokyo_bank_business_day'] == 'True') == business(d)
        assert (row['gotobi'] == 'True') == (str(d) in expected_gotobi)
    return {'days': len(days), 'business_days': sum(business(date.fromisoformat(d['date'])) for d in days), 'nominal_events': len(events), 'roll_oracle': 'PASS'}


def verify_snapshots(paths: list[Path]) -> dict:
    assert paths, 'No immutable snapshots found'
    records = []
    total = 0
    dates = set()
    complete_dates = set()
    for path in paths:
        frame = pl.read_parquet(path)
        assert frame.height < 1_000_000 and path.stat().st_size < 100_000_000
        assert isinstance(frame.schema['timestamp'], pl.Datetime)
        assert frame.schema['timestamp'].time_zone == 'UTC'
        assert frame['symbol'].unique().to_list() == ['USDJPY']
        assert frame['timestamp'].is_sorted()
        assert frame['timestamp'].n_unique() == frame.height
        frame = frame.with_columns(pl.col('timestamp').dt.convert_time_zone('Asia/Tokyo').alias('_jst')).with_columns(
            pl.col('_jst').dt.date().alias('_date'),
            (pl.col('_jst').dt.hour().cast(pl.Int32) * 60 + pl.col('_jst').dt.minute().cast(pl.Int32)).alias('_minute'))
        assert frame['_date'].min() >= date(2020, 1, 1)
        assert frame['_date'].max() <= date(2026, 8, 31)
        assert frame['_minute'].min() == 180 and frame['_minute'].max() == 720
        assert frame['_jst'].dt.second().sum() == 0
        assert frame['_jst'].dt.microsecond().sum() == 0
        prices = frame.select('open', 'high', 'low', 'close')
        assert prices.null_count().sum_horizontal().sum() == 0
        assert prices.select(pl.all().is_finite().all()).row(0) == (True, True, True, True)
        assert prices.select(pl.all().gt(0).all()).row(0) == (True, True, True, True)
        assert frame.filter((pl.col('low') > pl.min_horizontal('open', 'close')) | (pl.col('high') < pl.max_horizontal('open', 'close')) | (pl.col('low') > pl.col('high'))).is_empty()
        counts = frame.group_by('_date').agg(pl.len().alias('_n'), pl.col('_minute').n_unique().alias('_unique'))
        assert counts.filter((pl.col('_n') > 541) | (pl.col('_unique') != pl.col('_n'))).is_empty()
        complete_dates.update(counts.filter(pl.col('_n') == 541)['_date'].to_list())
        new = set(frame['_date'].to_list())
        assert not dates.intersection(new), 'Snapshot overlap'
        dates.update(new)
        total += frame.height
        records.append({'path': str(path.relative_to(ROOT)), 'rows': frame.height, 'sha256': sha256(path), 'days': counts.height})
    event = pl.read_parquet(AUDIT / 'execution_v1/event_panel.parquet')
    assert set(event['session'].to_list()) == complete_dates
    registry = pl.read_parquet(AUDIT / 'execution_v1/calendar_event_registry.parquet')
    assert set(registry.filter(pl.col('complete_full'))['session'].to_list()) == complete_dates
    return {'rows': total, 'available_days': len(dates), 'complete_days': len(complete_dates), 'holdout_in_snapshots': False, 'snapshots': records, 'exact541_no_forward_fill_oracle': 'PASS'}


def verify_events(paths: list[Path]) -> dict:
    """Reconstruct endpoint markouts and gates as an independent numerical oracle."""
    folder = AUDIT / 'execution_v1'
    ev = pl.read_parquet(folder / 'event_panel.parquet').sort('session')
    spec = yaml.safe_load((ROOT / 'config/research_sessions/tokyo_alpha_map_program1_v1.yaml').read_text())
    windows = spec['evaluation']['windows']
    data = pl.concat([pl.read_parquet(p) for p in paths]).with_columns(pl.col('timestamp').dt.convert_time_zone('Asia/Tokyo').alias('_jst')).with_columns(
        pl.col('_jst').dt.date().alias('_date'),
        (pl.col('_jst').dt.hour().cast(pl.Int32) * 60 + pl.col('_jst').dt.minute().cast(pl.Int32)).alias('_minute'))
    endpoints = sorted({m for a, b, _ in windows.values() for m in (a, b)} | {480, 595})
    grid = data.filter(pl.col('_minute').is_in(endpoints)).pivot(on='_minute', index='_date', values='open').sort('_date')
    grid = grid.filter(pl.col('_date').is_in(ev['session'].to_list()))
    assert grid['_date'].to_list() == ev['session'].to_list()
    for minute in endpoints:
        np.testing.assert_allclose(grid[str(minute)].to_numpy(), ev[f'p{minute}'].to_numpy(), rtol=0, atol=0)
    for name, (entry, exit_, sign) in windows.items():
        expected = sign * (grid[str(exit_)].to_numpy() - grid[str(entry)].to_numpy()) / 0.01
        np.testing.assert_allclose(expected, ev[name].to_numpy(), rtol=1e-12, atol=1e-10)
    extension = (grid['595'].to_numpy() - grid['480'].to_numpy()) / 0.01
    expected_sd = np.array([np.std(extension[i-20:i], ddof=1) if i >= 20 else np.nan for i in range(len(extension))])
    np.testing.assert_allclose(expected_sd, ev['prior20_sd'].to_numpy(), rtol=1e-10, atol=1e-8, equal_nan=True)
    np.testing.assert_array_equal(extension > 1.5 * expected_sd, ev['strict_gate'].to_numpy())
    history = pl.read_parquet(folder / 'original_gate_history.parquet').sort('session')
    ext = history['extension_pips'].to_numpy()
    expected_original = np.array([np.std(ext[i-20:i], ddof=1) if i >= 20 else np.nan for i in range(len(ext))])
    np.testing.assert_allclose(expected_original, history['original_prior20_sd'].to_numpy(), rtol=1e-10, atol=1e-8, equal_nan=True)
    np.testing.assert_array_equal(ext > 1.5 * expected_original, history['original_gate'].to_numpy())
    result = json.loads((folder / 'results.json').read_text())
    # Independent dummy construction checks ordinary/Gotobi regressions.
    design = np.column_stack([np.ones(ev.height), ev['gotobi'].cast(pl.Float64).to_numpy()] +
        [(ev[c].to_numpy() == value).astype(float) for c in ('weekday', 'year') for value in sorted(ev[c].unique().to_list())[1:]])
    for name in windows:
        fit = sm.OLS(ev[name].to_numpy(), design).fit(cov_type='HAC', cov_kwds={'maxlags': 5, 'kernel': 'bartlett', 'use_correction': True}, use_t=True)
        reported = result['windows'][name]['increment']
        np.testing.assert_allclose(fit.params[1], reported['estimate'], rtol=1e-10, atol=1e-10)
        np.testing.assert_allclose(fit.conf_int()[1], reported['ci95'], rtol=1e-10, atol=1e-10)
    ids = spec['evaluation']['global_holm_test_ids']
    assert set(result['tests']) == set(ids) and len(ids) == len(set(ids))
    corrected = multipletests([result['tests'][key]['p'] for key in ids], method='holm')[1]
    np.testing.assert_allclose(corrected, [result['tests'][key]['holm_p'] for key in ids], rtol=0, atol=0)
    curves = pl.read_parquet(folder / 'minute_curves.parquet')
    assert curves.height == 541 * 4
    fix = curves.filter(pl.col('minute_jst') == 595)
    assert fix['mean'].abs().sum() == fix['lower'].abs().sum() == fix['upper'].abs().sum() == 0
    return {'event_days': ev.height, 'markout_windows': len(windows), 'strict_and_original_gate_oracles': 'PASS', 'calendar_hac_regressions': 'PASS', 'global_holm_tests': len(ids), 'curves_anchored_at_fix': 'PASS', 'native_fill_oracle': 'NOT_APPLICABLE' if not result['candidates'] else 'REQUIRES_SEPARATE_FILL_AUDIT'}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshots', default='data/processed/tokyo_alpha_map_program1_v1')
    parser.add_argument('--output', default='run_log/tokyo_fix_alpha_map_program1_20261010/root_verification_v1/independent_verification.json')
    args = parser.parse_args()
    snapshots = sorted((ROOT / args.snapshots).glob('*.parquet'))
    result = {'calendar': verify_calendar(AUDIT / 'calendar_audit_v1'), 'data': verify_snapshots(snapshots), 'events': verify_events(snapshots)}
    protected = json.loads((AUDIT / 'root_verification_v1/protected_hashes.json').read_text())
    changed = [name for name, digest in protected.items() if sha256(ROOT / name) != digest]
    assert not changed, f'Protected work changed: {changed}'
    result['protected_files'] = {'count': len(protected), 'unchanged': True}
    result['status'] = 'PASS'
    (ROOT / args.output).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
