#!/usr/bin/env bash
# Registered MT5-style ATR research only. All market execution remains native ml4t-backtest.
set -u
cd /home/quant/dev/quant/quant-research || exit 2
root="run_log/mechanicalpremia_yen_squeeze_mt5atr_v4_20261014"
session="mechanicalpremia-yen-squeeze-mt5atr-v4-20261014"
status="$root/500_gate_status.log"
while kill -0 3555260 2>/dev/null; do sleep 20; done
trial="PORTFOLIO-500-2PIP"
summary="$root/$trial/summary.json"
if ! test -s "$summary"; then
  echo "$trial INCOMPLETE $(date -u +%FT%TZ); inspect native log before any new run" >> "$status"
  exit 3
fi
# The original trial summary was written directly by the native Engine runner.
.venv/bin/python scripts/research_session.py record --root . --session "$session" --trial "$trial" --status completed --artifact "$summary" >> "$status" 2>&1 || { echo "$trial LEDGER_RECORD_ERROR" >> "$status"; exit 4; }
echo "$trial COMPLETE_NATIVE $(date -u +%FT%TZ)" >> "$status"
# Conditional gate merely interprets already-produced native metrics; it does
# not compute backtest returns, simulate trades or rewrite the frozen thesis.
if .venv/bin/python - "$summary" <<'PY'
import json, math, sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
net=d["native_net_profit_usd"]
sharpe=d["daily_equity_diagnostic_metrics"].get("sharpe_ratio")
print(f"500h 2pips native net={net:.2f}, daily Sharpe={sharpe}",flush=True)
sys.exit(0 if net > 0 and isinstance(sharpe,(int,float)) and math.isfinite(sharpe) and sharpe > 0 else 1)
PY
then
  echo "500H_2PIP_PROFIT_GATE_PASSED; run preregistered 4/6pip cost stress" >> "$status"
  for pips in 4 6; do
    trial="PORTFOLIO-500-${pips}PIP"
    if test -f "$root/$trial/summary.json"; then
      echo "$trial EXISTING_SKIP" >> "$status"
      continue
    fi
    echo "$trial START $(date -u +%FT%TZ)" >> "$status"
    MPLCONFIGDIR=/tmp/yen-mt5-mpl XDG_CACHE_HOME=/tmp/yen-mt5-cache .venv/bin/python -m scripts.run_mechanicalpremia_yen_squeeze_mt5atr_v4_20261014 --lookback 500 --pips "$pips" > "$root/$trial.log" 2>&1
    rc=$?
    echo "$trial EXIT=$rc $(date -u +%FT%TZ)" >> "$status"
    if test "$rc" -ne 0 || ! test -s "$root/$trial/summary.json"; then
      echo "$trial FAILED_NATIVE_RUN; requires audit" >> "$status"
      exit 5
    fi
    .venv/bin/python scripts/research_session.py record --root . --session "$session" --trial "$trial" --status completed --artifact "$root/$trial/summary.json" >> "$status" 2>&1 || exit 6
  done
else
  echo "500H_2PIP_REJECTED; skip 4pip and 6pip as explicitly instructed" >> "$status"
  for pips in 4 6; do
    trial="PORTFOLIO-500-${pips}PIP"
    artifact="docs/audit/mechanicalpremia_yen_squeeze_mt5atr_v4_500h${pips}pip_skipped_20261014.json"
    .venv/bin/python - "$session" "$trial" "$artifact" <<'PY'
import json,sys
from pathlib import Path
session,trial,artifact=sys.argv[1:]
Path(artifact).write_text(json.dumps({
"session_id":session,"trial_id":trial,"execution_status":"SKIPPED_NOT_RUN_BY_USER_DIRECTIVE",
"ledger_record_type":"failed_cli_record_with_skip_disposition",
"reason":"The registered 500h/2pip net PnL or daily Sharpe was nonpositive. User explicitly requested no 4/6 pip runs after a failed 2pip baseline.",
"historical_performance_observed":False,"partial_result_valid":False,
"scientific_verdict":"NOT_EVALUATED; no claim of economic loss at these cost settings"
},indent=2)+"\n")
PY
    .venv/bin/python scripts/research_session.py record --root . --session "$session" --trial "$trial" --status failed --artifact "$artifact" >> "$status" 2>&1 || exit 7
    echo "$trial SKIPPED_AND_RECORDED" >> "$status"
  done
fi
echo "500_COST_GATE_TERMINAL $(date -u +%FT%TZ)" >> "$status"
