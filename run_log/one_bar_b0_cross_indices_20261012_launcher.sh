#!/bin/sh
set -u
cd /home/quant/dev/quant/quant-research || exit 1
mkdir -p run_log/one_bar_b0_cross_indices_20261012
codex exec --sandbox workspace-write 'Read run_log/one_bar_b0_cross_indices_20261012_mission.md and execute full Phase1 registration + Phase2 data inventory/validation for B0 cross-index NIKKEI225,DAX,HSI,ES,NQ. Do NOT run native backtests or change promoted B0. Write frozen YAML, quality manifests, tests, audit, report evidence and blockers. Inspect relevant ML4T skills and git first.' > run_log/one_bar_b0_cross_indices_20261012/agent.log 2>&1
rc=$?
printf '%s\n' "$rc" > run_log/one_bar_b0_cross_indices_20261012/codex_exit_code
exit "$rc"