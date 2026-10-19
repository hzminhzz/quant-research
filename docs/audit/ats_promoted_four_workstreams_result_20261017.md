# Four promoted-strategy qualification results — 2026-10-17

Scope: research and simulated qualification only. No provider order, protected
market read, ATS7 observation-service change, account purchase, or live approval.
Historical 2026 observations remain exposed.

**Portfolio-level reconciliation:** The earlier four-strategy shared-capital development
experiment and 2013-2024 continuous native B0/C3 replays were subsequently
located and independently checked. They verify an exploratory diversification
result; see [portfolio evidence reconciliation](ats_promoted_portfolio_evidence_reconciliation_20261017.md).
The candidate execution blockers below must not be mistaken for a rejection
of portfolio risk reduction or a claim that no continuous B0/C3 replays exist.

Runtime used for native checks: `ml4t-backtest==0.1.7`,
`ml4t-diagnostic==0.1.6.post2`, `ml4t-engineer==0.1.4`,
`ml4t-data==0.1.0b14`, and `ml4t-live==0.1.2` from the existing locked
environment. Applicable installed ML4T skill instructions were reviewed from
`/home/quant/dev/quant/quant-research/.agents/skills/ml4t-*/SKILL.md`, including
`run-backtest`, `prop-firm-evaluation`, `continuous-futures`, `cost-model`,
`transaction-costs`, and `registry-system`. API signatures and frozen candidate
methodology records were also inspected. No new economic backtest was run.

## A — one_bar_nq_30m B0

**Terminal: `INCONCLUSIVE`; release bridge:
`BLOCKED_UNSUPPORTED_STOP_OCO_STRATEGY_FEED`.** Research promotion remains; live
approval remains `NOT_APPROVED`.

B0 is exactly the long/short prior-50-completed-30-minute-bar breakout, Chicago
17:00 extended session, intended OCO, one illustrative NQ-equivalent at $20/point,
fixed 50-point protective stop, next-30-minute-open exit, and two entries/session.
`config/promoted_qualification/one_bar_nq_30m.json` binds source bytes and records
the package's pre-existing README provenance mismatch rather than repairing it.

Historical evidence is Dukascopy `USATECH.IDX/USD` BID-only CFD/index proxy, not
CME NQ. Its 5,462 trades and modeled $166,107.92 net remain retrospective. One-
minute OHLC ambiguity, absent ask, non-atomic OCO, stop gaps, 98 delayed exits,
annual account resets, incomplete expected-minute coverage, and absent certified
account-wide marks prevent an account-survival claim.

`src/promoted_evidence.py` provides the smallest reusable boundary: exact,
timezone-aware, Decimal native account facts become ATS5 events; uncertain,
duplicate, mixed-source, and out-of-order facts fail closed. It neither computes
fills nor PnL and cannot certify coverage. Candidate fixtures prove Prague DST,
floating breach latching, exact fees/swap, missing coverage, uncertainty, duplicate
rejection, and source drift. Public FTMO terms provide neither an account agreement
nor shadow eligibility. ATS2 and ATS4 have no B0 operation/protocol; M8 is not B0.
ATS6 remains synthetic. ATS7 supports only its BTC `SyntheticCycle`; its broker
boundary rejects B0 STOP/OCO behavior.

Independent **source-hash-only** judge: PASS (not an independent account-path or
economic-outcome certification). Candidate/ATS5 tests: 23 passed before QA;
QA candidate tests: 7 passed. Cross-gate subset: 74 passed. ATS7 with
`PYTHONPATH=.:/home/quant/dev/trading-connector`: 34 passed, one dependency
deprecation warning.

## B — rsi_30_50_spy

**Terminal: `BLOCKED_EXTERNAL_DATA`; account replay: `INCONCLUSIVE`.** Frozen
strategy is RSI(5) below 30 with close above SMA(200), long-only 95% current
equity, next-daily-bar market entry, exit at RSI(5) at least 50. Creator variant
omitted a rising-MA predicate; no formula survives, so none was invented.

Name notwithstanding, tested data are Dukascopy `usa500idxusd` under repository
symbol ES: an index/CFD price proxy, not SPY ETF and not CME ES futures. Frozen
package verification passed 15 package files and six native artifact hashes.
Archival result remains 101 trades, Sharpe 0.7835938000318212, +101.55%, and
-10.48% max drawdown. It was selected from seven observed 2020–2022 trials;
2011–2026 is exposed and author trial count remains unknown.

`config/promoted_qualification/rsi_30_50_spy.json` freezes identity and explicitly
denies CME translation and pricing of adjusted continuous futures as contracts.
Four deterministic tests verify source/product mapping, omitted rising-MA rule,
archival metrics, selection count, roll/contract denial, and external blockers.
Independent source-hash judge: PASS.

