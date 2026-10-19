from __future__ import annotations

import calendar
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from src.engine.combined_portfolio import build_portfolio
from src.engine.common import QuantError, file_hash
from src.engine.holdout import guard_development_read
from src.engine.profit_concentration import (
    attribute_instrument_pnl,
    build_profit_concentration,
    validate_profit_concentration,
    write_profit_concentration,
)
from src.engine.sleeve_runner import EVIDENCE_ROOT, run_sleeve
from src.engine.ts_casefile import build_casefile
from src.engine.ts_spec import parse_ts_spec

SPEC_DIR = Path(__file__).parents[1] / 'config/sleeves/advanced_futures_30'


def daily_from_months(values: list[tuple[int, float]], *, year: int = 2024) -> pl.DataFrame:
    rows = []
    for month, monthly_return in values:
        days = calendar.monthrange(year, month)[1]
        for day in range(1, days + 1):
            rows.append({'date': date(year, month, day),
                         'return': monthly_return if day == 1 else 0.0})
    return pl.DataFrame(rows)


def add_equity(daily: pl.DataFrame, initial: float = 100_000.0) -> pl.DataFrame:
    equity = initial * (1.0 + daily['return']).cum_prod()
    return daily.with_columns(equity.alias('equity'))


def make_attribution_inputs():
    days = [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)]
    panel = pl.DataFrame([
        {'timestamp': datetime(2024, 1, 1, 16, tzinfo=UTC), 'symbol': 'A', 'close': 101.0},
        {'timestamp': datetime(2024, 1, 2, 16, tzinfo=UTC), 'symbol': 'A', 'close': 103.0},
        {'timestamp': datetime(2024, 1, 3, 16, tzinfo=UTC), 'symbol': 'A', 'close': 104.0},
        {'timestamp': datetime(2024, 1, 1, 16, tzinfo=UTC), 'symbol': 'B', 'close': 51.0},
        {'timestamp': datetime(2024, 1, 2, 16, tzinfo=UTC), 'symbol': 'B', 'close': 52.0},
        {'timestamp': datetime(2024, 1, 3, 16, tzinfo=UTC), 'symbol': 'B', 'close': 53.0},
    ])
    fills = pl.DataFrame([
        {'timestamp': datetime(2024, 1, 1, 9, tzinfo=UTC), 'asset': 'A', 'side': 'buy',
         'quantity': 10.0, 'price': 100.0, 'commission': 1.0, 'slippage': 0.10},
        {'timestamp': datetime(2024, 1, 1, 9, tzinfo=UTC), 'asset': 'B', 'side': 'buy',
         'quantity': 20.0, 'price': 50.0, 'commission': 2.0, 'slippage': 0.05},
        {'timestamp': datetime(2024, 1, 2, 9, tzinfo=UTC), 'asset': 'A', 'side': 'sell',
         'quantity': 4.0, 'price': 102.0, 'commission': 0.5, 'slippage': 0.10},
    ])
    funding = pl.DataFrame([
        {'timestamp': datetime(2024, 1, 2, 0, tzinfo=UTC), 'symbol': 'A', 'cashflow': -1.0},
    ])
    equities = [100_027.0, 100_061.5, 100_087.5]
    returns = [equities[0] / 100_000.0 - 1.0,
               equities[1] / equities[0] - 1.0,
               equities[2] / equities[1] - 1.0]
    daily = pl.DataFrame({'date': days, 'equity': equities, 'return': returns})
    return panel, fills, funding, daily


