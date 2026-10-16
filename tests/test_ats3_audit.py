from datetime import UTC, datetime

from src.research_control.ats3_audit import AuditEvent, reconcile

T = datetime(2026, 10, 16, tzinfo=UTC)


def event(kind, name, payload=None, execution_id='o1'):
    return AuditEvent('archived', 'test', 'a1', 's1', 'BTC', name, kind, T, T, T, payload or {}, execution_id)


def test_deterministic_replay_and_unknowns():
    rows = [event('order', 'o'), event('ack', 'a'), event('fill', 'f', {'quantity': '2', 'price': '100', 'side': 'buy'}), event('commission', 'c', {'amount': '1'}), event('mark', 'm', {'price': '105'})]
    result = reconcile(rows, initial_cash='1000')
    assert result['equity'] == '1009'
    assert result['status'] == 'INSUFFICIENT_EVIDENCE'
    assert 'FINANCING_NOT_OBSERVED' in result['unknowns']
    assert reconcile(list(reversed(rows)) + [rows[2]], initial_cash='1000')['equity'] == '1009'
    assert reconcile(list(reversed(rows)) + [rows[2]], initial_cash='1000')['duplicates'] == 1


def test_conflict_and_missing_order():
    fill = event('fill', 'f', {'quantity': '1', 'price': '100', 'side': 'buy'})
    changed = event('fill', 'f', {'quantity': '2', 'price': '100', 'side': 'buy'})
    assert reconcile([fill, changed], initial_cash='1000')['status'] == 'CONFLICTING_EVIDENCE'
    assert 'MISSING_ORDER:o1' in reconcile([fill], initial_cash='1000')['unknowns']


def test_cash_and_position_mismatch():
    rows = [event('cash', 'deposit', {'amount': '50'}), event('position', 'position', {'quantity': '1'})]
    result = reconcile(rows, initial_cash='1000')
    assert result['cash'] == '1050'
    assert result['status'] == 'CONFLICTING_EVIDENCE'
