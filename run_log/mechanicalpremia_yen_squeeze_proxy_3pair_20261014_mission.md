# Autonomous three-pair continuation — Mechanical Premia Yen Squeeze broker-neutral

This is an independently frozen follow-on to the two-pair proxy research. The requested FULL original universe (USDJPY, GBPJPY, CADJPY) is now available for 2023-2024 and its new SessionSpecV1 is ALREADY INITIALIZED/FROZEN:
`config/research_sessions/mechanicalpremia_yen_squeeze_proxy_3pair_20261014.yaml`
`run_log/research_sessions/mechanicalpremia-yen-squeeze-proxy-3pair-20261014/frozen_spec.json`
Frozen SHA256 printed at initialization: 097c0fcaef1b49185f3c28b8617003f8e312b27f88ef503385484671779eebec.

Frozen 3-pair input identities:
USDJPY `data/processed/mechanicalpremia_yen_squeeze_mvp_20261014/USDJPY_2023_2024_1m.parquet`
GBPJPY `data/processed/mechanicalpremia_yen_squeeze_mvp_20261014/GBPJPY_2023_2024_1m.parquet`
CADJPY `data/processed/mechanicalpremia_yen_squeeze_proxy_20261014/CADJPY_2023_2024_1m.parquet` (745064 rows, sha dd68ea5fba40a3a229e665aa86db8f17d0e79f8fd032f4c29704abeabe9af590). Provenance manifest adjacent, UTC localized under an explicit unverified assumption. Do not touch upstream live downloader (PID earlier 2317144) or source files.
Pre-execution protocol: `docs/plans/mechanicalpremia_yen_squeeze_broker_neutral_proxy_20261014.md`.
Earlier audit: `docs/audit/mechanicalpremia_yen_squeeze_native_20261014.md`. Factual correction: `docs/audit/mechanicalpremia_yen_squeeze_cadjpy_process_correction_20261014.md`; the first 2-pair YAML incorrectly claims no active CADJPY downloader. Preserve this correction, don't mutate the frozen 2-pair spec.
NO 2025+ data access, no holdout use. No live orders, no custom loops for fills/equity/PnL, no custom feature math. Use native ml4t.engineer compute_features, native ml4t.backtest Engine with actual STOP, update, cancel and native FIXED slippage at frozen 2/4/6 pip rates. No homemade execution emulator.
At run time:
1. Verify current git status, HEAD, dirty and concurrent work, read applicable AGENTS.md, docs/research_sessions.md, frozen specs, full local ml4t skills, two-pair Codex implementation/tests, reports, logs, trial records. Preserve all unrelated changes. Do not pull/reset/clean/rebase/stash/commit/push.
2. Validate CADJPY staging dataset, UTC interpretation, year boundaries, gaps and feature clock, source manifest and hashes, native H1 ATR14 / Donchian 20 & 500, 100-ATR upper median. Explicitly label staging not upstream accepted. Verify native execution/cost gates first.
3. Adapt the earlier native 2-pair code to accept 3-pair data, shared native cash & 1%-per-trade risk; if modifying earlier new task-owned runner, ensure prior 2-pair results remain reproducible and tests pass. Prefer a new `scripts/mechanicalpremia_yen_squeeze_proxy_3pair_20261014.py` or config switch. Keep native engine broker orders/fills/cash only. Source is netting-ambiguous; count/report dual-trigger; source did not have OCO. Delayed first-minute protection is predeclared proxy approximation, must count and apply adverse native exit rule, no lookahead. Define fill clock carefully: if minute timestamp is OPEN, signal at hour boundary must NOT read current minute close, high or low for execution decisions.
4. Run the six FROZEN 3-pair portfolio trials:
PORTFOLIO-20-2PIP, PORTFOLIO-20-4PIP, PORTFOLIO-20-6PIP,
PORTFOLIO-500-2PIP, PORTFOLIO-500-4PIP, PORTFOLIO-500-6PIP.
No optimization, no parameter change after outcomes. Report native fills/trades/PnL, year and quarter, per-pair contribution, daily-equity Sharpe, Calmar, max DD, win rate, expectancy, 1x-3x cost stress, margin/rejections, possible ambiguity. Record all trial attempts, including failed/inconclusive via research_session.py CLI. Record `DATA-CADJPY-PROVENANCE`, `ENGINE-STOP-ORDER-AND-CASH-GATES`, `FEATURE-AND-CLOCK-PARITY`, `SINGLE-PAIR-ATTRIBUTION`, `ACCOUNTING-AND-GAP-AUDIT`. No unregistered historical search.
5. Run targeted pytest and independent source/engine accounting checks. If a routine failure, fix and rerun. If native Engine unsupported or scientific invalidity, record INCONCLUSIVE with exact evidence, no invented returns. Save report `docs/audit/mechanicalpremia_yen_squeeze_proxy_3pair_20261014.md` and artifacts under `run_log/research_sessions/mechanicalpremia-yen-squeeze-proxy-3pair-20261014/artifacts/`. Do not alter original 2023/24 snapshots or protected data. Include source code and config fingerprints.
6. Present outcome only after checking final HEAD/diff, frozen trial records, logs, tests, run data. Use REJECT/INCONCLUSIVE/EXPLORATORY-POSITIVE and differentiate assumptions; no promotion or live execution.

This continuation MUST use the same existing frozen 3-pair spec and distinct trial ledger. It should start only after the other worker in tmux ml4t-yen-proxy has finished, so do not duplicate edits or long runs. Work autonomously to completion or legitimate blocker; no new user action needed.
