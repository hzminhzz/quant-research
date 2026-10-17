# USDJPY Gotobi Tokyo Fix — Phases 2–5 execution audit

Research session: `usdjpy_tokyo_fix_gotobi_engine_20261010_v1`  
Parent frozen thesis: `usdjpy_tokyo_fix_gotobi_20261010`  
Classification: **EXPLORATORY; NOT_APPROVED**  
Environment: `main` at `c095faa` (pre-existing dirty changes preserved)

## Evidence and implementation

- Development: UTC 2026-01-01 to 2026-09-01 exclusive; no September/October 2026 outcome analysis.
- Source: LSE canonical USDJPY 1-minute OHLCV, 246,806 rows; source SHA256 `5c6ff1bc3cff0a69e1bb22565249fd8dbe03441fb3363edb510c939841685028`.
- Tokyo holidays: verified against Bank of Japan 2026 calendar, https://www.boj.or.jp/en/about/outline/holi.htm.
- Minute continuity: 151 consecutive minute opens 08:00–10:30 JST required. 158 complete Tokyo business sessions included; 49 Gotobi sessions. 2026-06-05, 2026-07-29 and 2026-08-14 incomplete within the analysis interval; 2026-09-01 is a partial JST day at the UTC source boundary and is outside the intended JST analysis period.
- Features: `ml4t.engineer.compute_features` EMA50 and ATR20 are computed but do **not** gate either strategy. The `pre_ema50` and `pre_atr20` supplementary columns currently shift one selected 08:29 observation, rather than one raw 1-minute bar: previous-session context, not immediately previous-minute features. Do not use these columns for subsequent signal research without a corrected separately versioned artifact. This does not change calendar-only H1/H2 signals.
- Diagnostics: `ml4t.diagnostic.quantile_profile` calculated 5 quintiles (non-monotonic). HAC-adjusted event statistics are in `phase3/result.json`. Cross-sectional IC is not meaningful for a single-asset Gotobi flag.
- Phase 4: native `ml4t.backtest.Engine` with `ExecutionMode.NEXT_BAR`, `ExecutionPrice.OPEN`. H1 entry 08:30, exit 09:54 JST; H2 conditional entry 09:56, exit 10:30. All 106 orders across the two **costed** legs filled; additional 106 zero-cost control orders filled.
- Price and cost oracle: `independent_fill_oracle.json` compares exact order fill prices and expected position P&L. All four arms pass.
- Cost assumption: 0.5 pip per filled side, zero modeled commission; total 1.0 pip round-trip. This is illustrative and does **not** establish a broker-valid net return.
- Accounting: hypothetical JPY-quote cash account 1,000,000 JPY with position size 1,000 USD base units; neither percent returns nor native minute-bar Sharpe represent real USD-denominated FX account results.

## Results

| Test | Trades | Mean gross pips | Mean net pips | Total hypothetical P&L, JPY |
| --- | ---: | ---: | ---: | ---: |
| H1 pre-fix long | 49 | 3.08265 | 2.08265 | +1,020.50 |
| H2 conditional short | 4 | -4.025 | -5.025 | -201.00 |

H1 Gotobi minus ordinary-day gross drift = +5.4785 pips, HAC 95% CI [-3.1563, 14.1133]. **Significance criterion not met.** H2 = 4 trades; negative mean and insufficient evidence. **Neither strategy approved**.

## Ledger and validation

- `scripts/research_session.py check`: PASS, 0 declared-input issues; this is not proof of calendar completeness, cost validity, or strategy approval.
- `scripts/research_session.py report`: six continuation trials completed and artifact hashes match.
- `uv run python -m pytest -q tests/test_research_session_cli.py`: 12 passed, 6 third-party PendingDeprecationWarnings.
- Three implementation scripts compiled; `git diff --check` passed.
- No full suite, paper trading, native exchange/broker bid-ask replay, or holdout was executed.
- No commit or push was performed; unrelated existing working-tree changes were not modified.

## Decision

**NOT APPROVED.** The next research step is a separately frozen longer-horizon historical test with verified historical Tokyo bank calendar and broker spread data, preserving the already used development period and protecting the September–October 2026 holdout.
