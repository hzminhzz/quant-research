"""Read-only canonical daily-partition eligibility for explicitly authorized 2025 and 2026YTD."""
from pathlib import Path
from collections import Counter
from datetime import date
import json

STORE=Path("/home/quant/dev/quant/ml4t-data/.data/store")
MAP={"US500":("ES","usa500idxusd"),"US100":("NQ","usatechidxusd"),
     "DE30":("DAX","deuidxeur"),"EU50":("EUSIDXEUR","eusidxeur")}
report={"session":"mechanicalpremia-authorized-2025-2026-ytd-v1","cutoff_exclusive":"2026-10-12",
        "status":"AUDITED_DAILY_ACCEPTANCE_ONLY","assets":{}}
for asset,(store,provider) in MAP.items():
    years={}
    for year in (2025,2026):
        files=[]
        for p in (STORE/f"index_minute_{store}"/f"year={year}").glob("month=*/day=*/data.parquet"):
            month=int(next(x.split("=")[1] for x in p.parts if x.startswith("month=")))
            day=int(next(x.split("=")[1] for x in p.parts if x.startswith("day=")))
            d=date(year,month,day)
            if d>=date(2026,10,12): continue
            files.append((d,p))
        issues=Counter()
        accepted=[]
        for d,p in files:
            a=STORE/".acceptance"/f"index_minute_{store}"/f"{d.isoformat()}.json"
            if not a.exists():
                issues["missing_acceptance"]+=1
                continue
            rec=json.loads(a.read_text())
            if rec.get("accepted") is not True:issues["not_accepted"]+=1
            if rec.get("dataset_key")!=f"index_minute_{store}":issues["dataset_key_mismatch"]+=1
            if rec.get("coverage_state")!="COMPLETE":issues["noncomplete_day"]+=1
            if rec.get("row_count",0)==0:issues["empty_day"]+=1
            if rec.get("row_count",0)<(600 if asset=="EU50" else 1000):issues["short_day"]+=1
            src=rec.get("source")
            if isinstance(src,dict) and src.get("instrument") and src["instrument"]!=provider:
                issues["provider_identity_mismatch"]+=1
            accepted.append(d)
        years[str(year)]={"partitions":len(files),"with_acceptance":len(accepted),
                            "first":str(min(accepted)) if accepted else None,
                            "last":str(max(accepted)) if accepted else None,
                            "issues":dict(issues)}
    report["assets"][asset]=years
print(json.dumps(report,indent=2))
