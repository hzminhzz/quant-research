#!/bin/sh
set -u
cd /home/quant/dev/quant/quant-research || exit 1
mkdir -p run_log/one_bar_2026_regime_20261012
while tmux has-session -t '=ml4t-onebar-2026-regime' 2>/dev/null; do sleep 12; done
codex exec --sandbox workspace-write 'Read run_log/one_bar_2026_regime_20261012_independent_fix.md and execute corrective audit end-to-end. MUST fix false 0 STOP exits based on raw signal label: map actual native EXIT fill order_type, correct Chicago RTH, fix bar feature release to next 30m open, add 50point stop vs pre-entry ATR analysis. Regenerate report/metrics/chart, tests, package integrity and independent review. No trading rerun or holdout, no commits.' > run_log/one_bar_2026_regime_20261012/fix_agent.log 2>&1
rc=$?
printf '%s\n' "$rc" > run_log/one_bar_2026_regime_20261012/fix_exit_code
exit "$rc"