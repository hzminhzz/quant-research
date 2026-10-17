#!/bin/sh
set -u
ROOT=/home/quant/dev/quant/quant-research
BASE="$ROOT/run_log/one_bar_dukascopy_phase567_20261011"
mkdir -p "$BASE"
printf 'STARTED_AT=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$BASE/launcher_status.txt"
while tmux has-session -t ml4t-onebar-dukascopy-2013 2>/dev/null; do
  printf 'WAITING_FOR_CORRECTED_BASELINE=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$BASE/launcher_status.txt"
  sleep 15
done
printf 'BASELINE_TMUX_ENDED=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$BASE/launcher_status.txt"
if ! command -v codex >/dev/null 2>&1; then
  echo 'BLOCKED: codex executable missing' >> "$BASE/launcher_status.txt"
  echo 127 > "$BASE/codex_exit_code"
  exit 127
fi
printf 'PHASE567_AGENT_STARTED=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$BASE/launcher_status.txt"
codex exec --sandbox workspace-write 'Read and autonomously EXECUTE run_log/one_bar_dukascopy_phase567_20261011_mission.md end-to-end. The old corrected baseline should have finished; inspect and verify it first. Implement Phases 5/6/7 with actual native ML4T tests, independent audit, and durable artifacts. Preserve dirty work and protected holdout; do not only plan or stop for ordinary implementation issues.' > "$BASE/agent.log" 2>&1
rc=$?
printf '%s\n' "$rc" > "$BASE/codex_exit_code"
printf 'PHASE567_AGENT_EXITED=%s CODE=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$rc" >> "$BASE/launcher_status.txt"
exit "$rc"