def test_extreme_two_month_concentration_and_richest_month_ablation():
    # Ten ordinary +0.5% months and two +11.389% months put 82% of gross
    # positive profit in two calendar months while the headline remains good.
    values = [(1, 0.11389), (2, 0.11389)] + [(month, 0.005) for month in range(3, 13)]
    daily = daily_from_months(values)
    record = build_profit_concentration(
        daily=daily, periods_per_year=252, scope='portfolio',
        source_hashes={'synthetic': 'a' * 64})

    concentration = record['concentration']['monthly_return']
    assert concentration['status'] == 'AVAILABLE'
    assert concentration['top_2']['months'] == ['2024-01', '2024-02']
    assert concentration['top_2']['share_of_gross_positive'] == pytest.approx(0.82, abs=0.01)
    assert record['headline']['compounded_return'] > 0.20
    assert record['headline']['sharpe'] is not None and record['headline']['sharpe'] > 0.5

    ablation = record['richest_month_exclusion']
    assert ablation['excluded_months'] == ['2024-01']
    assert ablation['after']['compounded_return'] < ablation['before']['compounded_return']
    assert ablation['delta']['compounded_return'] < 0.0
    assert ablation['interpretation'] == 'EXPLANATORY_ONLY_NOT_AN_EXECUTABLE_COUNTERFACTUAL'

    smooth = daily_from_months([(month, 0.02) for month in range(1, 13)])
    smooth_record = build_profit_concentration(
        daily=smooth, periods_per_year=252, scope='portfolio',
        source_hashes={'synthetic': 'b' * 64})
    assert smooth_record['concentration']['monthly_return']['top_2'][
        'share_of_gross_positive'] < 0.25
    assert (abs(smooth_record['richest_month_exclusion']['delta']['compounded_return'])
            < abs(ablation['delta']['compounded_return']))


def test_negative_zero_and_offsetting_profit_never_produce_a_bogus_net_share():
    negative = daily_from_months([(1, 0.10), (2, -0.20), (3, -0.05)])
    negative_record = build_profit_concentration(
        daily=add_equity(negative), periods_per_year=252, scope='sleeve',
        initial_cash=100_000.0, source_hashes={'synthetic': 'c' * 64})
    top = negative_record['concentration']['monthly_return']['top_1']
    assert top['share_of_gross_positive'] == pytest.approx(1.0)
    assert top['share_of_net'] is None
    assert top['net_share_status'] == 'NON_POSITIVE_NET_PROFIT'
    assert negative_record['concentration']['monthly_pnl']['top_1'][
        'share_of_net'] is None

    zero = daily_from_months([(1, 0.05), (2, -0.05)])
    zero_record = build_profit_concentration(
        daily=add_equity(zero), periods_per_year=252, scope='sleeve',
        initial_cash=100_000.0, source_hashes={'synthetic': 'd' * 64})
    zero_top = zero_record['concentration']['monthly_return']['top_1']
    assert zero_top['share_of_net'] is None
    assert zero_top['net_share_status'] == 'ZERO_NET_PROFIT'

    offsets = daily_from_months([(1, 0.10), (2, -0.04)])
    offset_record = build_profit_concentration(
        daily=add_equity(offsets), periods_per_year=252, scope='sleeve',
        initial_cash=100_000.0, source_hashes={'synthetic': 'e' * 64})
    offset_top = offset_record['concentration']['monthly_return']['top_1']
    assert offset_top['share_of_net'] is None
    assert offset_top['net_share_status'] == 'OFFSET_BY_LOSSES'

    all_loss = daily_from_months([(1, -0.01), (2, -0.02)])
    loss_record = build_profit_concentration(
        daily=all_loss, periods_per_year=252, scope='portfolio',
        source_hashes={'synthetic': 'f' * 64})
    assert loss_record['concentration']['monthly_return']['status'] == 'UNAVAILABLE'
    assert 'No positive monthly net return' in loss_record['concentration']['monthly_return']['reason']


def test_month_ties_are_deterministic_and_ablate_the_earliest_month():
    daily = daily_from_months([(1, 0.01), (2, 0.01), (3, 0.01)])
    first = build_profit_concentration(
        daily=daily, periods_per_year=252, scope='portfolio',
        source_hashes={'synthetic': '1' * 64})
    second = build_profit_concentration(
        daily=daily, periods_per_year=252, scope='portfolio',
        source_hashes={'synthetic': '1' * 64})
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    concentration = first['concentration']['monthly_return']
    assert concentration['top_1']['months'] == ['2024-01']
    assert concentration['top_2']['months'] == ['2024-01', '2024-02']
    assert first['richest_month_exclusion']['excluded_months'] == ['2024-01']


