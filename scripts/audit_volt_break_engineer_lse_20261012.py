"""Independent replay-free audit of ML4T Engineer VOLT BREAK trial artifacts."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from zoneinfo import ZoneInfo
from scripts.run_volt_break_engineer_lse_20261012 import OUT,make_features,COSTS
CT=ZoneInfo("America/Chicago")
features,provenance=make_features()
assert provenance["daily_atr_parity_talib"]
assert provenance["sma_atr_parity_talib"]
assert provenance["minute_typprice_parity_talib"]
signal=features.loc[features["go_long"],["timestamp","date","minute"]].copy()
signal["entry_time_expected"]=signal["timestamp"]+pd.Timedelta(minutes=1)
signal_keys=set(signal["entry_time_expected"].to_numpy(dtype="datetime64[ns]"))
results=[]
for variant in COSTS:
    path=OUT/variant
    trades=pd.read_csv(path/"trades.csv")
    fills=pd.read_csv(path/"fills.csv")
    summary=json.loads((path/"summary.json").read_text())
    assert len(trades)==len(fills[fills["side"]=="buy"])==len(fills[fills["side"]=="sell"])==summary["trades"]
    assert abs(trades["pnl"].sum()-summary["total_pnl_usd"])<1e-7
    assert abs(trades["pnl"].sum()-(summary["final_equity"]-1_000_000.))<1e-7
    trades["entry_utc"]=pd.to_datetime(trades["entry_time"],utc=True)
    trades["exit_utc"]=pd.to_datetime(trades["exit_time"],utc=True)
    trades["entry_ct"]=trades["entry_utc"].dt.tz_convert(CT)
    trades["exit_ct"]=trades["exit_utc"].dt.tz_convert(CT)
    trades["session"]=trades["entry_ct"].dt.date
    entry_minutes=trades["entry_ct"].dt.hour*60+trades["entry_ct"].dt.minute
    exit_minutes=trades["exit_ct"].dt.hour*60+trades["exit_ct"].dt.minute
    assert ((entry_minutes>=600)&(entry_minutes<=840)&((entry_minutes%30)==0)).all()
    assert ((exit_minutes<=870)&(exit_minutes>=600)).all()
    assert (trades["entry_ct"].dt.date==trades["exit_ct"].dt.date).all()
    assert (trades.groupby("session").size()<=3).all()
    assert np.all(np.isin(trades["entry_utc"].to_numpy(dtype="datetime64[ns]"),list(signal_keys)))
    # Every close must occur at or after its entry, with same-minute native
    # exit permitted when the entry minute itself touches a barrier.
    assert (trades["exit_utc"]>=trades["entry_utc"]).all()
    assert (trades["multiplier"].round(7)==20.).all()
    gross_diff=(trades["exit_price"]-trades["entry_price"])*20-trades["gross_pnl"]
    assert gross_diff.abs().max()<1e-5
    # Native trade ledger includes commissions/slippage; no manual P&L edits.
    exit_reason=trades["exit_reason"].value_counts(dropna=False).to_dict()
    results.append({
        "cost":variant,"trades":len(trades),
        "verified_entry_signals":len(trades),
        "same_ct_day":True,"no_exit_after_1430":True,
        "native_ledger_reconciled":True,
        "gross_price_multiplier_reconciled":True,
        "max_filled_entries_on_day":int(trades.groupby("session").size().max()) if len(trades) else 0,
        "time_exit_count":int((exit_minutes==870).sum()),
        "stop_target_or_other_exits":int((exit_minutes<870).sum()),
        "same_minute_exit_count":int((trades["entry_utc"]==trades["exit_utc"]).sum()),
        "native_exit_reason_counts":exit_reason,
        "net_pnl_usd":summary["total_pnl_usd"],
        "win_rate":summary["win_rate"],
        "profit_factor":summary["profit_factor"],
        "sharpe_eligible_days_only":summary["calendar_risk"]["sharpe_ratio"]
    })
out={"status":"PASS", "feature_provider":"ML4T Engineer ATR14/SMA15/TypicalPrice",
     "data_source":"LSE NQ.F 2025, provider-defined futures series, no 2026",
     "validated_trials":results,
     "limitations":[
       "No validated dated futures roll mapping for NQ.F",
       "No independently authenticated exchange-trade VWAP",
       "ATR_Daily inner period unspecified by original; ATR14 is conventional assumption",
       "37 trading sessions / 31 trades insufficient for robust inference",
       "Cost/slippage are illustrative, not independently measured",
       "Execution same-minute both-hit stop-first is conservative but minute path unobserved"
     ]}
(OUT/"independent_execution_audit.json").write_text(json.dumps(out,indent=2,default=str,allow_nan=False))
print(json.dumps(out,indent=2,default=str,allow_nan=False))
