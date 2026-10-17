#!/bin/sh
set -u
cd /home/quant/dev/quant/quant-research || exit 1
mkdir -p run_log/one_bar_nq_percent_stop_20261012/logs
uv run --no-sync python scripts/run_one_bar_nq_percent_stop_yearly_20261012.py 2026 > run_log/one_bar_nq_percent_stop_20261012/logs/year_2026_priority.log 2>&1
rc=$?
printf '%s\n' "$rc" > run_log/one_bar_nq_percent_stop_20261012/logs/year_2026_priority.exit
if [ "$rc" -eq 0 ]; then cp run_log/one_bar_nq_percent_stop_20261012/by_year/2026/worker_summary.json run_log/one_bar_nq_percent_stop_20261012/by_year/2026/year_summary.json; fi
exit "$rc"