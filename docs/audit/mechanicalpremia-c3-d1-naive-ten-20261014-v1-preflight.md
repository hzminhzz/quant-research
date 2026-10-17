# Naive D1 ten-rule trial — initial validation checkpoint

**Session:** `mechanicalpremia-c3-d1-naive-ten-20261014-v1`  
**Status:** RUNNING in dedicated tmux `ml4t-c3-d1-naive-ten`. Independent terminal audit is in `ml4t-c3-d1-naive-audit`.  
**Research:** exploratory, retrospective, no unseen 2013–2026 YTD data and no permission for live orders.

## Snapshot preserved from previous promoted C3 baseline

- Risk budget: nominal account equity ×1%; H1 0.2336 and D1 0.7664 per sleeve, equal per-index subdivision for US500 and US100. Native position sizing, not a guaranteed stop.
- H1 ATR14/BB40, exact original trailing stop event-handler unchanged.
- D1 exit (percent-B>0.80) unchanged. Daily ML4T Engineer EMA100, ATR20, Bollinger(10,3) features unchanged.
- Decision after complete session, next-minute fill; US500 and US100 Dukascopy BID CFD price proxy, missing ASK spread, financing and actual CFD contract mapping.
- Cost 1x: 1bp commission and 2bps slippage per side; 2x in the four preregistered years 2021,2024,2025,2026.
- 10 entry rules predeclared before any result in `docs/plans/mechanicalpremia-c3-d1-naive-ten-20261014-v1.md`. All 2013–2026 YTD data already exposed due previous research: no new OOS.

## Independent causal source-parity evidence (2025)

C3 frozen baseline 2025 SOURCE-US2 versus trial N01-LV-PB35:
- Native fills: 224 rows each, **exact equal**.
- Native trades: 112 rows each, **exact equal**.
- Native daily equity: 312 rows each, **exact equal**.
- The loosened N01 percent-B cutoff did not create any incremental 2025 fills; the exact baseline equivalence verifies the copied native runner's accounting in the no-new-entry case.
- Targeted tests: 6/6 passed for 10 unique rules, frozen universe, source budget, time cutoff, preserved H1 and D1 exit, and null warmup gate.

**This parity proof is only the 2025 no-new-entry case.** It is not complete source MT5 broker-execution fidelity.

## Job and output paths

- `run_log/research_sessions/mechanicalpremia-c3-d1-naive-ten-20261014-v1/batch_log.jsonl` — append-only progress, terminal state and errors.
- `run_log/research_sessions/mechanicalpremia-c3-d1-naive-ten-20261014-v1/yearly_native/year=YYYY/<variant>/cost_Nx/` — fills, trades, daily equity, native summary.
- `docs/audit/mechanicalpremia-c3-d1-naive-ten-20261014-v1/scoreboard.md` and `scoreboard.json` — missing-aware report. Run `uv run python -m scripts.report_mechanicalpremia_c3_d1_naive_ten_20261014` to refresh read-only from actual native ledgers.
- `scripts/finalize_mechanicalpremia_c3_d1_naive_ten_20261014.py` — refuses to record completed trials unless all 180 actual cells reconcile.
- No promoted source file, prior trial artifact, original SessionSpec, branch HEAD or unrelated concurrent job changed.

**Expected total:** 140 year×rule native annual cells at 1x direct costs, 40 fixed cost2x cells. All must be verified; failures are not passes. Do not rank incomplete variants as complete.
