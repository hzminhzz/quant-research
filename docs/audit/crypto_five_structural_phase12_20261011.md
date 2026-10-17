# Five crypto structural alpha theses — Phase 1 and Phase 2 gate review

Date: 2026-10-11 (Asia/Bangkok). Repository: `/home/quant/dev/quant/quant-research`.
Inspected HEAD: `c095faab89835c49f4cd6fd66d1a9ed922709039` on `main`.
Classification: EXPLORATORY. Approval: NOT_APPROVED. This report is an input/gate audit, not a backtest, portfolio optimization, or certification of broker execution.

## Scope and operating rules

Requested Phase 1: falsifiable hypotheses, mechanism, baseline, instruments, trials, causal timing and kill criteria.
Requested Phase 2: existing local data discovery, provenance, point-in-time availability, missing-input and broker-cost feasibility. No strategy outcomes, holdout prices, or PnL were opened. No tests, factors, fitting, simulated orders, or live trades were run.

Read: `AGENTS.md`, `docs/research_sessions.md`, `run_log/validation_status.json`, and local installed skills `ml4t-strategy-workflow`, `ml4t-fetch-data`, `ml4t-validate-data`, `ml4t-define-universe`, `ml4t-point-in-time`, `ml4t-transaction-costs`, `ml4t-prop-firm-evaluation`. All relevant data-gate and methodology rules apply. Never use known or protected past tests as new OOS evidence. Preserve the dirty working tree, including existing runs and tmux processes.

Five schema-shaped **draft** declarations are under `config/research_sessions/crypto_structural_{s1,s2,s3,s4,s5}_phase12_20261011.yaml`. They are *not frozen/initialized*: Phase 2 revealed missing input identities. Freezing them now would create immutable blocked sessions. Do not initialize until each complete declared data/cost set is verified; use a new versioned session ID if a draft materially changes.

## Critical source-review findings

- S1 token-unlock pressure is plausible, but Cobie (2024) is qualitative; the supplied -60% to -85% annualized post-unlock performance is not verified. Keyrock reports a broad event-study association, not an executable beta-hedged short backtest. Keyrock also finds **team** unlocks more disruptive on average than **investor** unlocks. See https://cobie.substack.com/p/new-launches-part-1-private-capture and https://keyrock.com/from-locked-to-liquidity-what-16000-token-unlocks-teach-us/.
- S2 Tagus Oct 7, 2026 source is a general market newsletter and does not validate the quoted 62.4% win rate, 1.85 profit factor, or a mechanically profitable short signal: https://taguscapital.substack.com/p/tagus-bytes-071026. Liquidation trades can be buys as well as sells; reversals and continuations are competing outcomes.
- S3 Aperiodic describes a family of crypto cross-sectional factors, including 30-day momentum; it does not validate the exact supplied strategy Sharpe. The 2.39 Sharpe / 4.51 Sortino / 7.72% max DD quoted from Young and Calculated refer to the 1Token/Bybit industry **dollar-neutral category** (not this rule). https://blog.aperiodic.io/p/cross-sectional-alpha-factors-in and https://youngandcalculated.substack.com/p/the-alpha-isnt-where-you-think-it.
- S4 is **structurally invalid as a currently actionable Sunday CME reopening hypothesis**. CME announced and started 24/7 cryptocurrency futures/options trading May 29, 2026, with limited weekly maintenance. Former Friday-to-Sunday closure cannot be projected into current 2026 trading. https://www.cmegroup.com/media-room/press-releases/2026/6/01/cme_group_announceslaunchof247cryptocurrencyfuturesandoptionstra.html; https://www.cmegroup.com/notices/electronic-trading/2026/05/20260511.html.
- S5 Jump article establishes market-making and cross-venue activity but no 5–30m CEX overshoot and reversion strategy, IC=0.092 or 57.8% win rate: https://insights4vc.substack.com/p/inside-jump-crypto-13b-terra-trade. AMM arbitrage may pull DEX prices toward CEX, not CEX toward DEX.
- The five-strategy correlation matrix and combined drawdown numbers have no reproduced returns or covariance evidence. Mechanism diversity alone does not imply zero correlation, and stop-loss orders do not guarantee a daily loss ceiling.

## Phase 1 thesis register

