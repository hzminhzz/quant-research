#!/bin/sh
set -u
cd /home/quant/dev/quant/quant-research || exit 1
mkdir -p run_log/one_bar_nq_stop_scaling_20261012/phase234
codex exec --sandbox workspace-write 'Read and EXECUTE end-to-end run_log/one_bar_nq_stop_scaling_20261012_phase234_mission.md. You own Phases 2 source and MNQ integrity, 3 causal ATR20 event study, 4 full 2013-Jul2026 native ML4T B2 ATR*1.5 MNQ integer fixed nominal $1000 risk simulation. Inspect repo/skills first. Implement, run, test, audit, repair failures; preserve frozen promote; do not merely plan.' > run_log/one_bar_nq_stop_scaling_20261012/phase234/agent.log 2>&1
rc=$?
printf '%s\n' "$rc" > run_log/one_bar_nq_stop_scaling_20261012/phase234/codex_exit_code
exit "$rc"
