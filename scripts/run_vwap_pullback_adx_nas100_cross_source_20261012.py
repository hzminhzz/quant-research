#!/usr/bin/env python3
"""Secondary LSE NAS100 cash index proxy replication; never claim CME NQ OOS."""
from __future__ import annotations
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import run_vwap_pullback_adx_phase5_20261012 as phase5
from scripts import run_vwap_pullback_adx_phase4_20261012 as original
from scripts.run_vwap_pullback_adx_execfix_v3_20261012 import LegalLimitsEngine
SID="vwap_pullback_adx_nas100_20261012_cross_source"
OUT=ROOT/"run_log"/SID/"phase5_cross_source"
phase5.FILE=ROOT/"data/processed/vwap_adx_nas100_2026h2_1m.parquet"
phase5.SHA="da3891d4ae7d686da6832081f322c7b2571bcc92e0e0ce5581b860a7e9d66e17"
def main():
 if OUT.exists() and any(OUT.iterdir()):raise FileExistsError("Existing trial evidence")
 assert (ROOT/"run_log/research_sessions"/SID/"frozen_spec.json").exists()
 feed,qa=phase5.build()
 if qa["accepted_count"]<60:raise RuntimeError(f"Insufficient index proxy coverage: {qa}")
 OUT.mkdir(parents=True,exist_ok=True)
 qa["kind"]="NAS100_CASH_INDEX_SECONDARY_PROXY_NOT_CME_FUTURES"
 qa["hypothetical_symbol_translation"]="NAS100 index prices -> NQ.F simulator label"
 (OUT/"source_qa.json").write_text(json.dumps(qa,indent=2)+"\n")
 original.OUT=OUT
 original.Engine=LegalLimitsEngine
 trials=[]
 for mode in ("B1","B2","B3"):
  for lab,fee,slip in (("gross",0.0,0.0),("cost",2.5,.25),("stress",2.5,.5)):
   a=original.run_mode(feed,mode,lab,fee,slip)
   trials.append(a)
   print("INDEX_ONLY",mode,lab,a["trades"],round(a["net_account_pnl_usd"],2),flush=True)
 (OUT/"all_trials.json").write_text(json.dumps(trials,indent=2,default=str)+"\n")
 print("INDEX_CROSS_SOURCE_COMPLETED_NOT_CME_OOS")
if __name__=="__main__":main()
