#!/usr/bin/env python3
"""Phase 6 frozen-development-only native robustness checks B1,B2,B3."""
from __future__ import annotations
import json,sys
from pathlib import Path
from types import MethodType
from ml4t.backtest.types import OrderSide
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import run_vwap_pullback_adx_phase4_20261012 as parent
from scripts.run_vwap_pullback_adx_execfix_v3_20261012 import LegalLimitsEngine

SID="vwap_pullback_adx_nq_20261012_proxy_v4_phase56"
OUT=ROOT/"run_log"/SID/"phase6"
TICK=0.25
class Queue1TickEngine(LegalLimitsEngine):
 def __init__(self,*args,**kwargs):
  super().__init__(*args,**kwargs)
  eng=self.broker._fill_engine
  original=eng.check_limit_fill
  def stricter(engine,order,high,low):
   lim=order.limit_price
   if lim is None:return None
   if order.side==OrderSide.SELL:
    return original(order,high,low) if high>=lim+TICK-1e-9 else None
   return original(order,high,low) if low<=lim-TICK+1e-9 else None
  eng.check_limit_fill=MethodType(stricter,eng)

def main():
 if OUT.exists() and any(OUT.iterdir()):
  raise FileExistsError("Do not overwrite Phase6 evidence")
 assert (ROOT/"run_log/research_sessions"/SID/"frozen_spec.json").exists()
 feed=parent.prepare()  # SAME 122 H1 development sessions as registered v3
 assert feed["day"].n_unique()==122
 parent.OUT=OUT
 OUT.mkdir(parents=True,exist_ok=True)
 results=[]
 for mode in ("B1","B2","B3"):
  for label,engine,fee,slip in [
   ("stress4tick",LegalLimitsEngine,2.5,1.0),
   ("limit_queue1tick",Queue1TickEngine,2.5,0.25)]:
   parent.Engine=engine
   print("START",mode,label,flush=True)
   result=parent.run_mode(feed,mode,label,fee,slip)
   results.append(result)
   print("DONE",mode,label,result["trades"],round(result["net_account_pnl_usd"],2),flush=True)
 (OUT/"all_trials.json").write_text(json.dumps(results,indent=2,default=str)+"\n")
 print("PHASE6_NATIVE_COMPLETE")
if __name__=="__main__":main()
