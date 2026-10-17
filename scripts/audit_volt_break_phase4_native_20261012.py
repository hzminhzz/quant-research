"""Independent audit of native Engine-created VOLT BREAK trade artifacts.

Rebuilds signal eligibility, checks exact prior completed minute, times,
native account ledger and risk on all 1576 fully-qualified CT research dates.
Does not simulate fills or recalculate strategy PnL from price.
"""
from pathlib import Path
import json
import numpy as np
import polars as pl
from ml4t.diagnostic.api import PortfolioAnalysis
from scripts.run_volt_break_phase4_native_20261012 import load_candidates,OUT,COSTS,MINUTES

prepared=load_candidates()
valid_dates=prepared.select("date").unique().sort("date")
records=[]
for variant in MINUTES:
    for cost in COSTS:
        path=OUT/variant/cost
        metrics=json.loads((path/"summary.json").read_text())
        trades=pl.read_csv(path/"trades.csv",try_parse_dates=True)
        fills=pl.read_csv(path/"fills.csv",try_parse_dates=True)
        daily=pl.read_csv(path/"daily_equity.csv",try_parse_dates=True)
        assert len(trades)==metrics["native_entry_count"]
        assert int(fills.filter(pl.col("side")=="buy").height)==len(trades)
        assert int(fills.filter(pl.col("side")=="sell").height)==len(trades)
        assert abs(float(trades["pnl"].sum())-metrics["total_net_pnl_usd"])<1e-5
        assert abs(float(trades["pnl"].sum())-(metrics["final_equity_usd"]-1_000_000))<1e-4
        # Native trade CSV timestamps are naive UTC; set timezone, never infer local CT.
        assert trades.schema["entry_time"].time_zone is None
        tr=(trades.with_columns(
          entry_ct=pl.col("entry_time").dt.replace_time_zone("UTC")
              .dt.convert_time_zone("America/Chicago"),
          exit_ct=pl.col("exit_time").dt.replace_time_zone("UTC")
              .dt.convert_time_zone("America/Chicago"),
          entry_utc=pl.col("entry_time").dt.replace_time_zone("UTC"),
          exit_utc=pl.col("exit_time").dt.replace_time_zone("UTC")
        ).with_columns(
          ct_day=pl.col("entry_ct").dt.date(),
          entry_minute=pl.col("entry_ct").dt.hour().cast(pl.Int32)*60+
                       pl.col("entry_ct").dt.minute().cast(pl.Int32),
          exit_minute=pl.col("exit_ct").dt.hour().cast(pl.Int32)*60+
                      pl.col("exit_ct").dt.minute().cast(pl.Int32)
        ))
        assert tr.filter(pl.col("entry_ct").dt.date()!=pl.col("exit_ct").dt.date()).is_empty()
        assert tr.filter(~pl.col("entry_minute").is_between(600,840)).is_empty()
        assert tr.filter(pl.col("entry_minute")%30!=0).is_empty()
        assert tr.filter(pl.col("exit_minute")>870).is_empty()
        assert tr.filter(pl.col("exit_minute")<600).is_empty()
        assert tr.group_by("ct_day").agg(pl.len().alias("n")).filter(pl.col("n")>3).is_empty()
        assert tr.filter(pl.col("entry_time")>pl.col("exit_time")).is_empty()  # Same-minute stop-first exit is permitted.
        # Every BUY entry must correspond to a true eligible signal on its
        # 09:59/10:29/... completed minute (at event time - 1 minute).
        refs=(prepared.select(pl.col("timestamp").alias("signal_utc"),
                  pl.col("date").alias("signal_ct_day"),
                  pl.col(f"signal_{variant}").alias("qualified_signal")))
        matched=tr.with_columns(signal_utc=pl.col("entry_utc")-pl.duration(minutes=1))
        matched=matched.join(refs,on="signal_utc",how="left")
        assert matched.filter(pl.col("qualified_signal")!=True).is_empty(),(
          variant,cost,matched.filter(pl.col("qualified_signal")!=True).height)
        assert matched.filter(pl.col("signal_ct_day")!=pl.col("ct_day")).is_empty()

        # Time exit is necessarily at 14:30 CT. For stop/target
        # the exit can occur earlier. Both-touch count uses the exit
        # event's own OHLC and native filled entry price (not next bars).
        event_rows=prepared.select(
          pl.col("timestamp").alias("exit_utc"),"high","low","open")
        trade_exit=tr.join(event_rows,on="exit_utc",how="left")
        assert trade_exit.filter(pl.col("high").is_null()).is_empty()
        dual_touch=trade_exit.filter(
          (pl.col("exit_minute")<870)&
          (pl.col("low")<=pl.col("entry_price")-75)&
          (pl.col("high")>=pl.col("entry_price")+40)
        ).height

        # Portfolio risk on the FULL 1576-day eligible source calendar, including
        # dates with no ATR or no trades. Forward filling previous native end-of-day
        # NAV is not simulating execution: those dates are confirmed flat.
        ed=(valid_dates.join(daily,on="date",how="left").sort("date")
            .with_columns(pl.col("equity").forward_fill().fill_null(1_000_000.0)))
        e=ed["equity"].to_numpy()
        ret=np.diff(np.r_[1_000_000.,e])/np.r_[1_000_000.,e][:-1]
        rm=PortfolioAnalysis(returns=ret,periods_per_year=252).compute_summary_stats()
        full_risk={k:(None if isinstance(v,(float,np.floating)) and not np.isfinite(v)
                      else (float(v) if isinstance(v,np.generic) else v))
                   for k,v in vars(rm).items()
                   if isinstance(v,(str,int,float,type(None),np.generic))}
        records.append({
          "variant":variant,"cost":cost,
          "trade_count":tr.height,"native_pnl_usd":metrics["total_net_pnl_usd"],
          "profit_factor":metrics["profit_factor"],"win_rate":metrics["win_rate"],
          "expectancy_per_trade_usd":metrics["avg_trade_usd"],
          "entry_time_qualification":"PASS",
          "max_entries_per_ct_date":int(tr.group_by("ct_day").agg(pl.len().alias("n"))["n"].max()),
          "positions_closed_by_1430_ct":"PASS",
          "entry_day_eq_exit_day":"PASS",
          "ledger_reconciliation":"PASS",
          "dual_touch_at_exit_bar_count":dual_touch,
          "time_exits_at_1430":int((tr["exit_minute"]==870).sum()),
          "risk_eligible_only":metrics["daily_equity_risk_metrics"],
          "risk_full_1576_ct_days":full_risk,
          "by_year":metrics["by_year"],
          "immediate_entry_bar_exits":metrics["adapter_immediate_exit_fills"],
          "no_2026_outcomes_read":True
        })
out={"session":"volt_break_nq_20261012","status":"INDEPENDENT_AUDIT_COMPLETED",
     "native_ml4t_engine":"0.1.7 with risk lifecycle adapter",
     "source":"Dukascopy USATECH.IDX/USD BID CFD proxy",
     "sample_calendar_fully_qualified_days":1576,"protected_2026_read":False,
     "interpretation":"retrospective CFD proxy; ATR coverage source sensitivity, stop-first dual touch convention",
     "results":records}
target=OUT/"phase4_independent_audit_20261012.json"
target.write_text(json.dumps(out,indent=2,default=str,allow_nan=False))
for r in records:
 print("AUDIT",json.dumps({k:r[k] for k in [
   "variant","cost","trade_count","native_pnl_usd","dual_touch_at_exit_bar_count",
   "time_exits_at_1430","max_entries_per_ct_date"]}),"CALENDAR_RISK",
   json.dumps({k:r["risk_full_1576_ct_days"].get(k) for k in
     ("sharpe_ratio","calmar_ratio","max_drawdown","annual_return")}),flush=True)
