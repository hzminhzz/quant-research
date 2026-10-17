#!/bin/sh
set -u
cd /home/quant/dev/quant/quant-research || exit 1
OUT=run_log/one_bar_practical_1m_20261012
mkdir -p "$OUT"
codex exec --sandbox workspace-write 'Read and EXECUTE run_log/one_bar_practical_1m_20261012_recovery_mission.md end-to-end. Recover failed monolithic backtest using annual native ML4T runs. Implement, test, run, audit complete source 2013-Jul2026 without custom simulator, no live or commit. Continue until complete or genuinely blocked.' > "$OUT/recovery_agent.log" 2>&1
rc=$?
printf '%s\n' "$rc" > "$OUT/recovery_exit_code"
exit "$rc"
