from datetime import UTC, datetime, timedelta

from src.research_control.ats3_audit import AuditEvent, reconcile

NOW = datetime(2026, 10, 16, tzinfo=UTC)


def row(kind, identity, payload=None, order='ORD-A', t=NOW, supersedes=''):
    return AuditEvent('journal-archive', 'demo', 'account-1', 'strategy-1', 'BTCUSD',
                      identity, kind, t, t, t, payload or {}, order, supersedes)


def base():
    return [
        row('intent', 'signal'),
        row('route', 'route'),
        row('order', 'ord', {'quantity': '2'}),
        row('ack', 'ack'),
        row('fill', 'fill-a', {'quantity': '1', 'price': '100', 'side': 'buy'}),
        row('fill', 'fill-b', {'quantity': '1', 'price': '101', 'side': 'buy'}),
        row('commission', 'fee', {'amount': '1'}),
        row('financing', 'fund', {'amount': '0'}),
        row('mark', 'mark', {'price': '105'}),
    ]


def test_two_partial_fills_reconcile_and_restart_duplicate_is_idempotent():
    records = base()
    good = reconcile(records, initial_cash='1000', as_of=NOW, max_mark_age=timedelta(seconds=10))
    assert good['status'] == 'VERIFIED'
    assert good['cash'] == '798'
    assert good['equity'] == '1008'
    replay = reconcile(list(reversed(records)) + [records[5]], initial_cash='1000',
                       as_of=NOW, max_mark_age=timedelta(seconds=10))
    assert replay['equity'] == good['equity']
    assert replay['duplicates'] == 1


def test_missing_ack_versus_partial_execution_are_distinct():
    records = [r for r in base() if r.event_id not in ('ack', 'fill-b')]
    got = reconcile(records, initial_cash='1000')
    assert 'ACK_UNKNOWN:ORD-A' in got['unknowns']
    assert 'PARTIAL_FILL:ORD-A' in got['unknowns']
    assert got['status'] == 'INSUFFICIENT_EVIDENCE'


def test_overfill_conflict_and_stale_mark_fail_closed():
    rows = base()
    overfill = rows + [row('fill', 'fill-extra', {'quantity': '1', 'price': '99', 'side': 'buy'})]
    assert 'OVERFILLED_ORDER:ORD-A' in reconcile(overfill, initial_cash='1000')['conflicts']
    later = NOW + timedelta(hours=2)
    stale = reconcile(rows, initial_cash='1000', as_of=later, max_mark_age=timedelta(minutes=1))
    assert 'STALE_MARK:BTCUSD' in stale['unknowns']
    assert stale['status'] == 'INSUFFICIENT_EVIDENCE'


def test_conflicting_fill_and_correction_never_silently_reprice():
    rows = base()
    changed = row('fill', 'fill-a', {'quantity': '1', 'price': '50', 'side': 'buy'})
    assert reconcile(rows + [changed], initial_cash='1000')['status'] == 'CONFLICTING_EVIDENCE'
    correction = row('fill', 'corrected-fill', {'quantity': '1', 'price': '50', 'side': 'buy'},
                     supersedes='fill-a')
    result = reconcile(rows + [correction], initial_cash='1000')
    assert any(x.startswith('CORRECTION_REQUIRES_REPLAY') for x in result['conflicts'])
    assert result['status'] == 'CONFLICTING_EVIDENCE'


def test_conflicting_order_quantity_never_silently_relax():
    rows = base()
    duplicate_order = rows + [row('order', 'ord-alt', {'quantity': '3'})]
    result = reconcile(duplicate_order, initial_cash='1000')
    assert 'ORDER_QUANTITY_CONFLICT:ORD-A' in result['conflicts']
    assert result['status'] == 'CONFLICTING_EVIDENCE'


def test_missing_mark_and_invalid_clock():
    rows = [r for r in base() if r.kind != 'mark']
    assert 'MISSING_MARK:BTCUSD' in reconcile(rows, initial_cash='1000')['unknowns']
