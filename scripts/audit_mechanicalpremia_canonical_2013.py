"""Audit eligible Dukascopy partition acceptance without reading any 2025+ data."""
import json
from collections import Counter,defaultdict
from datetime import date
from pathlib import Path
from statistics import median
ROOT=Path(__file__).resolve().parents[1]
CAT=Path("/home/quant/dev/quant/ml4t-data/.data/store")
SOURCES={"US500":("ES","usa500idxusd",1000),"US100":("NQ","usatechidxusd",1000),
"DE30":("DAX","deuidxeur",1000),"EU50":("EUSIDXEUR","eusidxeur",600)}
OUT=ROOT/"docs/audit/mechanicalpremia_data_2013_2024_v1.json"
report={"scope":"strictly year=2013..2024 acceptance and path inventory, no market returns",
"source":"Dukascopy 1-minute bid CFD","holdout_start":"2025-01-01T00:00:00Z","datasets":{}}
for name,(key,provider,threshold) in SOURCES.items():
    files=[]
    for year in range(2013,2025):
        files.extend((CAT/f"index_minute_{key}"/f"year={year}").glob("month=*/day=*/data.parquet"))
    seen=[]
    issues=Counter()
    counts=Counter()
    minute_counts=[]
    source_types=Counter()
    for file in sorted(files):
        year=int(next(part.split("=")[1] for part in file.parts if part.startswith("year=")))
        month=int(next(part.split("=")[1] for part in file.parts if part.startswith("month=")))
        day=int(next(part.split("=")[1] for part in file.parts if part.startswith("day=")))
        d=date(year,month,day).isoformat()
        acceptance=CAT/".acceptance"/f"index_minute_{key}"/f"{d}.json"
        if not acceptance.is_file():
            issues["missing_acceptance"]+=1
            continue
        data=json.loads(acceptance.read_text())
        counts[str(year)]+=1
        if data.get("accepted") is not True: issues["not_accepted"]+=1
        if data.get("coverage_state")!="COMPLETE": issues["coverage_noncomplete"]+=1
        if data.get("dataset_key")!=f"index_minute_{key}": issues["dataset_key_mismatch"]+=1
        if data.get("row_count",0)<threshold: issues["short_day"]+=1
        minute_counts.append(data.get("row_count",0))
        if isinstance(data.get("source"),dict):
            sym=data["source"].get("instrument")
            if sym and sym!=provider: issues["provider_instrument_mismatch"]+=1
            source_types[str(data["source"].get("price_type","unknown"))]+=1
        if data.get("quality_flags"): issues["flags_present"]+=1
        seen.append(d)
    report["datasets"][name]={"store":f"index_minute_{key}","first":min(seen) if seen else None,
      "last":max(seen) if seen else None,"eligible_partition_count":len(files),
      "accepted_record_count":len(seen),"counts_by_year":dict(sorted(counts.items())),
      "median_rows_per_day":median(minute_counts) if minute_counts else None,
      "threshold_min_rows":threshold,"issues":dict(issues),"price_types":dict(source_types)}
OUT.write_text(json.dumps(report,indent=2)+"\n")
print(json.dumps(report,indent=2))
