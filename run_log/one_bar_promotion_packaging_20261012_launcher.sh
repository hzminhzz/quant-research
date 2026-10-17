#!/bin/sh
set -u
cd /home/quant/dev/quant/quant-research || exit 1
mkdir -p run_log/one_bar_promotion_packaging_20261012
codex exec --sandbox workspace-write 'Read run_log/one_bar_promotion_packaging_20261012_mission.md and EXECUTE it end-to-end. Build a reproducible promote/one_bar_nq_30m/ package with YAML, code, tests, completed backtest ledgers/audits, provenance and verification, preserve ongoing yearly runner. Review and verify output, no commits.' > run_log/one_bar_promotion_packaging_20261012/agent.log 2>&1
rc=$?
printf '%s\n' "$rc" > run_log/one_bar_promotion_packaging_20261012/exit_code
exit "$rc"
