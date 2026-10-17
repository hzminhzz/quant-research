"""Declared-baseline and accounting evidence; no additional candidate search."""
import json
import numpy as np
import polars as pl
import statsmodels.api as sm
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LinearRegression
try:
    from run_tokyo_fix_program2_cross_currency_20261011_v1 import ROOT,SID,OUT,DATA,AnnualExpanding,save,mean_hac
except ModuleNotFoundError:
    from scripts.run_tokyo_fix_program2_cross_currency_20261011_v1 import ROOT,SID,OUT,DATA,AnnualExpanding,save,mean_hac
from ml4t.diagnostic import Evaluator

def main():
    flow=pl.read_parquet(OUT/"flow_events.parquet")
    parts=[]
    for a,b in [(420,510),(510,594),(596,610),(596,630)]:
        w=flow.filter((pl.col("start")==a)&(pl.col("end")==b)).select("session","gotobi","year","pair","return_bps").pivot(on="pair",index=["session","gotobi","year"],values="return_bps").drop_nulls().sort("session")
        w=w.with_columns((-pl.mean_horizontal("EURUSD","GBPUSD","AUDUSD",ignore_nulls=False)).alias("USDfactor"))
        for group in [True,False]:
            d=w.filter(pl.col("gotobi")==group)
            fit=sm.OLS(d["USDJPY"].to_numpy(),sm.add_constant(d["USDfactor"].to_numpy())).fit(cov_type="HAC",cov_kwds={"maxlags":5},use_t=True)
            parts.append({"start":a,"end":b,"gotobi":group,"n":d.height,"common_USD_mean_bps":mean_hac(d["USDfactor"].to_numpy()),"USDJPY_loading":float(fit.params[1]),"loading_ci95":list(map(float,fit.conf_int()[1])),"contemporaneous_r2":float(fit.rsquared),"inference":"Descriptive co-movement; unexplained component cannot identify JPY flow"})
    save("T3_decomposition/factor_components.json",{"status":"PARTIAL_UNIDENTIFIED","profiles":parts})
    events=pl.read_parquet(DATA/"event_labels.parquet")
    lead=json.loads((OUT/"T4_leadlag/result.json").read_text())
    combined={r["id"]:r["folds"] for r in lead["native_walkforward"]}
    baselines=[]
    for r in lead["tests"]:
        if r["id"] not in combined:continue
        a,p,lb,h,g=r["anchor"],r["pair"],r["lookback"],r["horizon"],r["group"]
        d=events.filter((pl.col("anchor")==a)&pl.col(g)).drop_nulls([f"{p}_f{lb}",f"USDJPY_f{lb}",f"y{h}"]).sort("session")
        ev=Evaluator(splitter=AnnualExpanding(d["year"].to_numpy()),metrics=["ic","hit_rate"],statistical_tests=[],tier=3).evaluate(d.select(f"USDJPY_f{lb}").to_numpy(),d[f"y{h}"].to_numpy(),make_pipeline(StandardScaler(),LinearRegression()),strategy_func=lambda pred,actual:np.zeros_like(actual))
        rows=[]
        for base,full in zip(ev.fold_results,combined[r["id"]]):
            assert base["n_train"]==full["n_train"] and base["n_test"]==full["n_test"]
            assert all(np.isfinite(base[m]) for m in ["ic","hit_rate"])
            rows.append({"year":2024+base["fold"],"n_train":base["n_train"],"n_test":base["n_test"],"own_only_ic":base["ic"],"combined_ic":full["ic"],"ic_increment":full["ic"]-base["ic"],"own_only_hit_rate":base["hit_rate"],"combined_hit_rate":full["hit_rate"]})
        baselines.append({"id":r["id"],"folds":rows})
    save("T4_leadlag/own_only_baseline.json",{"tests":baselines,"inference":"Matched own-USDJPY-only versus combined native model. IC differences are descriptive, not additional independent significance."})
    checks=[]
    for name,direction,hedge in [("C1_USD_confirmed_short",-1,False),("C2_USD_neutral_EUR_hedge",-1,True)]:
        d=pl.read_parquet(OUT/f"{name}_markouts.parquet")
        d=d.with_columns(pl.lit(direction*(5000 if hedge else 10000)).alias("q_USDJPY"),
            (direction*5000/pl.col("in_EURUSD") if hedge else pl.lit(0.)).alias("q_EURUSD"))
        d=d.with_columns((pl.col("q_USDJPY")-(pl.col("q_EURUSD")*pl.col("in_EURUSD") if hedge else 0)).alias("USD_units"),
            (-pl.col("q_USDJPY")*pl.col("in_USDJPY")).alias("JPY_units"),pl.col("q_EURUSD").alias("EUR_units"),pl.lit(0.).alias("GBP_units"),pl.lit(0.).alias("AUD_units"),
            (pl.col("q_USDJPY").abs()+(pl.col("q_EURUSD").abs()*pl.col("in_EURUSD") if hedge else 0)).alias("gross_entry_usd"))
        pnl=pl.col("q_USDJPY")*(pl.col("out_USDJPY")-pl.col("in_USDJPY"))/pl.col("out_USDJPY")
        value=pl.col("USD_units")+pl.col("JPY_units")/pl.col("in_USDJPY")
        if hedge:
            pnl=pnl+pl.col("q_EURUSD")*(pl.col("out_EURUSD")-pl.col("in_EURUSD"))
            value=value+pl.col("EUR_units")*pl.col("in_EURUSD")
        d=d.with_columns(pnl.alias("independent_gross_pnl_usd"),value.alias("net_entry_value_usd"))
        assert d["gross_entry_usd"].max()<=10000+1e-9
        assert d["net_entry_value_usd"].abs().max()<1e-8
        assert (d["independent_gross_pnl_usd"]-d["gross_usd"]).abs().max()<1e-8
        if hedge:assert d["USD_units"].abs().max()<1e-8
        d.write_parquet(OUT/f"{name}_currency_exposures.parquet")
        checks.append({"candidate":name,"rows":d.height,"max_gross_entry_usd":d["gross_entry_usd"].max(),"max_USD_units_abs":d["USD_units"].abs().max(),"Pnl_quote_conversion_parity":True,"all_currency_units_recorded":True})
    save("T5_candidates/exposure_oracle.json",{"status":"PASS","checks":checks,"warning":"Entry markout sizing only; no qualified holdings, broker readiness or intrahold gross cap claim"})

if __name__=="__main__":main()
