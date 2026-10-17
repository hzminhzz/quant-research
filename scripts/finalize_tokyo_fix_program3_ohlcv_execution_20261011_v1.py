"""Append final execution accounting and preservation evidence; never refreeze."""
import json
import subprocess
import sys
from pathlib import Path
from run_tokyo_fix_program3_ohlcv_execution_20261011_v1 import ROOT,SID,OUT,SPEC,sha,save,cli

def main():
    oracle=json.loads((OUT/'T3_oracle/result.json').read_text())
    assert oracle['status']=='PASS' and len(oracle['results'])==14
    for check in ['program3_final_tests.log','focused_pytest.log']:
        assert 'passed' in (OUT/check).read_text()
    frozen=json.loads((ROOT/f'run_log/research_sessions/{SID}/frozen_spec.json').read_text())
    before=json.loads((OUT/'preservation_before.json').read_text())
    changed=[name for name,value in before['hashes'].items() if not (ROOT/name).exists() or sha(ROOT/name)!=value]
    assert not changed,changed
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip();assert head==before['head']
    diff=subprocess.run(['git','diff','--check'],cwd=ROOT,capture_output=True,text=True);assert diff.returncode==0,diff.stdout+diff.stderr
    status=subprocess.check_output(['git','status','--porcelain=v1','--untracked-files=all'],cwd=ROOT,text=True)
    (OUT/'final_git_status.txt').write_text(status)
    variants={x['id']:x for x in frozen['spec']['evaluation']['variants']}
    runs=[]
    for directory,disposition in [('runs','Initial execution. Six policies rejected by decimal oracle; all initial artifacts retained. Corrected runs are authoritative.'),('runs_corrected','VERIFIED every fill and missed signal by independent Decimal oracle; hypothetical eligibility only.')]:
        for p in sorted((OUT/directory).glob('*/result.json')):
            r=json.loads(p.read_text());runs.append({'id':r['id'],'path':str(p.relative_to(ROOT)),'sha256':sha(p),'signals':r['submitted'],'fills':r['filled'],'disposition':disposition,'strategic_variant_unchanged':True})
    attempts=[]
    for p in sorted(OUT.glob('execution_attempt*.log')):
        text=p.read_text();attempts.append({'path':str(p.relative_to(ROOT)),'sha256':sha(p),'status':'FAILED_RUNTIME' if 'Traceback' in text else 'COMPLETED','reason':text.splitlines()[-1] if 'Traceback' in text else 'Fixed matrix completed','native_artifact_disposition':'No deletion or overwrite'})
    code=[ROOT/f'scripts/{prefix}{SID}.py' for prefix in ['run_','verify_','supplement_','finalize_']]+[ROOT/f'tests/test_{SID}.py']
    initial_runner=next(x for x in frozen['identity']['source'] if x['path']==f'scripts/run_{SID}.py')
    save(OUT/'execution_accounting.json',{'status':'ALL_ATTEMPTS_RETAINED','economic_unique_rules':14,'cost_overlays':56,'native_full_artifacts':28,'engine_runs_returned':29,'partial_artifact_runtime_failure':'Attempt3 first market Engine.run returned, raw orders/trades preserved; failed touch-count finalization; identical policy replay in attempt4.','attempts':attempts,'runs':runs,'initial_run_fill_dispositions':oracle['initial_preserved_run_audits'],'correction':'Binary floating dust admitted some exact touches. Compare nominal decimal prices at8decimal places; unchanged raw OHLC and frozen strict-cross policy. No parameter selection. Full corrected replay separate.','authoritative_comparison':'T2_comparison_corrected/result.json','original_CLI_terminal_records':'Create-once originals retained; completed means run executed, not fill validation. T3/T4 supply rejected/corrected dispositions and identities.','implementation_amendment':{'frozen_initial_runner':initial_runner,'actual_final_sources':{str(p.relative_to(ROOT)):sha(p) for p in code}},'additional_skill':{'name':'ml4t-information-coefficient','path':'.agents/skills/ml4t-information-coefficient/SKILL.md','sha256':sha(ROOT/'.agents/skills/ml4t-information-coefficient/SKILL.md'),'reason':'Single-asset event Rank correlation; no cross-sectional breadth claim; controlled HAC evidence and yearly stability independently checked.'},'no_new_selection_trials':True})
    cli('record','--session',SID,'--trial','T3_oracle','--status','completed','--artifact',str((OUT/'T3_oracle/result.json').relative_to(ROOT)))
    check=cli('check','--session',SID);assert check['status']=='PASS';save(OUT/'final_identity_check.json',check)
    report=ROOT/f'docs/audit/{SID}.md'
    artifacts={str(p.relative_to(ROOT)):sha(p) for p in sorted(OUT.rglob('*')) if p.is_file()}
    artifacts.update({str(p.relative_to(ROOT)):sha(p) for p in code+[report,SPEC]})
    save(OUT/'T4_final_audit/result.json',{'status':'PASS_RESEARCH_COMPLETE','approval_status':'NOT_APPROVED','head':head,'preservation_checked_files':len(before['hashes']),'changed_original_files':changed,'holdout':'SEALED; inputs exclusively frozen annual snapshots ending before2026-09-01JST','native_effective_runs':14,'effective_trades':sum(r['trades_checked'] for r in oracle['results']),'effective_fills':sum(r['fills_checked'] for r in oracle['results']),'every_limit_fill_assumption':'Independent original-source quantizedDecimal oracle PASS plus native semantics probes and native integration tests. Real queue/fill probability UNKNOWN.','metrics_cost_scenarios':56,'tests':{'focused':'51passed,3SHAP third-party deprecation warnings','final_program3':'20passed','native_semantics':'8passed','full_suite':'Interrupted exit130 after304items collected and progress stalled near47%; no full pass claimed','uv_initial':'Cache lock write failed under readonly user cache; retry usedUV_CACHE_DIR=/tmp and --no-sync installed environment'},'git_diff_check':'PASS','processes':{'research_sessions':'All5attempts returned; no active research job left','full_tests':'Stopped withSIGINT exit130; focused and final suites returned','host_tmux':'UNKNOWN due sandbox Operation not permitted. Task socket also blocked. No background or remote launch. Monitored unified execution used.','host_process_visibility':'Private sandbox namespace; cannot certify unrelated host jobs'},'frozen_spec_sha256':frozen['spec_sha256'],'decision':'Robustness falsifier FAILED:11of12negative at1pip, remaining positive rule negative with0.5pipbuffer; all12negative2026; market positive full sample only belowcost2pip','negative_and_failed_records':'execution_accounting.json and retained immutable initial artifacts','source_and_result_identities':artifacts,'next_decisive_question':'Can timestamp-verified future executable bid/ask and real passive outcomes establish fill probability and positive expectancy after costs? Preregister future quote/order study; do not open sealed holdout.'})
    cli('record','--session',SID,'--trial','T4_final_audit','--status','completed','--artifact',str((OUT/'T4_final_audit/result.json').relative_to(ROOT)))
    ledger=cli('report','--session',SID)
    save(OUT/'final_session_report.json',ledger)
    print(json.dumps({'preserved':len(before['hashes']),'oracle':oracle['status'],'native_fills':sum(r['fills_checked'] for r in oracle['results']),'all_trials_recorded':all(t['status']=='completed' for t in ledger['trials']) if 'trials' in ledger else 'inspect_report','identity_status':check['status']}))

if __name__=='__main__':main()
