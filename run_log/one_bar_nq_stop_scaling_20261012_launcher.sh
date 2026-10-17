#!/bin/sh
set -u
cd /home/quant/dev/quant/quant-research || exit 1
mkdir -p run_log/one_bar_nq_stop_scaling_20261012
codex exec --sandbox workspace-write 'Read and execute run_log/one_bar_nq_stop_scaling_20261012_mission.md completely. Preserve original promoted one-bar package unchanged and create verified frozen tar.gz/hash manifest, independent draft stop-scaling research YAML and proposal. Do not backtest, optimize, edit original, commit, push, or trade.' > run_log/one_bar_nq_stop_scaling_20261012/agent.log 2>&1
rc=$?
printf '%s\n' "$rc" > run_log/one_bar_nq_stop_scaling_20261012/exit_code
exit "$rc"
