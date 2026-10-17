"""One predeclared DAX CFD BID-proxy calendar MVP; native ML4T execution only.

Run prepare -> research_session init/check -> phase3/record -> native/record.
No protected 2025+ data, no indicator optimization, no custom execution loop.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import numpy as np
import polars as pl
import statsmodels.api as sm

from ml4t.backtest import BacktestConfig, DataFeed, Engine, ExecutionMode, Strategy, OrderType
from ml4t.backtest.config import CommissionType, ExecutionPrice, ShareType, SlippageType
from ml4t.diagnostic.api import PortfolioAnalysis

ROOT = Path(__file__).resolve().parents[1]
SID = "dax_monthend_fixed_cost_mvp_20261015_v1"
SOURCE = Path("/home/quant/dev/quant/ml4t-data/.data/store/index_minute_DAX")
DATA = ROOT / "data/processed" / SID
RUN = ROOT / "run_log" / SID
DIAG = ROOT / "run_log/diagnostics" / SID
STAGED = DATA / "clock_bars.parquet"
SCHEDULE = DATA / "schedule.json"
PREFLIGHT = RUN / "source_preflight.json"
REPORT = ROOT / "docs/audit" / (SID + "_results.md")
COST_BASE = {"commission_rate": .0001, "slippage_rate": .0004, "finance_rate_annual": .08}
COST_STRESS = {"commission_rate": .0002, "slippage_rate": .0008, "finance_rate_annual": .16}
INITIAL = 100_000.0
BERLIN = ZoneInfo("Europe/Berlin")
HOLDOUT = datetime(2025, 1, 1, tzinfo=UTC)
HAC_LAG = 3


def sha(path: Path) -> str:
    with path.open("rb") as fp:
        return hashlib.file_digest(fp, "sha256").hexdigest()


def save(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"Refuse to overwrite immutable artifact: {path}")
    path.write_text(json.dumps(obj, indent=2, allow_nan=False, default=str) + "\n", encoding="utf8")


def utc(ts: datetime) -> datetime:
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)


def clock(day: date, hh: int, mm: int) -> datetime:
    ts = datetime.combine(day, time(hh, mm), BERLIN).astimezone(UTC)
    assert ts < HOLDOUT
    return ts


def session_calendar():
    cal = xcals.get_calendar("XETR")
    sessions = [ts.date() for ts in cal.sessions_in_range("2017-12-01", "2024-12-20")]
    return cal, sessions


def anchors(cal, sessions):
    idx = {d: i for i, d in enumerate(sessions)}
    out = []
    for yr in range(2018, 2025):
        for mon in range(1, 13):
            if (yr, mon) > (2024, 11):
                continue
            t = max(d for d in sessions if (d.year, d.month) == (yr, mon))
            it = idx[t]
            ci, ce, bi, be = it, it + 3, it - 10, it - 7
            assert bi >= 0 and be < ci and ce < len(sessions)
            matching = sessions[bi].weekday() == sessions[ci].weekday()
            pairs = {
                "control": {"start": sessions[bi], "end": sessions[be], "sessions": sessions[bi:be + 1]},
                "candidate": {"start": sessions[ci], "end": sessions[ce], "sessions": sessions[ci:ce + 1]},
            }
            valid_clocks = True
            for leg in pairs.values():
                for d in (leg["start"], leg["end"]):
                    exch_close = cal.session_close(str(d)).to_pydatetime().astimezone(BERLIN)
                    if exch_close.time() < time(17, 11):
                        valid_clocks = False
            out.append({"month": f"{yr:04d}-{mon:02d}", "anchor": t,
                        "matched_weekday": matching, "xetra_clock_eligible": valid_clocks,
                        "legs": pairs})
    assert len(out) == 83
    return out


def required_event_times(leg):
    start, end = leg["start"], leg["end"]
    return {"entry_decision": clock(start, 9, 10),
            "entry_fill": clock(start, 9, 11),
            "exit_decision": clock(end, 17, 10),
            "exit_fill": clock(end, 17, 11)}


def prepare() -> None:
    """Read only pre-2025 minute bars; stage a price-free event selection plan."""
    if STAGED.exists() or SCHEDULE.exists() or PREFLIGHT.exists():
        raise FileExistsError("Prepared immutable artifacts already exist; do not overwrite")
    cal, sessions = session_calendar()
    events = anchors(cal, sessions)
    desired = defaultdict(set)
    for evt in events:
        if not evt["matched_weekday"] or not evt["xetra_clock_eligible"]:
            continue
        for leg in evt["legs"].values():
            for moment in required_event_times(leg).values():
                desired[moment.date()].add(moment)
            for day in leg["sessions"]:
                desired[day].add(clock(day, 17, 30))
    rows, missing_partitions = [], []
    for day, moments in sorted(desired.items()):
        assert day < date(2025, 1, 1), "Protected holdout partition"
        path = SOURCE / f"year={day.year}/month={day.month}/day={day.day}/data.parquet"
        if not path.is_file():
            missing_partitions.append(str(day))
            continue
        frame = pl.read_parquet(path, columns=["timestamp", "symbol", "open", "high", "low", "close", "volume"])
        if frame["timestamp"].dtype.time_zone != "UTC":
            raise AssertionError(f"UTC vendor timestamp missing: {path}")
        if frame["symbol"].unique().to_list() != ["DAX"]:
            raise AssertionError(f"Vendor/source symbol changed: {path}")
        select = frame.filter(pl.col("timestamp").is_in(sorted(moments)))
        if select.filter(
            (pl.col("open") <= 0) | (~pl.col("open").is_finite())
            | (pl.col("high") < pl.max_horizontal("open", "close"))
            | (pl.col("low") > pl.min_horizontal("open", "close"))
            | (pl.col("low") <= 0)
        ).height:
            raise AssertionError(f"Bad OHLC source bars at {day}")
        rows.append(select)
    if not rows:
        raise AssertionError("No source rows")
    prices = pl.concat(rows).sort("timestamp")
    if prices["timestamp"].n_unique() != prices.height:
        raise AssertionError("Duplicate required timestamps")
    assert prices["timestamp"].max() < HOLDOUT
    observed = set(prices["timestamp"].to_list())
    statuses, counts = [], Counter()
    for event in events:
        result = {"month": event["month"], "anchor": str(event["anchor"]),
                  "matched_weekday": event["matched_weekday"],
                  "xetra_clock_eligible": event["xetra_clock_eligible"]}
        if not event["matched_weekday"]:
            counts["weekday_mismatch"] += 1
            result["reason"] = "weekday_mismatch"
            result["complete"] = False
        elif not event["xetra_clock_eligible"]:
            counts["early_close"] += 1
            result["reason"] = "early_close"
            result["complete"] = False
        else:
            missing, legs = [], {}
            for side, leg in event["legs"].items():
                clocks = required_event_times(leg)
                for label, stamp in clocks.items():
                    if stamp not in observed:
                        missing.append(f"{side}.{label}:{stamp.isoformat()}")
                for day in leg["sessions"]:
                    stamp = clock(day, 17, 30)
                    if stamp not in observed:
                        missing.append(f"{side}.daily_mark:{stamp.isoformat()}")
                legs[side] = {"start": str(leg["start"]), "end": str(leg["end"]),
                              "sessions": [str(d) for d in leg["sessions"]],
                              **{k: v.isoformat() for k, v in clocks.items()}}
            result["legs"] = legs
            result["missing"] = missing
            result["complete"] = not missing
            if missing:
                counts["data_invalid_pairs"] += 1
                counts["missing_required_points"] += len(missing)
            else:
                counts["complete_pair"] += 1
        statuses.append(result)
    DATA.mkdir(parents=True, exist_ok=True)
    prices.write_parquet(STAGED)
    save(SCHEDULE, {"candidate_id": SID, "frozen_rules": "XETR T,T+3 vs T-10,T-7; 09:11 and 17:11 fills",
                    "source": "Dukascopy DEUIDXEUR BID index_minute_DAX; NOT EXECUTABLE ASK",
                    "costs": {"base": COST_BASE, "stress_2x": COST_STRESS},
                    "events": statuses})
    save(PREFLIGHT, {
        "status": "PRICE_PROXY_PREPARED_NO_RETURN_ANALYSIS",
        "total_monthly_anchors": len(events), "status_counts": dict(counts),
        "eligible_paired_months": [e["month"] for e in statuses if e.get("complete")],
        "missing_partitions": missing_partitions,
        "source_selected_days": len(desired), "selected_source_rows": prices.height,
        "earliest_bar": str(prices["timestamp"].min()), "latest_bar": str(prices["timestamp"].max()),
        "staged_sha256": sha(STAGED), "schedule_sha256": sha(SCHEDULE),
        "read_protected_holdout": False, "measured_returns": False,
        "bid_only": True, "bar_start_and_broker_contract_unverified": True,
        "future_exit_quote_not_used_for_trade_decisions": True,
        "post_event_invalid_pairs_are_recorded_not_silently_dropped": True})
    print(json.dumps({"stage": "PREPARED_NO_RETURNS", "counts": dict(counts),
                      "rows": prices.height, "missing_partitions": len(missing_partitions),
                      "files": [str(STAGED), str(SCHEDULE), str(PREFLIGHT)]}, indent=2))


def load():
    a = json.loads(SCHEDULE.read_text())
    p = pl.read_parquet(STAGED).sort("timestamp")
    assert sha(STAGED) == json.loads(PREFLIGHT.read_text())["staged_sha256"]
    assert p["timestamp"].max() < HOLDOUT
    good = sorted([e for e in a["events"] if e.get("complete")], key=lambda e: e["month"])
    return p, good, a


def hac(values: list[float]) -> dict:
    array = np.asarray(values, dtype=np.float64)
    assert len(array) >= 4 and np.isfinite(array).all()
    model = sm.OLS(array, np.ones((len(array), 1))).fit(
        cov_type="HAC", cov_kwds={"maxlags": HAC_LAG})
    mean, se = float(model.params[0]), float(model.bse[0])
    return {"n": len(array), "mean": mean, "se_hac3": se,
            "ci95_lower": mean - 1.9599639845 * se,
            "ci95_upper": mean + 1.9599639845 * se}


def phase3():
    prices, good, _ = load()
    if (DIAG / "phase3_signal_evaluation.md").exists():
        raise FileExistsError("Phase 3 result already recorded")
    opens = dict(zip(prices["timestamp"].to_list(), prices["open"].to_list()))
    gross_c, gross_b, rows = [], [], []
    for evt in good:
        rp = {}
        for arm in ("candidate", "control"):
            leg = evt["legs"][arm]
            entry = float(opens[datetime.fromisoformat(leg["entry_fill"])])
            exit_ = float(opens[datetime.fromisoformat(leg["exit_fill"])])
            gross = exit_ / entry - 1
            rp[arm] = gross
        gross_c.append(rp["candidate"])
        gross_b.append(rp["control"])
        rows.append({"month": evt["month"], **rp, "paired_gross": rp["candidate"] - rp["control"]})
    independent_years = len({x["month"][:4] for x in rows})
    ready = len(good) >= 60 and independent_years >= 6
    c, b, paired = hac(gross_c), hac(gross_b), hac([c - b for c, b in zip(gross_c, gross_b)])
    decision = ("INCONCLUSIVE" if not ready else
                "PASS" if c["mean"] > 0 and paired["mean"] > 0 else "FAIL")
    result = {"phase3": decision, "n_complete_pairs": len(good), "independent_years": independent_years,
              "candidate_gross": c, "control_gross": b, "paired_gross": paired,
              "costs_not_included": True, "price_proxy_bid_only": True,
              "post_event_missing_pairs": json.loads(PREFLIGHT.read_text())["status_counts"].get("data_invalid_pairs",0),
              "predeclared_native_diagnostic": "User explicitly requested native fixed-cost backtest regardless of gross screen; a gross FAIL does not become PASS.",
              "trials_executed": 1}
    save(DIAG/"phase3_signal.json", result)
    lines = [
        "# ResearchPhase 3 — DAX month-end fixed-cost MVP",
        "", f"**Phase 3 decision: {decision}.** This is a gross BID price-proxy directional test, not native execution.",
        "", f"- Preregistered session: {SID}; candidate and control are one frozen calendar variant.",
        f"- Observed complete pairs: {len(good)}, independent years: {independent_years}; minimum 60 over six years.",
        "- Price source: Dukascopy bid-only index_minute_DAX; outcome open at specified 09:11 and 17:11 Berlin times.",
        "- All fills would follow decisions one bar later. No price-based entry filters and no protected test access.",
        f"- Candidate gross mean per event: {100*c['mean']:.5f}% (HAC(3) 95% CI {100*c['ci95_lower']:.5f}% to {100*c['ci95_upper']:.5f}%).",
        f"- Control gross mean per event: {100*b['mean']:.5f}%.",
        f"- Paired candidate-minus-control gross mean: {100*paired['mean']:.5f}% (HAC(3) 95% CI {100*paired['ci95_lower']:.5f}% to {100*paired['ci95_upper']:.5f}%).",
        "- Preregistered PASS is positive standalone and paired gross point estimate with adequate sample; FAIL otherwise.",
        "- **User-directed native diagnostic:** even if Phase 3 is FAIL, execute fixed-cost native baseline for an auditable cost-inclusive conclusion; do not claim this changes Phase 3.",
        "- Missing future exit quote completeness is not an entry decision input; post-event missing pairs are reported and may prevent qualification.",
        "- Native order fills, 5bps per side, ACT/365 8% financing, and doubled-cost sensitivity are separate predeclared Phase 4 diagnostic trials.",
        "- No observed financing, historical ask, dividend adjustment, or source-to-execution parity has been verified.",
        "- Retrospective: NO; this phase was planned before gross outcomes were computed.",
    ]
    f = DIAG / "phase3_signal_evaluation.md"
    f.write_text("\n".join(lines) + "\n", encoding="utf8")
    print(json.dumps(result, indent=2))


class CalendarLong(Strategy):
    def __init__(self, events: list[dict], arm: str, costs: dict):
        self.arm, self.costs = arm, costs
        self.events = events
        self.at = {}
        for e in events:
            leg = e["legs"][arm]
            for action in ("entry", "exit"):
                self.at[datetime.fromisoformat(leg[action + "_decision"])] = (e["month"], action)
        self.orders = []
        self.entry_orders = {}
        self.finance_ledger = []

    def on_data(self, timestamp, data, context, broker):
        event = self.at.get(utc(timestamp))
        if event is None:
            return
        month, action = event
        bar = data.get("DAX")
        if bar is None:
            raise AssertionError("Missing DAX native source signal bar")
        if action == "entry":
            if broker.get_position("DAX") is not None:
                raise AssertionError("Unexpected open position at scheduled entry")
            # The exact later 09:11 open is not available to the strategy here.
            qty = INITIAL / float(bar["open"])
            order = broker.submit_order("DAX", qty, order_type=OrderType.MARKET)
            if order is None:
                raise AssertionError("Native buy order rejected on submission")
            self.entry_orders[month] = order
        else:
            pos = broker.get_position("DAX")
            if pos is None:
                raise AssertionError(f"Missing position at scheduled exit {month}")
            entry_order = self.entry_orders[month]
            if entry_order.filled_at is None:
                raise AssertionError("Entry not filled before exit")
            first = utc(entry_order.filled_at)
            final = utc(timestamp) + timedelta(minutes=1)
            days = (final - first).total_seconds() / 86400.0
            notional = float(pos.quantity) * float(entry_order.filled_price)
            cost = notional * self.costs["finance_rate_annual"] * days / 365.0
            before = float(broker.cash)
            broker.cash = before - cost
            self.finance_ledger.append({"month": month, "days": days, "notional": notional,
                                        "finance_debit": cost, "cash_before": before,
                                        "cash_after": float(broker.cash)})
            order = broker.close_position("DAX", order_type=OrderType.MARKET)
            if order is None:
                raise AssertionError("Native exit order rejected on submission")
        self.orders.append((month, action, utc(timestamp), order))

    def on_end(self, broker):
        if broker.get_position("DAX") is not None:
            raise AssertionError("Native engine retained an open final DAX position")


def native(prices: pl.DataFrame, events: list[dict], arm: str, costs: dict, cost_label: str):
    event_times = set()
    for evt in events:
        leg = evt["legs"][arm]
        event_times.update(datetime.fromisoformat(leg[k]) for k in
                           ("entry_decision", "entry_fill", "exit_decision", "exit_fill"))
        event_times.update(clock(date.fromisoformat(d), 17, 30) for d in leg["sessions"])
    feed_prices = prices.filter(pl.col("timestamp").is_in(sorted(event_times))).select(
        "timestamp", "symbol", "open", "high", "low", "close", "volume")
    assert feed_prices.height == len(event_times), (feed_prices.height, len(event_times))
    strategy = CalendarLong(events, arm, costs)
    config = BacktestConfig(
        initial_cash=INITIAL,
        allow_short_selling=False,
        allow_leverage=True, initial_margin=.5, long_maintenance_margin=.25,
        share_type=ShareType.FRACTIONAL,
        execution_mode=ExecutionMode.NEXT_BAR, execution_price=ExecutionPrice.OPEN,
        commission_type=CommissionType.PERCENTAGE, commission_rate=costs["commission_rate"],
        slippage_type=SlippageType.PERCENTAGE, slippage_rate=costs["slippage_rate"],
        partial_fills_allowed=False, timezone="UTC",
    )
    result = Engine(DataFeed(prices_df=feed_prices), strategy, config).run()
    if len(result.rejected_orders):
        raise AssertionError(f"Native rejects: {len(result.rejected_orders)}")
    assert len(strategy.orders) == 2 * len(events), (len(strategy.orders), len(events))
    assert len(result.trades) == len(events), (len(result.trades), len(events))
    orders = []
    for month, action, submitted, order in strategy.orders:
        expected = submitted + timedelta(minutes=1)
        filled = utc(order.filled_at) if order.filled_at else None
        if filled != expected or order.status.value != "filled":
            raise AssertionError(f"Wrong native fill {month} {action}: {filled} != {expected}; status {order.status}")
        orders.append({"month": month, "action": action, "submitted_at": submitted.isoformat(),
                       "expected_fill": expected.isoformat(), "filled_at": filled.isoformat(),
                       "filled_price": float(order.filled_price), "quantity": abs(float(order.quantity)),
                       "status": order.status.value})
    info = defaultdict(dict)
    for record in orders:
        info[record["month"]][record["action"]] = record
    charges = {row["month"]: row for row in strategy.finance_ledger}
    if len(charges) != len(events):
        raise AssertionError("Financing accrual not applied for each trade")
    per_trade = []
    for evt in events:
        m = evt["month"]
        e, x, f = info[m]["entry"], info[m]["exit"], charges[m]
        qty = e["quantity"]
        assert abs(x["quantity"] - qty) < 1e-6
        gross = (x["filled_price"] - e["filled_price"]) * qty
        commission = (x["filled_price"] + e["filled_price"]) * qty * costs["commission_rate"]
        net = gross - commission - f["finance_debit"]
        per_trade.append({"month": m, "side": arm, "gross_eur_after_slippage": gross,
                          "commission_eur": commission, "finance_eur": f["finance_debit"],
                          "net_eur": net, "net_return_initial_notional": net / INITIAL,
                          "holding_calendar_days": f["days"], "position_qty": qty,
                          "entry_price": e["filled_price"], "exit_price": x["filled_price"],
                          "entry_at": e["filled_at"], "exit_at": x["filled_at"]})
    final_value = float(result.metrics["final_value"])
    reconciliation = final_value - (INITIAL + sum(r["net_eur"] for r in per_trade))
    if abs(reconciliation) > 0.05:
        raise AssertionError(f"Native broker cash/PnL reconciliation failed: {reconciliation}")
    # Restore all XETR flat days in daily equity, rather than annualize only trade days.
    native_points = pl.DataFrame({
        "timestamp": [utc(t) for t, _ in result.equity_curve],
        "equity": [float(value) for _, value in result.equity_curve]})
    daily_native = (native_points.with_columns(pl.col("timestamp").dt.date().alias("date"))
                    .group_by("date").agg(pl.col("equity").last().alias("equity")))
    cal, sessions = session_calendar()
    daygrid = pl.DataFrame({"date": [d for d in sessions
                                  if date(2018,1,1) <= d <= date(2024,12,13)]})
    daily = daygrid.join(daily_native, on="date", how="left").sort("date").with_columns(
        pl.col("equity").forward_fill().fill_null(INITIAL))
    portfolio_returns = daily["equity"].pct_change().fill_null(0.0).to_numpy()
    stats = PortfolioAnalysis(returns=portfolio_returns, periods_per_year=252).compute_summary_stats()
    risk = {}
    for key, value in vars(stats).items():
        if isinstance(value, (int,float,np.number)):
            v = float(value)
            risk[key] = v if math.isfinite(v) else None
    if not math.isclose(final_value, float(daily["equity"][-1]), rel_tol=0, abs_tol=.05):
        raise AssertionError("Daily equity final differs from Engine ledger")
    yearly = {}
    for y in range(2018, 2025):
        sample = [r["net_eur"] for r in per_trade if r["month"].startswith(str(y))]
        yearly[str(y)] = {"trades": len(sample), "net_eur": sum(sample),
                          "return_initial_nav": sum(sample)/INITIAL}
    n = len(per_trade)
    summary = {"arm": arm, "cost_label": cost_label, "costs": costs,
               "engine": "ml4t.backtest.Engine(NEXT_BAR,OPEN)",
               "n_trades": n, "win_rate": sum(r["net_eur"] > 0 for r in per_trade)/n,
               "native_final_value_eur": final_value,
               "native_net_pnl_eur": final_value-INITIAL,
               "total_finance_eur": sum(f["finance_debit"] for f in charges.values()),
               "total_commission_eur": sum(r["commission_eur"] for r in per_trade),
               "avg_net_monthly_return": sum(r["net_return_initial_notional"] for r in per_trade)/n,
               "native_cash_pnl_reconciliation_eur": reconciliation,
               "risk_252d_daily_equity": risk, "yearly": yearly,
               "candidate_notional_fixed_initial": INITIAL,
               "source": "Dukascopy BID-only CFD proxy, 2025+ untouched",
               "quote_and_funding_assumptions_not_broker_validated": True}
    dest = RUN / ("native_" + cost_label + "_" + arm)
    dest.mkdir(parents=True, exist_ok=True)
    save(dest/"result.json", summary)
    save(dest/"trades.json", per_trade)
    save(dest/"orders.json", orders)
    save(dest/"financing_ledger.json", strategy.finance_ledger)
    daily.write_parquet(dest/"daily_equity.parquet")
    return summary, per_trade


def run_native():
    prices, events, plan = load()
    if len(events) < 60 or len(set(e["month"][:4] for e in events)) < 6:
        raise RuntimeError("Inadequate paired sample; do not label a backtest result conclusive")
    if not (DIAG/"phase3_signal_evaluation.md").exists():
        raise RuntimeError("Phase 3 must be recorded before native test")
    if (RUN/"terminal_result.json").exists():
        raise FileExistsError("Prior result exists; cannot repeat silently")
    outputs = {}
    for label, costs in (("base", COST_BASE), ("2x", COST_STRESS)):
        a, at = native(prices, events, "candidate", costs, label)
        b, bt = native(prices, events, "control", costs, label)
        assert [t["month"] for t in at] == [t["month"] for t in bt]
        p = [x["net_return_initial_notional"]-y["net_return_initial_notional"]
             for x,y in zip(at,bt)]
        stat = {"candidate_net": hac([x["net_return_initial_notional"] for x in at]),
                "control_net": hac([x["net_return_initial_notional"] for x in bt]),
                "paired_net": hac(p)}
        outputs[label] = {"candidate": a, "control": b, "hac3": stat,
                          "n_pairs": len(p)}
    actual = outputs["base"]
    cf = actual["hac3"]["candidate_net"]
    df = actual["hac3"]["paired_net"]
    has_missing = json.loads(PREFLIGHT.read_text())["status_counts"].get("data_invalid_pairs", 0)>0
    if cf["mean"]<=0 or df["mean"]<=0:
        decision = "REJECT"
    elif df["ci95_lower"]<=0 or has_missing:
        decision = "INCONCLUSIVE"
    else:
        decision = "VALIDATE"
    phase3result = json.loads((DIAG/"phase3_signal.json").read_text())
    terminal = {"mvp_decision": decision, "phase3": phase3result["phase3"],
                "mode": "HYPOTHETICAL_COSTS_BID_ONLY_NOT_BROKER_APPROVED",
                "num_complete_pairs": len(events),
                "post_event_invalid_months": json.loads(PREFLIGHT.read_text())["status_counts"].get("data_invalid_pairs",0),
                "base": outputs["base"], "stress_2x": outputs["2x"],
                "source_sha256": sha(STAGED), "scheduling_sha256": sha(SCHEDULE),
                "frozen_spec_sha256": sha(ROOT/"config/research_sessions"/(SID+".yaml")),
                "registered_trials_expected": ["phase3-signal-screen","phase4-native-base","phase4-native-2x-cost"],
                "no_protected_holdout_read": True,
                "no_promotion_or_live_broker_claim": True}
    save(RUN/"terminal_result.json",terminal)
    lines = [
        f"# DAX month-end liquidity-rebound fixed-cost MVP — {decision}",
        "", "**Interpretation:** purely hypothetical execution costs on Dukascopy BID-only CFD proxy. Do not treat as executable historical broker PnL.",
        "", f"Observed complete paired months: **{len(events)}** (2018–2024, last entry anchor November 2024); missing post-event months: **{terminal['post_event_invalid_months']}**.",
        f"Frozen Phase 3 signal decision: **{terminal['phase3']}**.",
        "", "## Base scenario (5 bps per side, 8% APR ACT/365 financing)",
        f"- Candidate mean monthly net per EUR100k: **{cf['mean']*100:.4f}%**; native EUR net **{actual['candidate']['native_net_pnl_eur']:,.2f}**.",
        f"- Control mean monthly net: **{actual['hac3']['control_net']['mean']*100:.4f}%**; native EUR net **{actual['control']['native_net_pnl_eur']:,.2f}**.",
        f"- Paired candidate - control: **{df['mean']*100:.4f}%**; HAC(3) 95% CI **[{df['ci95_lower']*100:.4f}%, {df['ci95_upper']*100:.4f}%]**.",
        f"- Candidate win rate **{actual['candidate']['win_rate']*100:.2f}%**; control **{actual['control']['win_rate']*100:.2f}%**.",
        "", "## Double-cost sensitivity (10 bps per side, 16% APR finance)",
        f"- Candidate mean net: **{outputs['2x']['hac3']['candidate_net']['mean']*100:.4f}%**; paired mean **{outputs['2x']['hac3']['paired_net']['mean']*100:.4f}%**.",
        "", "## Native execution and scientific limits",
        "- Actual `ml4t.backtest.Engine` order fills at the next observed 1-minute bar open; exact 09:11 and 17:11 Europe/Berlin fill assertions.",
        "- All trade fills, fees and ACT/365 financing are reflected in the native broker cash ledger and independently reconciled.",
        "- Bid-only series does not contain historical executable asks. Commission/slippage/financing are user-authorized fixed **assumptions**, not proven broker fees.",
        "- No verified Dukascopy dividend cash adjustments, price/performance index variant, lot step, contract multiplier, or source-to-live quote parity.",
        "- No strategy tuning or test-period peeking; no live orders.",
        "- A result `VALIDATE` supports only a separately authorized deeper validation program and does not authorize trading.",
        "", f"Input hashes: source {terminal['source_sha256']}; event plan {terminal['scheduling_sha256']}.",
    ]
    if REPORT.exists():
        raise FileExistsError(f"Refuse to overwrite report: {REPORT}")
    REPORT.write_text("\n".join(lines)+"\n",encoding="utf8")
    print(json.dumps({
        "decision":decision, "phase3":terminal["phase3"],"n_pairs":len(events),
        "base":{"candidate_net_monthly_pct":cf["mean"]*100,
                "control_net_monthly_pct":actual["hac3"]["control_net"]["mean"]*100,
                "paired_net_monthly_pct":df["mean"]*100,
                "paired_ci95_pct":[df["ci95_lower"]*100,df["ci95_upper"]*100],
                "candidate_win_pct":actual["candidate"]["win_rate"]*100,
                "candidate_total_eur":actual["candidate"]["native_net_pnl_eur"],
                "candidate_risk":actual["candidate"]["risk_252d_daily_equity"]},
        "stress":{"paired_net_monthly_pct":outputs["2x"]["hac3"]["paired_net"]["mean"]*100},
        "paths":[str(RUN/"terminal_result.json"),str(REPORT)]},indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["prepare","phase3","native"])
    args = parser.parse_args()
    {"prepare":prepare, "phase3":phase3, "native":run_native}[args.phase]()
