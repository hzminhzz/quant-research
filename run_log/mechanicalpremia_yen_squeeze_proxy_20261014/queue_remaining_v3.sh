#!/usr/bin/env bash
# Task-owned sequential scheduler; calls only native ml4t-backtest runner.
set -u
cd /home/quant/dev/quant/quant-research || exit 2
dir="run_log/mechanicalpremia_yen_squeeze_proxy_20261014"
session="mechanicalpremia-yen-squeeze-proxy-20261014-v3"
mkdir -p "$dir"
while kill -0 2460557 2>/dev/null; do sleep 15; done
printf '%s\n' "First run PID finished; checking first native artifact." >> "$dir/v3_queue_status.log"
for spec in "20 4" "20 6" "500 2" "500 4" "500 6"; do
  set -- $spec
  lookback=$1
  pips=$2
  trial="PORTFOLIO-${lookback}-${pips}PIP"
  if test -f "$dir/$trial/summary.json"; then
    echo "$trial HAS_EXISTING_SUMMARY; skip duplicate" >> "$dir/v3_queue_status.log"
    continue
  fi
  echo "$trial START $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$dir/v3_queue_status.log"
  MPLCONFIGDIR=/tmp/yen-mpl XDG_CACHE_HOME=/tmp/yen-cache .venv/bin/python -m scripts.run_mechanicalpremia_yen_squeeze_proxy_20261014 --lookback "$lookback" --pips "$pips" > "$dir/$trial.log" 2>&1
  code=$?
  echo "$trial EXIT=$code $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$dir/v3_queue_status.log"
  if test "$code" -eq 0 && test -f "$dir/$trial/summary.json"; then
    .venv/bin/python scripts/research_session.py record --root . --session "$session" --trial "$trial" --status completed --artifact "$dir/$trial/summary.json" >> "$dir/v3_queue_status.log" 2>&1 || echo "$trial RECORD_FAILED" >> "$dir/v3_queue_status.log"
  else
    echo "$trial FAILURE_REQUIRES_AUDIT" >> "$dir/v3_queue_status.log"
  fi
done
echo "QUEUE_TERMINAL $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$dir/v3_queue_status.log"
