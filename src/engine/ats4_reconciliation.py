"""Independent arithmetic reconciliation for the frozen ATS-4 M8 event run."""
from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

import polars as pl

BAR = timedelta(minutes=30)
INITIAL_CASH = 100_000.0
UNIT = 1.0
SLIPPAGE_BPS = 3.0
COMMISSION_BPS = 0.6


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError(f'timestamp must be timezone-aware: {value!r}')
    return value.astimezone(UTC)


def _close(a: float, b: float) -> bool:
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-7)


def _native_frame_time_matches(actual: datetime, source_utc: datetime) -> bool:
    """Compare the pinned engine's timezone-stripped marks without relabeling them."""
    if not isinstance(actual, datetime):
        return False
    if actual.utcoffset() is None:
        return actual == source_utc.replace(tzinfo=None)
    return actual.astimezone(UTC) == source_utc


def reconcile_m8_n8(result: Any, strategy: Any, raw_data: pl.DataFrame,
                    expected_executed_signal_times: list[datetime],
                    frozen_cost_multiple: int) -> dict[str, Any]:
    """Rebuild orders, fills, cash, position, and marks without production audit helpers.

    This check is qualified for the pinned ML4T 0.1.7 Order IDs (ORD-n).
    A signal timestamp labels the completed [t,t+30m) bar. Native created_at
    is a callback bar label; semantic decision availability is reported per leg.
    """
    if frozen_cost_multiple not in (1, 2, 3):
        raise ValueError('cost_multiple must be the frozen 1x, 2x, or 3x scenario')
    required = {'timestamp', 'open', 'close'}
    if not required <= set(raw_data.columns) or raw_data.is_empty():
        raise ValueError('source requires timestamp, open, close rows')
    source = raw_data.sort('timestamp').to_dicts()
    times = [_utc(row['timestamp']) for row in source]
    if len(set(times)) != len(times):
        raise ValueError('source timestamps must be unique')
    if 'symbol' not in raw_data.columns or raw_data['symbol'].n_unique() != 1:
        raise ValueError('source must contain exactly one symbol')
    symbol = str(raw_data['symbol'][0])
    for row in source:
        if any(not math.isfinite(float(row[field])) or float(row[field]) <= 0
               for field in ('open', 'close')):
            raise ValueError('source open and close prices must be finite and positive')
    bars = {stamp: row for stamp, row in zip(times, source, strict=True)}
    signals = [_utc(x) for x in expected_executed_signal_times]
    if signals != sorted(set(signals)):
        raise ValueError('expected signal times must be unique and increasing')
    for i, signal in enumerate(signals):
        if i and signal < signals[i - 1] + 2 * BAR:
            raise ValueError('expected signal lifecycle overlaps')
        if signal not in bars or signal + BAR not in bars or signal + 2 * BAR not in bars:
            raise ValueError(f'missing signal or planned fill bar: {signal.isoformat()}')

    slip = SLIPPAGE_BPS * frozen_cost_multiple / 10_000
    commission_rate = COMMISSION_BPS * frozen_cost_multiple / 10_000
    expected_orders = []
    expected_fills = []
    for index, signal in enumerate(signals):
        entry_at, exit_at = signal + BAR, signal + 2 * BAR
        for leg, side, fill_at, raw_price, direction in (
            ('entry', 'buy', entry_at, float(bars[entry_at]['open']), 1),
            ('exit', 'sell', exit_at, float(bars[exit_at]['open']), -1),
        ):
            price = raw_price * (1 + direction * slip)
            commission = abs(price * UNIT) * commission_rate
            expected_orders.append({'order_id': f'ORD-{2 * index + (1 if leg == "entry" else 2)}',
                                    'leg': leg, 'signal_at': signal, 'decision_available_at': fill_at,
                                    'created_at': signal if leg == 'entry' else entry_at,
                                    'filled_at': fill_at, 'side': side, 'quantity': UNIT,
                                    'filled_quantity': UNIT, 'filled_price': price,
                                    'asset': symbol, 'order_type': 'market'})
            expected_fills.append({'order_id': expected_orders[-1]['order_id'], 'timestamp': fill_at,
                                   'side': side, 'quantity': UNIT, 'price': price,
                                   'commission': commission})

    errors: dict[str, float] = {}
    error_locations: dict[str, dict[str, Any]] = {}
    def compare(key: str, actual: Any, expected: Any) -> None:
        if isinstance(expected, datetime):
            if _utc(actual) != expected:
                raise ValueError(f'{key} mismatch: {actual!r} != {expected!r}')
        elif isinstance(expected, str):
            if str(getattr(actual, 'value', actual)).lower() != expected.lower():
                raise ValueError(f'{key} mismatch: {actual!r} != {expected!r}')
        else:
            error = abs(float(actual) - float(expected))
            summary_key = key.split('@', 1)[0]
            if error >= errors.get(summary_key, -1.0):
                errors[summary_key] = error
                error_locations[summary_key] = {'location': key.rsplit('@', 1)[-1] if '@' in key else key,
                                        'actual': float(actual), 'expected': float(expected)}
            if not _close(actual, expected):
                raise ValueError(f'{key} mismatch: {actual!r} != {expected!r}')

    if list(getattr(strategy, 'executed_signals', [])) != signals:
        raise ValueError('executed signal sequence mismatch')
    native_orders = []
    strategy_pairs = getattr(strategy, 'orders', [])
    for pair, expected_signal in zip(strategy_pairs, signals):
        compare('strategy.signal_at', pair.get('signal_at'), expected_signal)
        native_orders.extend((pair.get('entry_order'), pair.get('exit_order')))
    if (len(strategy_pairs) != len(signals) or len(native_orders) != len(expected_orders)
            or any(order is None for order in native_orders)):
        raise ValueError('missing or extra native order submissions')
    if getattr(strategy, 'pending_entry', None) is not None or getattr(strategy, 'pending_exit', None) is not None:
        raise ValueError('strategy retains pending order metadata')
    ids = [getattr(order, 'order_id', None) for order in native_orders]
    if None in ids or len(set(ids)) != len(ids):
        raise ValueError('native order IDs must be present and unique')
    order_table = []
    for order, expected in zip(native_orders, expected_orders, strict=True):
        for field, value in (('order_id', expected['order_id']), ('status', 'filled'),
                             ('created_at', expected['created_at']), ('filled_at', expected['filled_at']),
                             ('side', expected['side']), ('asset', symbol),
                             ('order_type', 'market')):
            compare(f'order.{field}', getattr(order, field), value)
        for field in ('quantity', 'filled_quantity', 'filled_price'):
            compare(f'order.{field}', getattr(order, field), expected[field])
        order_table.append({**expected, 'created_at': expected['created_at'].isoformat(),
                            'decision_available_at': expected['decision_available_at'].isoformat(),
                            'filled_at': expected['filled_at'].isoformat()})
    if getattr(result, 'rejected_orders', None):
        raise ValueError('native result contains rejected orders')

    fills = result.to_fills_dataframe()
    fill_rows = fills.to_dicts()
    if len(fill_rows) != len(expected_fills):
        raise ValueError('missing or extra native fills')
    for actual, expected in zip(fill_rows, expected_fills, strict=True):
        for field in ('order_id', 'side', 'timestamp', 'asset'):
            expected_value = symbol if field == 'asset' else expected[field] if field != 'timestamp' else expected['timestamp']
            if field == 'timestamp' and isinstance(actual[field], datetime) and actual[field].utcoffset() is None:
                # The pinned 0.1.7 fill frame drops tz metadata; compare wall clocks without assigning a zone.
                if not _native_frame_time_matches(actual[field], expected_value):
                    raise ValueError(f'fill.timestamp mismatch: {actual[field]!r} != {expected_value!r}')
            else:
                compare(f'fill.{field}', actual[field], expected_value)
        for field in ('quantity', 'price', 'commission'):
            compare(f'fill.{field}', actual[field], expected[field])

    portfolio = result.to_portfolio_state_dataframe()
    equity = result.to_equity_dataframe()
    if 'timestamp' not in portfolio.columns or 'timestamp' not in equity.columns:
        raise ValueError('native marks lack timestamps')
    portfolio_rows, equity_rows = portfolio.to_dicts(), equity.to_dicts()
    if (len(portfolio_rows) != len(times) or len(equity_rows) != len(times)
            or any(not _native_frame_time_matches(row['timestamp'], stamp)
                   for frame in (portfolio_rows, equity_rows) for row, stamp in zip(frame, times))):
        raise ValueError('portfolio/equity timestamps must match every source row exactly')
    fill_at: dict[datetime, list[dict[str, Any]]] = {}
    for fill in expected_fills:
        fill_at.setdefault(fill['timestamp'], []).append(fill)
    cash, position = INITIAL_CASH, 0.0
    ledger = []
    for stamp, row, state in zip(times, equity_rows, portfolio_rows, strict=True):
        for fill in fill_at.get(stamp, []):
            signed = fill['quantity'] if fill['side'] == 'buy' else -fill['quantity']
            cash -= signed * fill['price'] * UNIT + fill['commission']
            position += signed
        marked_exposure = position * float(bars[stamp]['close']) * UNIT
        marked_equity = cash + marked_exposure
        compare(f'cash@{stamp.isoformat()}', state['cash'], cash)
        compare(f'equity@{stamp.isoformat()}', row['equity'], marked_equity)
        compare(f'portfolio.equity@{stamp.isoformat()}', state['equity'], marked_equity)
        for field, value in (('gross_exposure', abs(marked_exposure)), ('net_exposure', marked_exposure),
                             ('open_positions', int(position != 0))):
            compare(f'portfolio.{field}@{stamp.isoformat()}', state[field], value)
        ledger.append({'timestamp': stamp.isoformat(), 'cash': cash, 'position': position,
                       'equity': marked_equity, 'gross_exposure': abs(marked_exposure),
                       'net_exposure': marked_exposure, 'open_positions': int(position != 0)})
    if not _close(position, 0.0):
        raise ValueError('terminal position is not flat')
    return {'status': 'PASS', 'cost_multiple': frozen_cost_multiple,
            'assumptions': {'initial_cash': INITIAL_CASH, 'unit_quantity': UNIT,
                            'slippage_bps_per_fill': SLIPPAGE_BPS * frozen_cost_multiple,
                            'commission_bps_per_fill': COMMISSION_BPS * frozen_cost_multiple,
                            'signal_interval': '[t,t+30m)', 'entry': 't+30m open', 'exit': 't+60m open',
                            'exposure_basis': 'currency, marked as position times source close'},
            'counts': {'signals': len(signals), 'orders': len(native_orders), 'fills': len(fill_rows),
                       'source_marks': len(times), 'portfolio_marks': len(portfolio_rows),
                       'equity_marks': len(equity_rows)},
            'maximum_absolute_errors': errors, 'max_error_locations': error_locations,
            'native_dataframe_timestamp_note': 'ML4T 0.1.7 strips timezone metadata in dataframe timestamps; compared wall-clock values to timezone-aware source UTC without relabeling native values',
            'order_id_scope': 'ML4T backtest 0.1.7 pinned Engine IDs ORD-n',
            'orders': order_table, 'ledger': ledger}
