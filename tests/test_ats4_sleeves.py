import json
from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from src.engine.ats4_sleeves import NativeScenario, demonstration
from src.portfolio_evidence import SleeveIdentity, TrialDisclosure

SESSION_DATES = tuple(date(2020, 1, day) for day in (2, 3, 6, 7, 8))


class NativeResult:
    def __init__(self, equity, portfolio, fills):
        self._equity = pl.DataFrame(equity)
        self._portfolio = pl.DataFrame(portfolio)
        self._fills = pl.DataFrame(
            fills,
            schema={"timestamp": pl.Datetime("us", "UTC"), "side": pl.String,
                    "quantity": pl.Float64, "price": pl.Float64, "commission": pl.Float64},
        )
        self.metrics = {"num_trades": 1, "initial_cash": 100_000.0, "final_value": equity[-1]["equity"]}

    def to_equity_dataframe(self):
        return self._equity

    def to_portfolio_state_dataframe(self):
        return self._portfolio

    def to_fills_dataframe(self):
        return self._fills


def identity(strategy, *, cost, spec):
    return SleeveIdentity(strategy, "v7", spec, f"code-{strategy}", "m8-source-v1", cost, "XNAS-2020-2024", "m8-selection-v1")


def fixture(monkeypatch):
    import src.engine.ats4_sleeves as bridge

    sessions = tuple(
        (day, datetime.combine(day, datetime.min.time(), UTC) + timedelta(hours=14, minutes=30),
         datetime.combine(day, datetime.min.time(), UTC) + timedelta(hours=21))
        for day in SESSION_DATES
    )
    monkeypatch.setattr(bridge, "_frozen_xnas_sessions", lambda: sessions)
    rows = [{"timestamp": datetime(2019, 12, 31, 20, 30, tzinfo=UTC), "symbol": "NQ", "open": 99.0, "close": 99.0}]
    for day, opens, _ in sessions:
        rows.extend([
            {"timestamp": opens, "symbol": "NQ", "open": 100.0, "close": 100.0},
            {"timestamp": opens + timedelta(minutes=30), "symbol": "NQ", "open": 100.0, "close": 100.5},
            {"timestamp": opens + timedelta(minutes=60), "symbol": "NQ", "open": 99.0, "close": 99.5},
            {"timestamp": opens + timedelta(hours=6), "symbol": "NQ", "open": 99.5, "close": 99.5},
        ])
    data = pl.DataFrame(rows)
    scenarios = []
    for multiple in (1, 2, 3):
        fills = []
        for stamp, side, raw in (
            (sessions[0][1] + timedelta(minutes=30), "buy", 100.0),
            (sessions[0][1] + timedelta(minutes=60), "sell", 99.0),
        ):
            sign = 1 if side == "buy" else -1
            price = raw * (1 + sign * .0003 * multiple)
            fills.append({"timestamp": stamp, "side": side, "quantity": 1.0,
                          "price": price, "commission": price * .00006 * multiple})
        fills_by_stamp = {item["timestamp"]: item for item in fills}
        cash, position = 100_000.0, 0.0
        equity, portfolio, ledger = [], [], []
        for row in rows:
            stamp = row["timestamp"]
            fill = fills_by_stamp.get(stamp)
            if fill:
                if fill["side"] == "buy":
                    cash -= fill["price"] + fill["commission"]
                    position = 1.0
                else:
                    cash += fill["price"] - fill["commission"]
                    position = 0.0
            marked = cash + position * row["close"]
            equity.append({"timestamp": stamp, "equity": marked})
            portfolio.append({"timestamp": stamp, "cash": cash, "open_positions": int(position != 0),
                              "net_exposure": position * row["close"], "gross_exposure": abs(position * row["close"])})
            ledger.append({"timestamp": stamp, "cash": cash, "position": position, "equity": marked})
        scenarios.append(NativeScenario(f"{multiple}x", NativeResult(equity, portfolio, fills),
                                         {"status": "PASS", "cost_multiple": multiple, "ledger": ledger}))
    return data, scenarios, sessions