def test_instrument_pnl_uses_native_fills_funding_and_causal_marks_and_reconciles():
    panel, fills, funding, daily = make_attribution_inputs()
    attribution = attribute_instrument_pnl(
        panel=panel, fills=fills, funding=funding, daily=daily,
        initial_cash=100_000.0)
    assert attribution['status'] == 'AVAILABLE'
    assert attribution['reconciliation']['status'] == 'PASS'
    assert attribution['reconciliation']['max_daily_equity_error'] <= 1e-9
    symbols = {row['symbol']: row for row in attribution['symbols']}
    assert symbols['A']['net_pnl'] == pytest.approx(29.5)
    assert symbols['B']['net_pnl'] == pytest.approx(58.0)
    assert symbols['A']['commission'] == pytest.approx(1.5)
    assert symbols['A']['funding'] == pytest.approx(-1.0)
    assert symbols['A']['slippage_events'] == 2
    monthly = {row['symbol']: row for row in attribution['monthly'].iter_rows(named=True)}
    assert monthly['A']['net_pnl'] == pytest.approx(29.5)
    assert monthly['B']['net_pnl'] == pytest.approx(58.0)

    record = build_profit_concentration(
        daily=daily, periods_per_year=252, scope='sleeve', initial_cash=100_000.0,
        panel=panel, fills=fills, funding=funding,
        identity={'sleeve_id': 'synthetic'})
    assert record['instrument_attribution']['status'] == 'AVAILABLE'
    assert record['instrument_attribution']['reconciliation']['status'] == 'PASS'
    assert record['months'][0]['net_pnl'] == pytest.approx(87.5)
    assert record['concentration']['monthly_pnl']['top_1']['combined'] == pytest.approx(87.5)
    assert {'panel', 'fills', 'funding', 'daily', 'attribution_daily'} <= set(
        record['source_hashes'])


def test_missing_or_inconsistent_attribution_evidence_rejects():
    panel, fills, funding, daily = make_attribution_inputs()
    with pytest.raises(QuantError) as exc:
        attribute_instrument_pnl(panel=panel, fills=fills.drop('commission'), funding=funding,
                                 daily=daily, initial_cash=100_000.0)
    assert exc.value.status == 'INVALID_EVIDENCE'

    tampered = daily.with_columns(
        pl.when(pl.col('date') == date(2024, 1, 2)).then(pl.col('equity') + 10.0)
        .otherwise(pl.col('equity')).alias('equity'))
    with pytest.raises(QuantError) as exc:
        attribute_instrument_pnl(panel=panel, fills=fills, funding=funding,
                                 daily=tampered, initial_cash=100_000.0)
    assert exc.value.status == 'INVALID_ACCOUNTING'
    assert 'reconcile' in exc.value.reason

    missing_mark = panel.filter(~((pl.col('symbol') == 'A')
                                  & (pl.col('timestamp') == datetime(2024, 1, 2, 16, tzinfo=UTC))))
    with pytest.raises(QuantError) as exc:
        attribute_instrument_pnl(panel=missing_mark, fills=fills, funding=funding,
                                 daily=daily, initial_cash=100_000.0)
    assert exc.value.status == 'INVALID_ACCOUNTING'

    nonfinite = daily.with_columns(pl.when(pl.col('date') == date(2024, 1, 3))
                                   .then(float('nan')).otherwise(pl.col('return')).alias('return'))
    with pytest.raises(QuantError) as exc:
        attribute_instrument_pnl(panel=panel, fills=fills, funding=funding,
                                 daily=nonfinite, initial_cash=100_000.0)
    assert exc.value.status == 'INVALID_EVIDENCE'

    record = build_profit_concentration(
        daily=daily_from_months([(1, 0.01)]), periods_per_year=252, scope='portfolio',
        instrument_attribution={'status': 'UNAVAILABLE', 'reason': 'no native artifacts'},
        source_hashes={'synthetic': '2' * 64})
    assert record['availability']['instrument_attribution'] == 'UNAVAILABLE'
    assert record['instrument_attribution']['reason'] == 'no native artifacts'

    invalid = dict(record)
    invalid['gating'] = True
    with pytest.raises(QuantError) as exc:
        validate_profit_concentration(invalid)
    assert 'non-gating' in exc.value.reason


