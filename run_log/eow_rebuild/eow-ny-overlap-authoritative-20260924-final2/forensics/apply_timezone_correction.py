from pathlib import Path
import json, polars as pl
p=Path("run_log/eow_rebuild/eow-ny-overlap-authoritative-20260924-final2/forensics")
pure=json.loads((p/"pure_timezone_correction.json").read_text())
wf=json.loads((p/"performance_waterfall.json").read_text())
r1=wf["stages"][1]
r2=wf["stages"][2]
old_r1=r1["net_r"]
r1["candidate_events"]=1121-181-454+211+563
r1["trades"]=pure["pure_timezone"]["summary"]["trade_count"]
r1["wr_pct"]=pure["pure_timezone"]["summary"]["win_rate_pct"]
r1["net_r"]=pure["pure_timezone"]["summary"]["net_r"]
r1["mean_r"]=pure["pure_timezone"]["summary"]["mean_r"]
r1["delta_r"]=pure["delta_net_r"]
r1["packed_sharpe"]=None
r1["common_daily_sharpe"]=None
r1["common_mdd"]=None
r1["common_metric_status"]="PURE_TIMEZONE_EVENT_TREATMENT_WITH_SHARED_META_REFIT; JP/HK events frozen to legacy"
r1["note"]="Only DE30/NAS100 session clocks changed. JP225/HK33 exact legacy events retained. Shared meta model retrained, so JP/HK score/gate movement is cross-asset model spillover, not timezone."
r2["delta_r"]=r2["net_r"]-r1["net_r"]
wf["identification_notes"].insert(0,"CORRECTION: the original timezone-only builder also applied corrected calendar/session filtering to JP/HK and retrained a shared cross-asset meta model. R1 has been replaced with a pure event treatment: JP/HK legacy events frozen; only DE30/NAS100 session clocks change. JP/HK gate changes are model spillover.")
(p/"performance_waterfall.json").write_text(json.dumps(wf,indent=2,sort_keys=True,default=str)+"\n")
pl.DataFrame(wf["stages"],infer_schema_length=None).write_parquet(p/"performance_waterfall.parquet")
s=(p/"forensic_summary.md").read_text()
corr=f"""
## Correction: pure timezone attribution

The earlier R1 label was too broad. The repository's timezone-only lane uses the corrected session/calendar path for every asset and then retrains one shared meta model. That allowed JP225/HK33 results to move despite having no DST clock change.

A corrected counterfactual freezes JP225/HK33 to their exact legacy event objects and changes only DE30/NAS100 session clocks:

- Pure timezone R: {pure['legacy']['summary']['net_r']:.2f}R -> {pure['pure_timezone']['summary']['net_r']:.2f}R, delta {pure['delta_net_r']:.2f}R.
- JP225: candidates 244 -> 244; gate spillover {pure['jp_hk_meta_spillover'][0]['meta_spillover_delta_r']:+.2f}R.
- HK33: candidates 242 -> 242; gate spillover {pure['jp_hk_meta_spillover'][1]['meta_spillover_delta_r']:+.2f}R.
- DE30 treated sleeve selected delta: {pure['per_instrument'][2]['selected_delta_r']:+.2f}R.
- NAS100 treated sleeve selected delta: {pure['per_instrument'][3]['selected_delta_r']:+.2f}R.

JP/HK score/gate movement in this counterfactual is shared-model spillover, not a timezone effect.
"""
if "## Correction: pure timezone attribution" not in s:
    s=s+"\n"+corr
(p/"forensic_summary.md").write_text(s)
print(json.dumps({"old_R1":old_r1,"corrected_R1":r1["net_r"],"corrected_R1_delta":r1["delta_r"],"R2R3_delta":r2["delta_r"]},indent=2))