No new backtest was valid: canonical price vault flags spread/carry as unknown and
not execution-qualified. CFD qualification needs effective-dated broker contract,
historical ask/spread, commission, directional swaps, dividend adjustments, lot/
tick/margin, dealing calendar, and exact fill clocks. SPY needs actual ETF prices
plus exclusive adjusted-price versus dividend-cash treatment. The requested CME ES adaptation remains a separately scoped and currently
unqualified product mapping. It requires dated contracts, a point-in-time roll
map, unadjusted execution prices, basis, sessions, margin, multiplier and costs.

## C — donchian_btc

**Terminal: `INCONCLUSIVE_MARGIN_LIQUIDATION_AND_EXACT_FUNDING`.** Source package
and signed funding-overlay identities pass the independent judge. Five candidate
tests pass.

Frozen candidate is Binance BTCUSDT perpetual on daily UTC bars: nine prior-close
Donchian channels, 60-day volatility, 25% target, 2× cap, next-bar native
rebalancing. Archive remains +208.18%, Sharpe 0.6826 under 252-day convention,
-25.07% max drawdown, 2,506 fills and 1,102 rebalance close records. These records
are not independent episodes; seven known selection trials and unknown author
trials remain declared.

The separately signed 2019–2024 funding repair is preserved, not rerun or upgraded:
cashflow is `-signed_position * settlement_or_proxy_mark * funding_rate`, using
position strictly before scheduled settlement. It contains 5,819 events, only
1,283 exact marks, 4,223 8-hour mark-close proxies, and 313 local perpetual-minute
proxies. Fixed-fill funding was -47,096.83 USDT; final-snapshot booked amount was
-47,090.99 USDT. This overlay does not feed funding into native sizing, future
fills, margin, or liquidation and says nothing exact about 2025–2026.

Native diagnostic API test confirms explicit 252 versus 365 annualization scaling.
A single half-target/half-cap scenario was frozen before any result, but remains
`NOT_EXECUTED` because no funding-integrated, liquidation-qualified engine path is
available. Linear drawdown rescaling cannot prove FTMO or account survival.

## D — mechanicalpremia_us500_us100

**Terminal decision: `RESTRUCTURE`; economic edge:
`INCONCLUSIVE_UNQUALIFIED_FRICTION_AND_NONCONTINUOUS_CAPITAL`.** Four candidate
tests and independent source judge pass.

Frozen comparison is H1 standalone, D1 standalone, and source-weighted C3 joint
(23.36% H1 / 76.64% D1) at modeled 1× and 1.5× costs. No sleeve or weight was
optimized. Archive retains 84/84 C3 native cells and 252/252 three-candidate
cells. H1 has 1,347 trades and PF near 1.06; D1 has 58 and PF near 8.07; C3 has
1,405. Modeled annual-reset C3 mean annual return is 2.99% at 1× and 2.07% at
1.5×. These annual runs reset capital, may end with positions, and cannot establish
continuous multi-year ROI. Standalone and joint sleeve quantities also differ. The 1.5× C3 archival
mean of annual Sharpe values is approximately 0.423; it is not a continuous
out-of-sample Sharpe.

Decision criterion was frozen before any new result: KEEP needs positive
continuous same-grid native C3 at qualified 1.5× plus source-justified spread,
carry and impact and positive incremental H1 contribution; RESTRUCTURE applies
where D1 may remain useful but H1 or friction is unresolved; SHELVE applies if
source-compliant continuous C3 is nonpositive at 1.5× or neither sleeve survives.
Current evidence therefore requires RESTRUCTURE, not retrospective H1 deletion.

Gross/commission/slippage exist only within archival native annual runs. Historical
ask/spread, directional financing, broker lot/point/margin terms and impact are
unavailable. CFD quote/tick volume was not relabeled ADV. Existing ATS4 M8 bridge
is strategy-specific and cannot admit C3. Correct next action is a new frozen,
continuous native same-grid source/cost qualification, not a hand-built PnL layer.

## Release verification and interpretation

The combined ATS2/4/5/6/7, dual-mode, managed-policy and candidate suite passed
**293 tests with 1 skipped** before the final intake-authorization hardening.
The final changed code was subsequently checked with **39 passing focused
candidate and ATS5 tests**. Ruff passed on all task-owned source and tests;
`git diff --cached --check` must also pass before commit. Full-repository Ruff
reported 695 existing violations in unrelated historical code, which were not
modified or treated as new regressions.

The independent outside-process judge in this work unit verifies **frozen
source hashes and producer source-identity receipts only**. It is not the ATS5
account-path oracle, ATS6 transactional acceptance judge, or ATS7 provider-paper
release judge. These four registrations cannot issue positive trading authority;
all provider-paper and live permissions remain denied. B0's historical source
package retains its separate pre-existing README-versus-manifest hash failure.

The four results are terminal *for this bounded qualification attempt*, not
full releases or economic rejections. Any new native backtest, funding-integrated
position sizing, contract translation, continuous portfolio simulation or real
shadow routing requires a new frozen scope with independently qualified inputs.