### S1 — unlock pressure versus BTC (priority: evidence-led, blocked on calendar)
Economic payer: *hypothesized* unlocking recipients liquidate newly tradable supply; not all holders sell immediately. Some pressure can be anticipated.
Primary baseline: short an eligible token versus a time-matched matched-token control and a BTC-beta hedged null; compare event windows versus matched non-unlock dates.
Proposed first rule: eligible liquid Binance USD-M perpetuals (WLDUSDT, ARBUSDT, TIAUSDT; BTCUSDT hedge), pre-announced unlocks above 5% of then circulating supply; one fixed entry at event minus 7 calendar days; primary 7-day forward beta-hedged price return and separate pre/post event effects. Compare against zero-trade and non-event matched short baskets. This is a *registered candidate*, not a proven threshold.
Falsifier: no improvement over contemporaneous, liquidity-matched non-event controls after costs, or apparent effect exists only after unlocked amounts or calendars were revised; severe tail squeezes invalidate challenge feasibility.
Point-in-time rule: preserve schedule original publication and every revision; avoid backfilling later unlock revisions and current circulating supply into history. Beta estimation only prior to entry. No funding-income signal; charge signed payments and spreads.
Gate: BLOCKED. No versioned, timestamped TokenUnlocks calendar or point-in-time circulating-float records were verified in canonical store. Price and funding directories exist.

### S2 — post-pump forced deleveraging (priority: conditional)
Economic payer: hypothesized forced long liquidations under stressed conditions; opposing mechanism is short liquidation and continuation of a squeeze.
Primary baseline: short after a +35% trailing 24-hour surge without extra filters, plus no-trade; compare with matched pump-control events.
Proposed first rule: completed 15m bar below *causally computed* session VWAP after +35% 24h return; OHLCV-only variant is separately classified as a **different reduced hypothesis**; full thesis requires archived OI, liquidation side and taker imbalance **available by decision timestamp**. Entry next bar executable price, 4–18h descriptive horizon, max 24h.
Falsifier: negative or statistically inconclusive matched post-event expectancy after stress costs, missing liquidating-side support, or slip/short squeeze makes stop/risk unreliable.
Gate: BLOCKED for the full mechanism. Binance OHLCV exists and 1m flow exists for some tokens. No canonical historic OI or liquidation-event stores were found by catalog/directory inventory; no verified 15m causal joined feed was prepared.

### S3 — top/bottom liquid altcoin relative momentum (priority: first candidate for data-build)
Economic payer: hypothesized slow, sector-specific capital rotation and behavioral underreaction, but could instead be a high-beta/short-squeeze risk premium.
Primary baseline: equal-dollar long/short basket based on past 30-day returns, with no advanced model; no-trade, market-neutral randomized ranks, and sector/size controls.
Proposed rule: point-in-time eligible top 40 by *trailing 30-day USDT notional volume* (not current market capitalization); exclude BTC, stablecoins and non-crypto underlyings based on dated product evidence. Daily UTC ranking after complete prior bar. Long top quintile, short bottom quintile, equal gross notionals and cap leverage; next-open fills. Beta neutrality is an **empirical constraint**, not automatic from notional balance. Funding always charged.
Falsifier: no robust net factor spread on dated tradable universe, exposure explained by BTC/sector beta, or turnover drag exceeds spread.
Gate: INPUTS PARTIAL / PIT BLOCKED. There are extensive Binance 1h archives but dated historical eligibility/delisting status and broker-specific CFD symbol availability remain unresolved. No Phase 3 trial until these are addressed.

### S4 — Sunday CME reopening (priority: reject original live mechanism)
Economic payer in old regime: speculative weekend flows while CME futures were closed. Post-2026-05-29 there is no analogous broad weekly CME reopening; weekly maintenance is not a validated replacement.
Primary baseline: fixed-timestamp Sunday contrarian rule versus contemporaneous zero-trade and weekend trend continuation; only historical era prior to May 29, 2026.
Falsifier: no net pre-change matched event effect; **predeclared current-regime mechanism is already falsified by calendar change**. Do not trade or optimize an obsolete Sunday reopening proxy on 2026 June–Oct.
Gate: REJECT CURRENT PREMISE; optional historical-only event study. Needs actual CME open/close calendars and historical BTC/ETH minute data before any PnL claim.

### S5 — CEX/DEX causal dislocation (priority: low, dependent on new data)
Economic payer: hypothesized stale AMM quotes, inventory rebalancing and cross-venue adjustment. CEX itself may lead price discovery; DEX convergence need not create a profitable CEX reversion.
Primary baseline: CEX-only price burst/reversion and random timestamp matched bursts. Incremental predictive test uses *observed DEX minus CEX executable mid* before decision.
Proposed rule: ETHUSDT and SOLUSDT Binance USD-M only if timestamp-aligned on-chain AMM swaps/pool reserve states, fee tiers, gas/priority costs and CEX L1/book/trades are sourced. Test latency-adjusted 1–5m price response first; never infer on-chain state from later blocks.
Falsifier: DEX values add no causal predictive information beyond CEX-only baseline after cost/latency, or the predicted sign is wrong.
Gate: BLOCKED. CEX ETH tick/L2 and other high-frequency crypto data are locally available; no matched timestamped Uniswap/Raydium pool state history or reconstruction was found in scoped canonical inventory.

## Phase 2 evidence ledger (read-only inspection)

