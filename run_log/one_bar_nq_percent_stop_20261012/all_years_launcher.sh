#!/bin/sh
set -u
cd /home/quant/dev/quant/quant-research || exit 1
mkdir -p run_log/one_bar_nq_percent_stop_20261012/logs
uv run --no-sync python scripts/run_one_bar_nq_percent_stop_20261012.py > run_log/one_bar_nq_percent_stop_20261012/logs/all_years.log 2>&1
rc=$?
printf '%s\n' "$rc" > run_log/one_bar_nq_percent_stop_20261012/logs/all_years.exit
exit "$rc"