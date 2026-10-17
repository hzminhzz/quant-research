#!/usr/bin/env bash
# Frozen v4 experiment queue; ONLY ml4t-backtest runner controls fills and PnL.
set -u
cd /home/quant/dev/quant/quant-research || exit 2
root="run_log/mechanicalpremia_yen_squeeze_mt5atr_v4_20261014"
session="mechanicalpremia-yen-squeeze-mt5atr-v4-20261014"
while kill -0 3511537 2>/dev/null; do sleep 20; done
if ! test -f "$root/PORTFOLIO-20-2PIP/summary.json"; then
  echo "FIRST_TRIAL_FAILED_OR_INCOMPLETE $(date -u +%FT%TZ)" >> "$root/queue_status.log"
  exit 3
fi
.venv/bin/python scripts/research_session.py record --root . --session "$session" --trial PORTFOLIO-20-2PIP --status completed --artifact "$root/PORTFOLIO-20-2PIP/summary.json" >> "$root/queue_status.log" 2>&1
for pair in "20 4" "20 6" "500 2" "500 4" "500 6"; do
  set -- $pair
  trial="PORTFOLIO-${1}-${2}PIP"
  if test -f "$root/$trial/summary.json"; then
    echo "$trial EXISTS_SKIP" >> "$root/queue_status.log"
    continue
  fi
  echo "$trial START $(date -u +%FT%TZ)" >> "$root/queue_status.log"
  MPLCONFIGDIR=/tmp/yen-mt5-mpl XDG_CACHE_HOME=/tmp/yen-mt5-cache .venv/bin/python -m scripts.run_mechanicalpremia_yen_squeeze_mt5atr_v4_20261014 --lookback "$1" --pips "$2" > "$root/$trial.log" 2>&1
  rc=$?
  echo "$trial EXIT=$rc $(date -u +%FT%TZ)" >> "$root/queue_status.log"
  if test "$rc" -ne 0 || ! test -f "$root/$trial/summary.json"; then
    echo "$trial FAILED_STOP_FOR_DIAGNOSIS" >> "$root/queue_status.log"
    exit 4
  fi
  .venv/bin/python scripts/research_session.py record --root . --session "$session" --trial "$trial" --status completed --artifact "$root/$trial/summary.json" >> "$root/queue_status.log" 2>&1
done
echo "QUEUE_TERMINAL $(date -u +%FT%TZ)" >> "$root/queue_status.log"
