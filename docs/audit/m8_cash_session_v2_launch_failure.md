# M8 cash-session v2 managed launch failure

The immutable v2 session passed its file audit and permit/feature-proof
preflight. Attempt `c0864648-5bfc-491a-a133-295a82d37a94` reserved the job
name `ml4t-m8-cash-pilot`, but its recorded launch command targeted
`scripts/run_m8_n8.py`, the extended-hours runner. That runner rejected the
cash attempt because its job name did not match. The tmux pane then exited.

The attempt ledger now records terminal `FAILED`. The v2 preregistered trial
record links `run_log/m8/n8/cash_session/results/c0864648-5bfc-491a-a133-295a82d37a94/launch_failure.json`.
The failure artifact states that the native engine did not start, no signals
or fills were produced, and the holdout was not accessed. This is a managed
launch failure, not a strategy outcome. Do not re-open v2. The corrected
runner command requires a new versioned freeze.