def call(data, scenarios):
    return demonstration(
        data, scenarios,
        identity=identity("m8_n8_cash_session_v7", cost="assumed-bps", spec="m8-spec-hash"),
        cash_identity=identity("cash_zero_yield_no_fee", cost="zero-fee-assumption", spec="cash-spec-hash"),
        authorities={"source_sha256": "a" * 64, "cost_authority_sha256": "b" * 64,
                    "calendar_authority_sha256": "c" * 64},
        trial_disclosure=TrialDisclosure(("m8-known-attempt",), ("FALSIFIED",), None),
        periods_per_year=252,
        include_sleeves=True,
    )


def test_native_ledgers_bridge_by_prior_net_equity_and_return_json_safe(monkeypatch):
    data, scenarios, _ = fixture(monkeypatch)
    result = call(data, scenarios)
    report = result["report"]
    json.dumps(report, allow_nan=False)
    assert report["sample"]["session_count"] == 5
    assert report["sample"]["annualization_unit"].startswith("XNAS cash sessions")
    assert report["selection_adjustment"] == "UNAVAILABLE_NOT_COMPUTED"
    assert report["assumptions_and_limits"]["carry"].startswith("zero because")
    assert report["assumptions_and_limits"]["market_cost_authority"].startswith("UNAVAILABLE")
    assert len(report["native_scenarios"]) == 3
    first = report["native_scenarios"][0]
    assert [row["m8_capital_weight"] for row in first["allocation_comparisons"]] == [0, .25, .5, 1]
    assert [row["cash_capital_weight"] for row in first["allocation_comparisons"]] == [1, .75, .5, 0]
    assert first["allocation_comparisons"][-1]["comparison"]["candidate_daily_audit"]["audit_max_drawdown_initial_wealth"] < 0
    assert result["sleeves"][1].risk_fraction is None
    assert result["sleeves"][1].period_capital_denominator[0] == 100_000.0
    assert result["sleeves"][1].period_capital_denominator[1] == pytest.approx(result["sleeves"][1].net[0] * 100_000 + 100_000)
    assert all(not sleeve.carry_qualified and not sleeve.costs_qualified for sleeve in result["sleeves"])
    assert report["resampling"]["seed"] == 42
    assert report["resampling"]["block_size"] == 5
    assert report["resampling"]["samples"] == 100
    assert report["assumptions_and_limits"]["diversification_claim"].startswith("M8-versus-cash")


def test_missing_source_close_native_mark_or_reconciliation_day_blocks(monkeypatch):
    data, scenarios, sessions = fixture(monkeypatch)
    final_bar = sessions[-1][2] - timedelta(minutes=30)
    with pytest.raises(ValueError, match="cover every source row"):
        call(data.filter(pl.col("timestamp") != final_bar), scenarios)
    result = scenarios[0].result
    result._equity = result._equity.filter(pl.col("timestamp") != final_bar)
    with pytest.raises(ValueError, match="cover every source row"):
        call(data, scenarios)


def test_unknown_risk_is_not_invented_and_nonflat_session_close_blocks(monkeypatch):
    data, scenarios, sessions = fixture(monkeypatch)
    report = call(data, scenarios)["report"]
    assert report["native_scenarios"][0]["identity"]["cost_model_id"].endswith(":1x")
    assert call(data, scenarios)["sleeves"][1].risk_fraction is None
    final = sessions[0][2] - timedelta(minutes=30)
    state = scenarios[0].result._portfolio
    state_row = state.filter(pl.col("timestamp") == final).row(0, named=True)
    scenarios[0].result._portfolio = state.with_columns(
        pl.when(pl.col("timestamp") == final).then(1).otherwise(pl.col("open_positions")).alias("open_positions"),
        pl.when(pl.col("timestamp") == final).then(99.5).otherwise(pl.col("net_exposure")).alias("net_exposure"),
        pl.when(pl.col("timestamp") == final).then(99.5).otherwise(pl.col("gross_exposure")).alias("gross_exposure"),
        pl.when(pl.col("timestamp") == final).then(state_row["cash"] - 99.5).otherwise(pl.col("cash")).alias("cash"),
    )
    ledger = list(scenarios[0].reconciliation_report["ledger"])
    ledger_row = next(row for row in ledger if row["timestamp"] == final)
    ledger_row.update(position=1.0, cash=ledger_row["cash"] - 99.5)
    scenarios[0] = NativeScenario("1x", scenarios[0].result, {
        **scenarios[0].reconciliation_report, "ledger": ledger,
    })
    with pytest.raises(ValueError, match="terminally flat"):
        call(data, scenarios)


