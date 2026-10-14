#!/usr/bin/env bash
set -uo pipefail
cd /home/quant/dev/quant/quant-research || exit 2
OUT=run_log/milkman_cfd_2015_2024_dev_extension_v1_retry1
LOG=run_log/milkman_cfd_2015_2024_dev_extension_v1_queue.log
echo "QUEUE_START $(date -u +%FT%TZ) HEAD=$(git rev-parse HEAD) BRANCH=$(git branch --show-current)" | tee -a "$LOG"
fail=0
for c in swing_golden_gate legends_buy_day legends_ema bilbo_box_v2; do
  for y in 2015 2016 2017 2018 2019 2020 2021 2022 2023 2024; do
    dir="$OUT/$c/$y"
    if test -f "$dir/report.json"; then
      echo "SKIP_VERIFIED $c $y" | tee -a "$LOG"
      continue
    fi
    if test -d "$dir"; then
      echo "BLOCKED_EXISTING_ATTEMPT $c $y" | tee -a "$LOG"
      fail=$((fail+1))
      continue
    fi
    echo "RUN_START $c $y $(date -u +%FT%TZ)" | tee -a "$LOG"
    if uv run --no-sync python -m scripts.run_milkman_extended_2015_2024 --case "$c" --year "$y" --out "$OUT" >> "$LOG" 2>&1; then
      echo "RUN_OK $c $y $(date -u +%FT%TZ)" | tee -a "$LOG"
    else
      echo "RUN_FAILED $c $y $(date -u +%FT%TZ)" | tee -a "$LOG"
      fail=$((fail+1))
    fi
  done
done
echo "QUEUE_FINISHED $(date -u +%FT%TZ) failures=$fail" | tee -a "$LOG"
exit "$((fail>0))"
