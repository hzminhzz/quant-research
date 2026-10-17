#!/bin/sh
set -u
cd /home/quant/dev/quant/quant-research || exit 1
mkdir -p run_log/one_bar_tearsheet_20261012
codex exec --sandbox workspace-write 'Read and execute run_log/one_bar_tearsheet_20261012_frequency_fix.md completely: fix trading-session weekday Sharpe methodology, regenerate ML4T tearsheet, tests and package checksum verification. Do not change any native trading result or original research data, and do not commit/push.' > run_log/one_bar_tearsheet_20261012/frequency_fix_agent.log 2>&1
rc=$?
printf '%s\n' "$rc" > run_log/one_bar_tearsheet_20261012/frequency_fix_exit_code
exit "$rc"
