# Mission: package one-bar NQ 30m strategy under promote/

Execute fully; user asked to SAVE entire strategy, YAML, configs, backtests, source, tests, audits in a new promote folder. ChatGPT is research lead, Codex executor. No commit/push/live trading.

Repository /home/quant/dev/quant/quant-research. Read AGENTS.md, docs/research_sessions.md, current validations/reports, latest research spec. Inspect branch/HEAD/git status/upstream, tmux. Read relevant ML4T skills registry-system, production-readiness, strategy-workflow and applicable skills. Protect dirty concurrent work. Current tmux ml4t-onebar-practical-yearly-20261012 is actively running. Do not kill/modify/move its files or start duplicate work.

Create a reproducible COPY-ONLY research package at promote/one_bar_nq_30m/. This represents a saved research candidate, not LIVE APPROVED. Original published rules unchanged: 30m extended session, max/min prior 50 complete bars buy/sell stop OCO, exit immediately following 30m open, stop $1000/trade, max 2 entries/day, one illustrative E-mini NQ $20/pt contract, long+short, no added filters. The 1m historical 2013-Jul2026 source is Dukascopy USATECH.IDXUSD BID-only CFD/index proxy, not verified CME futures. Unknown intraminute ordering and native atomic OCO limitation. Prior positive historical results not validated executable CME edge.

Desired intuitive structure:
promote/one_bar_nq_30m/
  README.md (what, exact rules, reproducibility, status not-approved, latest evidence and caveats)
  strategy.yaml (frozen original rules; no extras)
  config/backtest.yaml (1m source, boundaries, engine, cost scenarios 0 and full tick + commission and spread sensitivity; illustrative contract mapping)
  config/research_status.yaml (explicit exploratory, live false, observed retrospective trial identities and known blockers)
  data/data_manifest.json (source pointer + SHA256/hash if available; never duplicate raw 3.88m row Parquet data)
  src/ (copy task-owned one_bar runners and remediation implementations; no python bytecode)
  tests/ (copy matching one_bar tests)
  backtests/{lse_2026,dukascopy_long_history,phase567,remediation,practical_yearly}/
    COMPLETE run specs, JSON metrics, trades.csv, fills.csv, daily_equity.csv, year summary, trial ledgers, tearsheets/PNG and useful files, with clear source run IDs
    practical_yearly: include only fully completed individual year artifacts based on explicit per-year summary and file stability. Current year results are active. Record active job and PENDING years; do not copy partial/actively-written year or overwrite it.
  audits/ (copies of relevant docs/audit/one_bar_* reports and independent reviews)
  provenance/manifest.json (SHA256 per copied file, canonical original relative path, timestamp and git HEAD, original external references for big logs/superseded directories and canonical market data)
  scripts/verify_package.py (validate required files/YAML, source references, hashes)
  scripts/refresh_completed_runs.py (safe opt-in refresh after annual experiment ends: copy newly complete years only, updates manifest, no move or delete, no writes to source run directories)
  STATUS.md or equivalent active annual job status.
Adjust structure if simpler and coherent; no deep clutter. Do not copy secrets, .env, or massive agent logs. All substantive completed backtest ledgers/code/audit must be accessible INSIDE the package, not merely pointers; big raw market dataset and running output stay canonical and only referenced. Existing source locations scripts/, tests/, docs/audit/, run_log/ MUST NOT be moved or deleted, since other agents depend on them. Prefer snapshots of immutable completed artifacts with copies and hash manifest, not symlink-only. Mark superseded runs (e.g. duplicate OCO pre-fix) as superseded in index and preserve original paths rather than bulk copying duplicate huge dirs.

Relevant existing files:
- scripts/run_one_bar_50breakout_20261011.py
- scripts/run_one_bar_dukascopy_2013_2026_20261011.py
- scripts/run_one_bar_dukascopy_phase567_20261011.py
- scripts/run_one_bar_execution_remediation_20261012.py
- scripts/run_one_bar_practical_1m_20261012.py
- scripts/run_one_bar_practical_yearly_20261012.py (active executor may edit; if uncertain only reference it until stable)
- matching tests/test_one_bar_* (only task-owned)
- docs/audit/one_bar_* reports
- run_log/one_bar_50breakout_20261011; run_log/one_bar_dukascopy_2013_2026_20261011; run_log/one_bar_dukascopy_phase567_20261011; run_log/one_bar_execution_remediation_20261012; run_log/one_bar_practical_1m_20261012 (running yearly).

Do not change research economics, strategy code outside package or run_log/validation_status.json. Preserve all past trial statuses and failed/inconclusive evidence without claiming unperformed backtest. Copy actual frozen YAML/JSON session config if present; new YAML strategy/config must be explicitly a description, not evidence a frozen research session existed. Clearly distinguish the previous historical +$166k proxy results from unfinished corrected annual run; never headline past profitable backtest as live verified. No protected holdout access. Optional package unit test for exact immutable rule contract.

Verify with execution: hash inventory, YAML parse (installed PyYAML if available), test package verification, git diff --check and scoped status. Report new path, structure, file count, storage, copied completed runs and active annual-year progress. Do not stage/commit/push without authorization. Continue until all package files genuinely on disk and validated.
