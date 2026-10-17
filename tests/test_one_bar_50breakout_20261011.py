from datetime import date, datetime, timezone

from scripts.run_one_bar_50breakout_20261011 import engine_gate, exchange_day, input_files


def test_native_next_bar_stop_and_open_exit_contract():
    gate = engine_gate()
    fills = gate["results"]["next_bar"]
    assert gate["exact_strategy_supported"] is True
    assert [(fill["type"], fill["price"]) for fill in fills] == [("stop", 101.0), ("market", 101.5)]
    assert fills[0]["timestamp"] == "2026-01-01T00:01:00+00:00"
    assert fills[1]["timestamp"] == "2026-01-01T00:02:00+00:00"


def test_input_partition_selection_excludes_protected_august():
    for symbol in ("NQ", "ES"):
        files = input_files(symbol)
        assert files
        assert all("year=2025" in path.as_posix() or int(path.parent.name.split("=")[1]) <= 7 for path in files)
        assert not any("year=2026/month=08" in path.as_posix() for path in files)


def test_globex_session_date_rolls_at_1700_chicago():
    before = datetime(2026, 7, 1, 21, 59, tzinfo=timezone.utc)  # 16:59 CDT
    after = datetime(2026, 7, 1, 22, 0, tzinfo=timezone.utc)  # 17:00 CDT
    assert exchange_day(before) == date(2026, 6, 30)
    assert exchange_day(after) == date(2026, 7, 1)
