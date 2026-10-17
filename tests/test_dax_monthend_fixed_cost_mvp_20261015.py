"""Independent, read-only audit of the frozen DAX monthly native ML4T MVP."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl
import pytest
import statsmodels.api as sm

ROOT = Path(__file__).resolve().parents[1]
SID = "dax_monthend_fixed_cost_mvp_20261015_v1"
DATA = ROOT / "data/processed" / SID
RUN = ROOT / "run_log" / SID
BERLIN = ZoneInfo("Europe/Berlin")
INITIAL = 100_000.0


def read(path):
    return json.loads(path.read_text())


def typed_time(raw):
    value = datetime.fromisoformat(raw)
    assert value.tzinfo is not None
    return value.astimezone(UTC)


@pytest.fixture(scope="module")
def evidence():
    schedule = read(DATA / "schedule.json")
    audit = read(RUN / "source_preflight.json")
    terminal = read(RUN / "terminal_result.json")
    source = pl.read_parquet(DATA / "clock_bars.parquet")
    values = {t: float(p) for t, p in zip(source["timestamp"].to_list(), source["open"].to_list())}
    return schedule, audit, terminal, source, values


def test_predeclared_anchor_identity(evidence):
    schedule, audit, terminal, source, values = evidence
    assert len(schedule["events"]) == 83
    assert audit["status_counts"] == {"complete_pair": 73, "weekday_mismatch": 10}
    assert len([r for r in schedule["events"] if r["complete"]]) == 73
    assert terminal["num_complete_pairs"] == 73
    assert len({r["month"][:4] for r in schedule["events"] if r["complete"]}) == 7
    assert audit["read_protected_holdout"] is False
    assert source["timestamp"].max() < datetime(2025,1,1,tzinfo=UTC)
    assert source["timestamp"].n_unique() == source.height
    assert source["symbol"].unique().to_list() == ["DAX"]
    assert hashlib.sha256((DATA/"clock_bars.parquet").read_bytes()).hexdigest() == audit["staged_sha256"]
    assert terminal["source_sha256"] == audit["staged_sha256"]


def test_clock_alignment_and_no_same_bar_fills(evidence):
    schedule, audit, terminal, source, values = evidence
    for event in schedule["events"]:
        if not event["complete"]:
            continue
        control = event["legs"]["control"]
        candidate = event["legs"]["candidate"]
        assert date.fromisoformat(control["start"]).weekday() == date.fromisoformat(candidate["start"]).weekday()
        assert date.fromisoformat(control["end"]) < date.fromisoformat(candidate["start"])
        for arm in (candidate, control):
            ed, ef, xd, xf = (typed_time(arm[field]) for field in
                              ("entry_decision", "entry_fill", "exit_decision", "exit_fill"))
            assert ed + timedelta(minutes=1) == ef
            assert xd + timedelta(minutes=1) == xf
            assert (ed.astimezone(BERLIN).hour, ed.astimezone(BERLIN).minute) == (9, 10)
            assert (ef.astimezone(BERLIN).hour, ef.astimezone(BERLIN).minute) == (9, 11)
            assert (xd.astimezone(BERLIN).hour, xd.astimezone(BERLIN).minute) == (17, 10)
            assert (xf.astimezone(BERLIN).hour, xf.astimezone(BERLIN).minute) == (17, 11)
            assert ed in values and ef in values and xd in values and xf in values


@pytest.mark.parametrize("scenario,arm", [
    ("base","candidate"),("base","control"),("2x","candidate"),("2x","control")
])
def test_every_native_order_fee_finance_and_accounting(evidence,scenario,arm):
    schedule, audit, terminal, source, values = evidence
    dest = RUN / f"native_{scenario}_{arm}"
    report, orders, trades, cash = (read(dest/x) for x in
                ("result.json","orders.json","trades.json","financing_ledger.json"))
    assert report["engine"] == "ml4t.backtest.Engine(NEXT_BAR,OPEN)"
    assert len(trades) == 73 and len(orders) == 146 and len(cash) == 73
    bymonth = {}
    for o in orders:
        assert o["status"] == "filled"
        sent = typed_time(o["submitted_at"])
        filled = typed_time(o["filled_at"])
        assert sent + timedelta(minutes=1) == filled
        assert typed_time(o["expected_fill"]) == filled
        raw_open = values[filled]
        adverse = report["costs"]["slippage_rate"]
        wanted = raw_open * (1+adverse if o["action"]=="entry" else 1-adverse)
        assert math.isclose(float(o["filled_price"]), wanted, rel_tol=1e-11)
        if o["action"] == "entry":
            # Entry sizing is fixed from the known 09:10 signal bar, NOT later 09:11.
            quantity = INITIAL / values[sent]
            assert math.isclose(float(o["quantity"]), quantity, rel_tol=1e-11)
        bymonth.setdefault(o["month"], {})[o["action"]] = o
    finance = {r["month"]:r for r in cash}
    assert len(bymonth) == 73 and len(finance) == 73
    total = 0.0
    for t in trades:
        e,x = bymonth[t["month"]]["entry"],bymonth[t["month"]]["exit"]
        notional = e["quantity"] * e["filled_price"]
        days = (typed_time(x["filled_at"]) - typed_time(e["filled_at"])).total_seconds()/86400
        expected_finance = notional * report["costs"]["finance_rate_annual"] * days/365
        expected_commission = e["quantity"] * (e["filled_price"]+x["filled_price"]) * report["costs"]["commission_rate"]
        expected_net = e["quantity"]*(x["filled_price"]-e["filled_price"]) - expected_commission-expected_finance
        assert math.isclose(t["holding_calendar_days"],days,rel_tol=1e-10)
        assert math.isclose(t["finance_eur"], expected_finance, rel_tol=1e-10)
        assert math.isclose(t["finance_eur"], finance[t["month"]]["finance_debit"], rel_tol=1e-10)
        assert math.isclose(t["commission_eur"], expected_commission, rel_tol=1e-10)
        assert math.isclose(t["net_eur"], expected_net, rel_tol=1e-10,abs_tol=1e-8)
        total += expected_net
    assert abs(INITIAL+total-report["native_final_value_eur"]) < 0.01
    assert abs(total-report["native_net_pnl_eur"]) < 0.01
    assert abs(report["native_cash_pnl_reconciliation_eur"]) < 0.01
    daily = pl.read_parquet(dest/"daily_equity.parquet")
    assert len(daily) >= 1700
    assert abs(float(daily["equity"][-1])-report["native_final_value_eur"]) < 0.01
    # Independent maximum drawdown oracle from native daily-equity observations.
    eq = daily["equity"].to_numpy()
    dd = float((eq / np.maximum.accumulate(eq)-1).min())
    assert math.isclose(dd, report["risk_252d_daily_equity"]["max_drawdown"],rel_tol=1e-10,abs_tol=1e-10)


def test_pairing_and_hac_are_exact(evidence):
    schedule,audit,terminal,source,values=evidence
    for label in ("base","stress_2x"):
        sub = "base" if label=="base" else "2x"
        c = read(RUN/f"native_{sub}_candidate/trades.json")
        b = read(RUN/f"native_{sub}_control/trades.json")
        assert [x["month"] for x in c]==[x["month"] for x in b]
        array = np.array([x["net_return_initial_notional"]-y["net_return_initial_notional"]
                           for x,y in zip(c,b)],dtype=float)
        fit=sm.OLS(array,np.ones((len(array),1))).fit(cov_type="HAC",cov_kwds={"maxlags":3})
        expected=terminal[label]["hac3"]["paired_net"]
        assert math.isclose(float(fit.params[0]),expected["mean"],rel_tol=1e-12,abs_tol=1e-12)
        assert math.isclose(float(fit.bse[0]),expected["se_hac3"],rel_tol=1e-12,abs_tol=1e-12)


def test_double_cost_is_adverse_without_new_signal(evidence):
    schedule, audit, terminal, source, values=evidence
    for arm in ("candidate","control"):
        base=read(RUN/f"native_base_{arm}/trades.json")
        stress=read(RUN/f"native_2x_{arm}/trades.json")
        assert [r["month"] for r in base] == [r["month"] for r in stress]
        assert all(h["net_eur"] < b["net_eur"] for b,h in zip(base,stress))
    assert terminal["base"]["hac3"]["candidate_net"]["mean"] < 0
    assert terminal["mvp_decision"] == "REJECT"
