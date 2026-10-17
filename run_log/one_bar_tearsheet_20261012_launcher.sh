#!/bin/sh
set -u
cd /home/quant/dev/quant/quant-research || exit 1
mkdir -p run_log/one_bar_tearsheet_20261012
codex exec --sandbox workspace-write 'Read run_log/one_bar_tearsheet_20261012_mission.md and EXECUTE the complete ML4T-tearsheet report generation now using verified annual ledgers and applicable ML4T skills. Save PNG Markdown CSV JSON inside promote/one_bar_nq_30m/reports/, verify aggregate stats and package SHA256 manifest, focused tests, no backtest rerun, no commits.' > run_log/one_bar_tearsheet_20261012/agent.log 2>&1
rc=$?
printf '%s\n' "$rc" > run_log/one_bar_tearsheet_20261012/exit_code
exit "$rc"
