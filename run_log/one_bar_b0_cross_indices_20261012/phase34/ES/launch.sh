#!/bin/sh
set -u
cd /home/quant/dev/quant/quant-research || exit 1
uv run --no-sync python scripts/run_one_bar_cross_indices_native_20261012.py --symbol ES --batch > run_log/one_bar_b0_cross_indices_20261012/phase34/ES/batch.log 2>&1
rc=$?
printf '%s\n' "$rc" > run_log/one_bar_b0_cross_indices_20261012/phase34/ES/batch_exit_code
exit "$rc"
