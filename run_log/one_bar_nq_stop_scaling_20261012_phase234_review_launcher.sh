#!/bin/sh
set -u
cd /home/quant/dev/quant/quant-research || exit 1
OUT=run_log/one_bar_nq_stop_scaling_20261012/phase234
while tmux has-session -t '=ml4t-onebar-b2-phase234' 2>/dev/null; do sleep 15; done
codex exec --sandbox workspace-write 'Read run_log/one_bar_nq_stop_scaling_20261012_phase234_independent_review_mission.md and execute complete independent verification: latest B0 baseline (5462 trades), MNQ 2019 listing, ATR/tick/risk/fill accounting and all 14 B2 annual native results; repair real errors, run tests and preserve original frozen promoted package, no new variants.' > "$OUT/review_agent.log" 2>&1
rc=$?
printf '%s\n' "$rc" > "$OUT/review_exit_code"
exit "$rc"
