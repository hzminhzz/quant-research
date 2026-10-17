#!/bin/sh
set -u
cd /home/quant/dev/quant/quant-research || exit 1
mkdir -p run_log/one_bar_nq_stop_scaling_20261012/risk_comparison_20261012
codex exec --sandbox workspace-write 'Read run_log/one_bar_nq_stop_scaling_20261012_risk_metrics_mission.md and autonomously EXECUTE complete B0 vs B2 risk metric/Monte Carlo analysis, coding, tests and report. Focus winrate daily Sharpe Calmar risk-R quality Monte Carlo and whether undersizing explains PnL. Preserve promoted and prior research. Do not merely plan.' > run_log/one_bar_nq_stop_scaling_20261012/risk_comparison_20261012/agent.log 2>&1
rc=$?
printf '%s\n' "$rc" > run_log/one_bar_nq_stop_scaling_20261012/risk_comparison_20261012/exit_code
exit "$rc"
