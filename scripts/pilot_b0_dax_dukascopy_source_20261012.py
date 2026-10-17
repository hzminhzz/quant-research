"""Pilot independent Dukascopy DEUIDXEUR BID 1m source on DAX bad dates.

No canonical store writes; preserve retrieval identities. Diagnostic only.
"""
from __future__ import annotations
import hashlib,json,lzma,struct,time
from pathlib import Path
from datetime import date,datetime,timezone
import httpx
import polars as pl

OUT=Path("run_log/one_bar_b0_cross_indices_20261012/followup_dax_nikkei_20261012")
DATES=[date(2024,9,10),date(2025,7,10),date(2026,6,17)]
def decode(payload,day):
    decompressed=lzma.decompress(payload)
    rows=[]
    for off in range(0,len(decompressed),24):
        if off+24>len(decompressed):break
        sec,o,c,l,h=struct.unpack_from(">5i",decompressed,off)
        volume=struct.unpack_from(">f",decompressed,off+20)[0]
        rows.append({"offset":sec,"raw_open":o,"raw_high":h,"raw_low":l,"raw_close":c,"volume":volume})
    return rows
def main():
    findings=[]
    for day in DATES:
        url=f"https://datafeed.dukascopy.com/datafeed/DEUIDXEUR/{day.year}/{day.month-1:02d}/{day.day:02d}/BID_candles_min_1.bi5"
        record={"date":str(day),"provider":"Dukascopy public DEUIDXEUR 1m BID","url":url,"access_status":"unknown"}
        try:
            t=time.time()
            with httpx.Client(follow_redirects=True,timeout=18.0) as client:
                res=client.get(url,headers={"User-Agent":"ml4t-source-validation/1.0"})
            record.update({"http_status":res.status_code,"elapsed_seconds":round(time.time()-t,3),"bytes":len(res.content),"sha256":hashlib.sha256(res.content).hexdigest()})
            res.raise_for_status()
            a=decode(res.content,day)
            record["raw_bars"]=len(a)
            record["access_status"]="available" if len(a) else "empty"
            if a:
                for scale in (100,1000):
                    closes=[row["raw_close"]/scale for row in a]
                    record[f"scale_{scale}_min_max"]=[min(closes),max(closes)]
                record["sample_first"]=[{k:v for k,v in item.items() if k!="volume"} for item in a[:3]]
        except Exception as exc:
            record["access_status"]="error"
            record["error"]=f"{type(exc).__name__}: {str(exc)[:300]}"
        findings.append(record)
        print("PILOT",day,record["access_status"],record.get("http_status"),record.get("raw_bars"),record.get("error",""),flush=True)
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/"dukascopy_deuidxeur_pilot.json").write_text(json.dumps({"status":"INDEPENDENT_SOURCE_PILOT_ONLY","observations":findings,
        "no_canonical_store_changes":True,
        "additional_source_consistency_checks_required":True},indent=2)+"\n")
if __name__=="__main__":main()
