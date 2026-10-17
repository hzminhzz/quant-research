"""Independent bounded source-price, timing and preservation oracle."""
from pathlib import Path
from datetime import timedelta
import hashlib
import json
import math
import polars as pl

ROOT=Path(__file__).resolve().parents[1]
SID="tokyo_fix_program2_cross_currency_20261011_v1"
OUT=ROOT/"run_log"/SID
DATA=ROOT/"data/processed"/SID

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    decisions=pl.read_parquet(DATA/"decision_features.parquet")
    assert decisions.select((pl.col("feature_available")<pl.col("decision")).all()).item()
    assert decisions["session"].max().isoformat()<"2026-09-01"
    count=0;label_count=0;window_count=0
    for pair in ["USDJPY","EURUSD","GBPUSD","AUDUSD"]:
        raw=pl.concat([pl.read_parquet(p).select("timestamp","close","open") for p in sorted(DATA.glob(f"{pair}_*.parquet"))]).sort("timestamp")
        lookup=dict(zip(raw["timestamp"].to_list(),raw["close"].to_list()))
        opens=dict(zip(raw["timestamp"].to_list(),raw["open"].to_list()))
        for row in decisions.to_dicts():
            end=row["decision"]-timedelta(minutes=2)
            for h in [5,15,30,60]:
                value=row[f"{pair}_f{h}"]
                if value is None:continue
                start=end-timedelta(minutes=h)
                assert end+timedelta(minutes=1)<row["decision"]
                assert all(start+timedelta(minutes=k) in lookup for k in range(h+1))
                expected=math.log(lookup[end]/lookup[start])
                assert math.isclose(expected,value,abs_tol=1e-13)
                count+=1;window_count+=1
        if pair=="USDJPY":
            for row in pl.read_parquet(DATA/"event_labels.parquet").to_dicts():
                start=row["decision"]+timedelta(minutes=1)
                for h in [5,15,30,60]:
                    val=row[f"y{h}"]
                    if val is None:continue
                    end=start+timedelta(minutes=h)
                    assert all(start+timedelta(minutes=k) in opens for k in range(h+1))
                    assert math.isclose(math.log(opens[end]/opens[start])*10000,val,abs_tol=1e-10)
                    label_count+=1
    preservation=json.loads((OUT/"preservation_before.json").read_text())
    changed=[p for p,digest in preservation.items() if sha(ROOT/p)!=digest]
    assert not changed,changed
    complete=json.loads((OUT/"analysis_complete.json").read_text())
    for p,digest in complete["snapshot_hashes"].items():assert sha(ROOT/p)==digest
    lead=json.loads((OUT/"T4_leadlag/result.json").read_text())
    assert len(lead["tests"])==640
    assert len({r["id"] for r in lead["tests"]})==640
    assert all(math.isfinite(r["p_holm640"]) and r["p_holm640"]>=r["p"]-1e-12 for r in lead["tests"])
    test_map={r["id"]:r for r in lead["tests"]}
    labeled=pl.read_parquet(DATA/"event_labels.parquet")
    missing_stress=0
    for item in lead["native_walkforward"]:
        r=test_map[item["id"]]
        samples=labeled.filter((pl.col("anchor")==r["anchor"]) & pl.col(r["group"])).drop_nulls([f'{r["pair"]}_f{r["lookback"]}',f'USDJPY_f{r["lookback"]}',f'y{r["horizon"]}'])
        expected=[]
        for year in [2024,2025,2026]:
            ntrain=samples.filter(pl.col("year")<year).height
            ntest=samples.filter(pl.col("year")==year).height
            if ntrain>=100 and ntest>=20:expected.append((ntrain,ntest))
            elif year==2026:missing_stress+=1
        assert [(f["n_train"],f["n_test"]) for f in item["folds"]]==expected
        assert all(math.isfinite(f[metric]) for f in item["folds"] for metric in ["ic","hit_rate"])
    native=json.loads((OUT/"T6_native_disposition/result.json").read_text())
    assert native["native_candidate_runs"]==0
    dest=OUT/"T7_verification/result.json"
    if dest.exists():raise RuntimeError("Refuse existing oracle")
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps({"status":"PASS","independent_feature_prices":count,"complete_lookback_windows":window_count,"independent_target_prices":label_count,"preserved_prior_and_dirty_files":len(preservation),"source_hashes":len(complete["snapshot_hashes"]),"holdout":"SEALED","native_fold_metrics_finite":True,"native_fold_counts_independently_match":True,"tests_without_20_stress_observations":missing_stress},indent=2)+"\n")
    print(dest.read_text())

if __name__=="__main__":main()
