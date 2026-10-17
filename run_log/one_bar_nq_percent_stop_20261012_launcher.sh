#!/bin/sh
set -u
cd /home/quant/dev/quant/quant-research || exit 1
mkdir -p run_log/one_bar_nq_percent_stop_20261012
codex exec --sandbox workspace-write 'Read run_log/one_bar_nq_percent_stop_20261012_mission.md and EXECUTE fully: original B0 unchanged except one fixed 0.34250680732279554% protective stop anchored to 2021 median price, one NQ no ATR/no MNQ sizing; implement, write tests, run native ML4T zero/cost full yearly historical comparison, audit and report. Preserve promote/original outputs; no live trades or commits.' > run_log/one_bar_nq_percent_stop_20261012/agent.log 2>&1
rc=$?
printf '%s\n' "$rc" > run_log/one_bar_nq_percent_stop_20261012/codex_exit_code
exit "$rc"