def test_qualified_portfolio_diagnostic_preserves_weights_and_is_non_gating(tmp_path: Path):
    from tests.test_combined_portfolio import make_casefile

    log = tmp_path / 'run_log'
    first = [0.001 * ((i % 5) - 1) for i in range(40)]
    second = [0.002 * ((i % 7) - 2) for i in range(40)]
    make_casefile(log, 'af30_s06_slow_trend_long_short', 6, returns=first)
    make_casefile(log, 'af30_s07_slow_trend_trend_strength', 7, returns=second)
    record = build_portfolio(log, 'indices')

    assert record['status'] == 'COMPOSED'
    assert record['weights'] == {'af30_s06_slow_trend_long_short': 0.5,
                                 'af30_s07_slow_trend_trend_strength': 0.5}
    assert record['class_dsr']['trials'] == 2
    assert record['class_dsr']['observations'] == 40
    diagnostic = record['profit_concentration']
    assert diagnostic['gating'] is False
    assert diagnostic['status'] == 'AVAILABLE'
    assert diagnostic['availability']['instrument_attribution'] == 'UNAVAILABLE'
    assert 'not split arbitrarily' in diagnostic['availability']['instrument_reason']
    artifact = log / diagnostic['artifact']
    assert artifact.is_file()
    assert file_hash(artifact) == diagnostic['artifact_sha256']
    assert {'daily', 'portfolio_returns', 'sleeve:af30_s06_slow_trend_long_short'} <= set(
        diagnostic['source_hashes'])


def test_casefile_diagnostic_does_not_change_gates_or_disposition(tmp_path: Path):
    from tests.test_ts_casefile import inputs

    base = build_casefile(**inputs())
    diagnostic = build_profit_concentration(
        daily=add_equity(daily_from_months([(1, 0.01), (2, 0.01)])),
        periods_per_year=252, scope='sleeve', initial_cash=100_000.0,
        source_hashes={'synthetic': '3' * 64})
    written = write_profit_concentration(diagnostic, tmp_path / 'diagnostic')
    with_diagnostic = build_casefile(**inputs(),
                                     profit_concentration=written['summary'])
    assert with_diagnostic['gates'] == base['gates']
    assert with_diagnostic['disposition'] == base['disposition']
    assert with_diagnostic['profit_concentration'] == written['summary']
    assert with_diagnostic['profit_concentration']['gating'] is False


def test_sleeve_runner_persists_non_gating_diagnostic(tmp_path: Path):
    from tests.test_sleeve_execution import synthetic_loaders

    path = SPEC_DIR / 'af30_s01_buy_hold_single.yaml'
    spec = parse_ts_spec(path)
    market_class = spec.market_classes[0]
    log = tmp_path / 'run_log'
    result = run_sleeve(path, market_class.name, run_log=log,
                        loaders=synthetic_loaders(spec, market_class, []))
    assert result['status']
    summary = result['profit_concentration']
    assert summary['gating'] is False
    assert summary['status'] in {'AVAILABLE', 'UNAVAILABLE', 'INCONCLUSIVE', 'BLOCKED'}
    folder = log / EVIDENCE_ROOT / market_class.name / spec.sleeve_id
    artifact = log / summary['artifact']
    assert artifact == folder / 'profit_concentration.json'
    assert file_hash(artifact) == summary['artifact_sha256']
    casefile = json.loads((folder / 'casefile.json').read_text(encoding='utf-8'))
    assert casefile['profit_concentration'] == summary
    persisted = json.loads(artifact.read_text(encoding='utf-8'))
    assert persisted['status'] == summary['status']
    assert persisted['gating'] is False


def test_protected_guard_still_refuses_a_crossing_read():
    protected = datetime(2026, 1, 1, tzinfo=UTC)
    guard_development_read(protected - timedelta(days=1), protected)
    with pytest.raises(QuantError) as exc:
        guard_development_read(protected + timedelta(days=1), protected)
    assert exc.value.status == 'INVALID_SPEC'

    # A sleeve runner records no diagnostic when the declared development
    # window would cross the protected start; parsing rejects that window first.
    path = SPEC_DIR / 'af30_s01_buy_hold_single.yaml'
    spec = parse_ts_spec(path)
    with pytest.raises(QuantError):
        guard_development_read(spec.windows.validation.end + timedelta(days=1),
                               spec.windows.protected.start)
