#!/bin/sh
set -u
cd /home/quant/dev/quant/quant-research || exit 1
mkdir -p run_log/one_bar_2026_regime_20261012
codex exec --sandbox workspace-write 'Read and execute run_log/one_bar_2026_regime_20261012_mission.md end-to-end. Independently diagnose why 2026 lost -14166.96 on the fixed strategy, with ML4T Polars source/macro causal attribution. Create tested regime report and chart in promote/one_bar_nq_30m/reports/regime_2026/, preserve original files/holdout, no optimization or trading.' > run_log/one_bar_2026_regime_20261012/agent.log 2>&1
rc=$?
printf '%s\n' "$rc" > run_log/one_bar_2026_regime_20261012/exit_code
exit "$rc"