- Canonical store: `/home/quant/dev/quant/ml4t-data/.data/store/`.
- Confirmed existing store directory types: `crypto_futures_hourly_*` (~20 per-symbol folders), `crypto_futures_minute_*` (23 per-symbol folders), `crypto_futures_funding_*` (528 folders), and pooled Binance USD-M hourly archive `crypto_futures_ohlcv_1h_BINANCE_UM_PERP/`. Directory counts are inventory only, not current data-quality passes.
- `data/research_sessions/altcoin_momentum/inventory_audit.json` records 864 symbols and 15,382,059 hourly rows through 2026-09-30 after the documented archive extension. Crucial prior result: **zero date-qualified eligible contracts supported by full lifecycle evidence** at its audited early start; 130 preliminary price-eligible candidates do not establish point-in-time tradability. The adjacent experiment may have protected tests; avoid opening their outcomes.
- `run_log/fixed23_flow_repair_20261007.json` records a separate 23-symbol, 56,296,420-row Binance 1m source audit with no duplicates/null/invalid OHLC in that audit. Its BTC historic one-minute and PUMP 450-minute official gaps remain. Some taker-volume inconsistencies originate in vendor data. Eight of 23 tails end on Oct 7, fifteen on Oct 6; enforce common UTC intersection if used.
- `run_log/research_sessions/crypto_tsmom_flow_increment_20261008_v4/data_gate_report.json` records verified historical **BTC, ETH, SOL** complete hourly/flow sample through 2026-07-31 and event-aligned funding surrogate; it explicitly reserves observations since 2026-08-01 as prospective holdout for that session. **Do not reuse that window as a fresh holdout or open protected returns in this audit.**
- `data/processed/{btcusdt,ethusdt,solusdt,wldusdt,arbusdt,tiausdt,myxusdt}_1h.parquet` files were confirmed to exist by metadata. Existence is not quality assurance, nor proof of quote/settlement/contract identity.
- WLD, ARB, STRK, TIA and W Binance USD-M funding directories exist, but Phase 2 has **not** established exact funding settlement timing/mark series for each required instrument. This must be completed before a perpetual strategy PnL test.
- Catalog/directory search did not find canonical point-in-time token-unlock feed, standalone historical OI/liquidation stream, or CEX-aligned AMM history. Absence from the surveyed paths is **not** proof that no external source can provide them.
- Exchange/broker CFD/prop eligibility, per-symbol spreads, overnight financing, short constraints, news/weekend permissions and clock-based daily equity drawdown rules have NOT been verified. It is invalid to claim 100% CFD compatibility or guaranteed max risk.

## Chronological boundary and decision policy

Start with 2026-01-01 UTC and end initial *development* at 2026-08-01 00:00 UTC where data permit. This is exploratory and overlaps earlier research; no clean confirmatory inference from past-observed outcomes. Use after 2026-10-11 for a fresh future prospective test only if genuinely not accessed. For S4 the pre-CME-change design ends before 2026-05-29. No live/trial performance data analyzed in Phases 1–2.

Pre-register a single simplest rule per track. Every variant, feature, rule, cost stress, unmatched episode and failure must enter the trial ledger. Use native installed ML4T engineering/diagnostics/Engine for Phases 3–5; use independent leakage audit, matched event controls, realistic fills, full signed funding and portfolio-equity daily-loss checks. Do not read/tune protected holdouts. No free funding-income assumption. Never treat a 0.4% stop budget as an enforced 0.4% realized worst loss.

### Phase 2 disposition and next dependency

| Thesis | Mechanism | Existing price data | Missing critical data | Phase 2 status |
| --- | --- | --- | --- | --- |
| S1 Unlock | Plausible, Keyrock independent evidence | WLD/ARB/TIA/BTC | PIT unlock announcements/recipient/float; funding and broker map | BLOCKED |
| S2 Pump -> liquidation | Conditional, direction can reverse | OHLCV, selective 1m flow | Historical OI, side-labelled liquidations, full event timestamps | BLOCKED |
| S3 Relative momentum | Plausible, prior factor literature | Broad hourly Binance pool | Dated lifecycle/tradable universe; broker execution | PIT BLOCKED |
| S4 Sunday CME reopens | Broken since 2026-05-29 | BTC/ETH 1m and hourly | Historic real CME calendar for old-regime study | REJECT LIVE ORIGINAL |
| S5 CEX-DEX mean reversion | Unproved price-discovery direction | CEX tick/L2 on some assets | PIT DEX pool history, time sync, matched executable quotes | BLOCKED |

**Most efficient next action:** Complete S3 dated universe eligibility and cost metadata first, then run one fixed simple long/short 30-day momentum development diagnostic; in parallel source S1 timestamped unlock calendar. Keep S2 a conditional third track. Do not run S4 live or imply S5 is derivable from CEX-only 1-minute candles. Final portfolio correlation/risk analysis must wait until net, aligned independently validated strategy returns exist.
