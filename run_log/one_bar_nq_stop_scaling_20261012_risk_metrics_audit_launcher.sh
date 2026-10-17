#!/bin/sh
set -u
cd /home/quant/dev/quant/quant-research || exit 1
out=run_log/one_bar_nq_stop_scaling_20261012/risk_comparison_20261012
while tmux has-session -t '=ml4t-nq-b2-risk-mc-20261012' 2>/dev/null; do sleep 12; done
codex exec --sandbox workspace-write 'Read and EXECUTE run_log/one_bar_nq_stop_scaling_20261012_risk_metrics_audit_mission.md end-to-end. Mandatory: fix signed negative short quantities in 10-MNQ counterfactual AND abs quantity median, ensure counterfactual trade sign/winrate invariant, tests, regenerate output and independent final report; no strategies/backtests or original changes.' > "$out/audit_agent.log" 2>&1
rc=$?
printf '%s\n' "$rc" > "$out/audit_exit_code"
exit "$rc"
