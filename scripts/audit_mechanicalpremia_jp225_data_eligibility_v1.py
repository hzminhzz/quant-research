"""Read-only acceptance/coverage evidence for JP225 substitution (no price outcomes)."""
import json
from collections import Counter
from datetime import date
from pathlib import Path
STORE=Path("/home/quant/dev/quant/ml4t-data/.data/store")
SETS={"US500":("ES","usa500idxusd"),"US100":("NQ","usatechidxusd"),
      "JP225":("NIKKEI225","jpnidxjpy"),"EU50":("EUSIDXEUR","eusidxeur")}
OUT=Path("docs/audit/mechanicalpremia-nikkei-replaces-dax-2013-2026-v1-data-eligibility.json")
report={"research_session":"mechanicalpremia-nikkei-replaces-dax-2013-2026-v1",
        "provider":"Dukascopy","price_type":"bid","cutoff_exclusive":"2026-10-12",
        "source":"local canonical daily-Hive Parquet + per-day acceptance",
        "data_integrity_from_acceptance_only":True,"instruments":{}}
for sym,(key,source) in SETS.items():
    path=STORE/f"index_minute_{key}"
    years={}
    for year in range(2013,2027):
        ds=[]
        for p in (path/f"year={year}").glob("month=*/day=*/data.parquet"):
            month=int(next(a[6:] for a in p.parts if a.startswith("month=")))
            day=int(next(a[4:] for a in p.parts if a.startswith("day=")))
            d=date(year,month,day)
            if d>=date(2026,10,12):continue
            ds.append(d)
        flags=Counter()
        for d in ds:
            ap=STORE/".acceptance"/f"index_minute_{key}"/f"{d.isoformat()}.json"
            if not ap.exists():
                flags["missing_acceptance"]+=1;continue
            meta=json.loads(ap.read_text())
            if not meta.get("accepted"): flags["unaccepted"]+=1
            if meta.get("dataset_key")!=f"index_minute_{key}":flags["source_key_mismatch"]+=1
            if meta.get("coverage_state")!="COMPLETE":flags["noncomplete"]+=1
            if meta.get("row_count",0)<(600 if sym=="EU50" else 1000):flags["under_daily_bar_threshold"]+=1
            sc=meta.get("source") or {}
            if sc.get("instrument") and sc["instrument"]!=source:flags["instrument_identity_mismatch"]+=1
            if sc.get("price_type") and sc["price_type"]!="bid":flags["price_type_mismatch"]+=1
        years[str(year)]={"files":len(ds),"start":str(min(ds)) if ds else None,
                          "last":str(max(ds)) if ds else None,"flags":dict(flags)}
    report["instruments"][sym]={"dataset":key,"source_instrument":source,"yearly":years}
OUT.write_text(json.dumps(report,indent=2)+"\n")
print(json.dumps({"path":str(OUT),"summary":{sym:{"years_with_data":sum(v["files"]>0 for v in val["yearly"].values()),"total_files":sum(v["files"] for v in val["yearly"].values()),"no_manifest_days":sum(v["flags"].get("missing_acceptance",0) for v in val["yearly"].values()),"short_days":sum(v["flags"].get("under_daily_bar_threshold",0) for v in val["yearly"].values())} for sym,val in report["instruments"].items()}},indent=2))
