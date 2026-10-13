# M8 N8 freeze preflight correction — 2026-10-13

The immutable v1 session `m8_n8_dukascopy_nas100_cfd_30m_v1` was created with
frozen hash `9ef110c423b4d41d1be1a85eff0d1e4adb65e72778379541cf1b76e8bb8b9a1a`.
Its first actual `preflight_run` returned `BLOCKED / IDENTITY_DRIFT` before any
native outcome or attempt was created. The exact finding was that
`independent_audit.source_sha256` in `run_intent.json` named the implementation
source hash, while the permit contract requires this field to hash the linked
audit evidence file `run_log/m8/n8/audit_recipe.json`. The implementation hash
is retained inside that audit recipe.

The v1 frozen file and its inputs are preserved unchanged. A corrected v2
session uses a new intent with the audit evidence file hash and binds its
contract, runner, data, costs, multiplier, and audit recipe before any trial.
The same candidate, source bars, dates, holdout boundary, costs, strategy, and
single declared trial remain in force. No outcome was observed in v1, no data
preparation was repeated, no holdout data was read, and no worker or tmux job
was started.