def test_incomplete_or_failed_reconciliation_is_rejected(monkeypatch):
    data, scenarios, _ = fixture(monkeypatch)
    scenarios[1] = NativeScenario("2x", scenarios[1].result, {"status": "FAILED", "ledger": []})
    with pytest.raises(ValueError, match="did not PASS"):
        call(data, scenarios)


def test_serialized_oracle_ledger_preserves_literal_net_and_cash_statistics(monkeypatch):
    data, scenarios, _ = fixture(monkeypatch)
    serialized = [NativeScenario(
        scenario.scenario, scenario.result,
        {**scenario.reconciliation_report, 'ledger': [
            {**row, 'timestamp': row['timestamp'].isoformat()}
            for row in scenario.reconciliation_report['ledger']
        ]},
    ) for scenario in scenarios]
    result = call(data, serialized)
    sleeve = result['sleeves'][1]
    assert sleeve.gross[0] == pytest.approx(-1.0 / 100_000)
    assert sleeve.execution_drag[0] == pytest.approx(0.071640018 / 100_000)
    assert sleeve.net[0] == pytest.approx(-1.071640018 / 100_000)
    assert sleeve.period_capital_denominator[1] == pytest.approx(99_998.928359982)
    cash = result['report']['native_scenarios'][0]['allocation_comparisons'][0]['comparison']
    assert cash['undefined_native_statistics']
    assert all(cash['native_statistics'][name] is None for name in cash['undefined_native_statistics'])
    json.dumps(result['report'], allow_nan=False)


def test_missing_scheduled_date_is_not_filled_with_zero_return(monkeypatch):
    data, scenarios, _ = fixture(monkeypatch)
    missing_day = SESSION_DATES[-1]
    data = data.filter(pl.col('timestamp').dt.date() != missing_day)
    for scenario in scenarios:
        scenario.result._equity = scenario.result._equity.filter(pl.col('timestamp').dt.date() != missing_day)
        scenario.result._portfolio = scenario.result._portfolio.filter(pl.col('timestamp').dt.date() != missing_day)
        scenario.reconciliation_report['ledger'] = [
            row for row in scenario.reconciliation_report['ledger'] if row['timestamp'].date() != missing_day
        ]
    with pytest.raises(ValueError, match='missing native equity mark on scheduled open date'):
        call(data, scenarios)


def test_frozen_daily_valuation_uses_actual_later_mark_not_exchange_close(monkeypatch):
    data, scenarios, sessions = fixture(monkeypatch)
    old_mark = sessions[-1][2] - timedelta(minutes=30)
    later_mark = sessions[-1][2] + timedelta(minutes=30)

    def later(frame):
        return frame.with_columns(pl.when(pl.col('timestamp') == old_mark)
                                  .then(pl.lit(later_mark)).otherwise(pl.col('timestamp')).alias('timestamp'))

    data = later(data)
    for scenario in scenarios:
        scenario.result._equity = later(scenario.result._equity)
        scenario.result._portfolio = later(scenario.result._portfolio)
        for row in scenario.reconciliation_report['ledger']:
            if row['timestamp'] == old_mark:
                row['timestamp'] = later_mark
    report = call(data, scenarios)['report']
    assert report['sample']['native_daily_mark_timestamps'][-1] == later_mark.isoformat()
    assert report['sample']['interpolated_marks'] is False


def test_source_timezone_cannot_be_inferred_from_naive_clock(monkeypatch):
    data, scenarios, _ = fixture(monkeypatch)
    with pytest.raises(ValueError, match='timezone-aware'):
        call(data.with_columns(pl.col('timestamp').dt.replace_time_zone(None)), scenarios)
