# Research handoff — connors_alvarez_spy_qqq_double7_nextopen_v1

**Admission target:** THESIS_READY_UNVERIFIED / MVP_RESEARCH_DESIGN_ONLY. This is a descriptive practitioner-source replication design. It is NOT an executable CandidateSpec, a backtest, a source-performance verification, or trading authority.

## 1. Exact independent practitioner publication and provenance

**VERIFIED FACT — primary public source:** Cesar Alvarez, "Double 7's Strategy", **February 10, 2016**, https://alvarezquanttrading.com/blog/double-7s-strategy/ . The author describes the original Connors/Alvarez strategy from their 2008 book and his later 2016 portfolio re-test. The 2008 book itself was not accessed; the 2016 article is the exact primary source inspected for this handoff.

**VERIFIED FACT — context and disclosures:** Author FAQ, https://alvarezquanttrading.com/faq/ (undated live page). The author states that portfolio tests generally include a combined USD 0.01/share commission-and-slippage assumption, adjusted dividends/capital gains, a 3-month Treasury bill cash rate, and a survivorship-free source. **UNKNOWN:** the 2016 Double-7 post does not explicitly establish that these assumptions applied unchanged to each reported chart.

**VERIFIED FACT — adversarial related study, NOT a rule-exact replication:** Cesar Alvarez, "Mean Reversion Check Up 2022", **October 24, 2022**, https://alvarezquanttrading.com/blog/mean-reversion-check-up-2022/ . It tests Russell 3000 stock RSI2 signals, not ETF Double-7 signals. The author reports that short-term mean-reversion edges have diminished; do not attribute its annual statistics to Double-7.

Source access did not include the gated spreadsheet, original AmiBroker source, source trade ledger, paywalled book or original Norgate market dataset. No source code, strategy return, factor diagnostic, broker fill or market data was computed or accessed here.

## 2. Rules — distinguish 2008 ORIGINAL_AUTHOR_RULES from published 2016 SOURCE_TESTED_AUTHOR_REVISION

**ORIGINAL_AUTHOR_RULES (Connors/Alvarez, described retrospectively in 2016):** When the close is above its 200-day moving average and equals a 7-session *low of closes*, **buy on that same close**. Exit on a 7-session *high of closes* **at the same close**. The author calls this earlier approach a "points test." Same-close trading after observing the final close is noncausal without a separately qualified order protocol.

**SOURCE_TESTED_AUTHOR_REVISION (Alvarez's public 2016 SPY and QQQ portfolio retest):**
1. At the complete regular-session close t, require close[t] > arithmetic SMA200 of closing prices through t, and close[t] <= the minimum of close[t-6] through close[t]. The author explicitly confirms the *inclusive* low (his Method 1), not a strictly lower comparison.
2. **Buy the next session's open using 100% of available cash**. Run SPY and QQQ as separate single-ETF cases. There is no published instruction here to split the cash between two ETFs, substitute index futures, trade a CFD, or short the ETF.
3. While holding, at a session t where close[t] reaches a trailing 7-session HIGH of closes, **sell at the NEXT regular-session open**.
4. The public 2016 ETF rules specify no protective stop, short position, time stop, margin, or optimized exit. Treat a continuous drawdown while waiting for a rebound as genuine unbounded holding risk.

**Fidelity issue / SOURCE CONTRADICTION:** In a July 5, 2017 comment under the same primary article, Alvarez responds to a stop question with "There is no stop. You wait for a 7 day low to happen and then you exit." That conflicts with the article's repeated **HIGH** exit condition. Treat the published written BUY-low / SELL-high clauses as the source-tested candidate; label the comment an unresolved contradiction, possibly a typo but **not verified as such**. Independently resolve before rule-exact implementation. The high-of-closes equality convention is inferred symmetrically; confirm with the original source code when available.

**Excluded alternative from the same article:** A separate stock-selection study using constituents of S&P 500 or Nasdaq 100, index 200-day SMA, and 10%/position up to ten slots is NOT this ETF candidate. Historical constituent membership would become mandatory only for that **different** proposed family.

## 3. Published sample, evidence and adversarial record

| Evidence | Original test or stated finding | Status / limitations |
| --- | --- | --- |
| Early book version | First documented in a book published in early 2008; same-close points formulation | ORIGINAL SOURCE CLAIM; full original book/test not read |
| SPY & QQQ, 2000–2007 | The 2016 author re-ran his next-open portfolio rules, reporting outperformance over buy-and-hold and lower drawdown with about **26% exposure** | ORIGINAL SOURCE CLAIM; exact CAR/MDD values reside in image/spreadsheet and were not extracted or fabricated |
| SPY & QQQ, 2008–2015 | Both ETFs' reported CAR fell below buy-and-hold; SPY drawdown smaller, QQQ drawdown about as bad; the author identifies **one bad 2008 trade** as important | **Strong direct adverse source evidence**, not independent reproduction |
| Equity-stock variant, 2013–2015 | Returns only modestly above buy-and-hold; 2015 described as weak | DIFFERENT TEST; not evidence for ETF candidate |
| October 2022 stock-RSI2 follow-up | Author says broader short-term mean-reversion edges are shrinking | INDIRECT ADVERSARIAL CONTEXT; distinct rules and sample |
| After 2015 Double-7 | No exact public trade ledger, independently reproduced 2016–2026 ETF test, or source-rule-exact decay curve found in this bounded review | UNKNOWN, not evidence of recovery |

Author's own February 2016 conclusion suggests that the rule may be too simple and the historical edge may have little or no remaining value. Do not describe this candidate as alpha-positive, high Sharpe, or likely profitable. Avoid comparing a low-exposure strategy's raw CAR against continuously invested buy-and-hold without accounting for exposure, cash yield and risk.

The post reports trading-system test software AmiBroker and data provider Norgate Data. Attribution and interpretation remain SOURCE CLAIM; publication itself and exact printed rules were inspected. Trade count, full yearly losing periods, the five worst drawdowns, exact source cost debits, source code, and selection/parameter sweep count are **UNKNOWN** without the gated spreadsheet or original test artifacts. The source reports both inclusive and strict 7-low variants for stocks, but this candidate freezes the author's inclusive Method 1.

## 4. Scientific economic question, rival explanations, and null

**HYPOTHESIS:** In an otherwise persistent broad-market uptrend, unusually repeated lower closes may reflect transient forced selling and liquidity demand. A next-session entrant might earn a short-lived positive reversal.

**INFERENCE — likely counterparties:** Urgent sellers transferring short-term inventory/risk to dip-buyers. No direct order-flow evidence identifies them.

**Economic null:** Conditional signed returns after the 7-close-low event are no greater than eligible, same-clock, above-SMA200 non-event observations, once transaction frictions are included. Apparent lower drawdown can be a low-exposure cash-allocation effect, not an information edge.

**Adversarial alternatives:** structural edge decay following publication, parameter mining of lookback 7/200, rising ETF efficiency, exposure bias, volatility-regime confounding, overnight gap capture before an order is executable, one large crash-era losing episode, survivorship or adjustment errors, and understated opening slippage.

## 5. Signal and causality contract

- Original product is cash SPY/QQQ **ETFs**, independently examined. No CFD, leveraged ETF, index future, perpetual or replica instrument allowed by this handoff.
- Date t means one complete historical US-listed ETF regular session, with the ETF's effective-dated listing calendar. Local clock is **America/New_York** and raw timestamps must be UTC-aware. Historical DST, US exchange holidays and half-day open/close times are mandatory.
- Close[t] is available only after that session actually completes and the bar is received; 200-session SMA is the arithmetic average of close[t-199 ... t]. A seven-close minimum is min(close[t-6 ... t]); the entry uses <= inclusive. A seven-close maximum defines the intended exit threshold.
- **Decision:** after completed session t. **Earliest candidate buy or sell:** an eligible opening auction or realistically executable next-open order at the next trading session t+1, subject to source-verified quotes. Historical daily Open is a price reference, **not proof of executable fill**. The original 2008 same-close variant is not a legal shortcut.
- Close-price indicator histories, raw tradeable opening marks, split and distribution cashflows must be tracked separately; adjusted data cannot be treated as order-book quotes.
- Local decision for future implementation: no pyramiding and existing-position exit before a possible new entry on the same close. This is a labeled **LOCAL_ADAPTATION**, not an original author's stated edge. If it changes measured behavior, it requires versioning/re-admission.
- No missing-bar fill, retrospective adjustment, row-lag ambiguity, ineligible session or OHLC-based synthetic order execution.

## 6. Cost and product obligations

**ORIGINAL SOURCE CLAIM:** The general FAQ mentions USD 0.01/share combined commission and slippage for portfolio studies, as well as a cash T-bill rate and adjusted dividends. Whether these were used in the 2016 Double-7 charts is unverified.

**LOCAL_ADAPTATION for any later approved test:** Freeze ETF-specific opening buy-ask/sell-bid or confirmed auction-access assumptions, fee schedule, spread, market impact and fill slippage. Make dividend/distribution entitlement and cash yield explicit. No financing or crypto funding is assumed in an unlevered ETF/cash configuration. Do not double charge spread when quote-side fills already pay it. Stress normal opening spreads and crash-era gaps rather than using a generic CFD fee model.

**UNRESOLVED:** Verified raw/daily ETF bars; split/distribution handling; effective-dated venue listing and cash calendar; executable opening quote data; source chart gross-versus-net and trade counts; local ML4T API support. No claim is made that the VPS owns usable ETF data.

## 7. Predeclared Phase 3 protocol — DESIGN ONLY, NOT RUN

This is a **single-instrument event hypothesis replicated on SPY and QQQ separately**, not a cross-sectional alpha rank. Therefore cross-sectional Spearman IC is NOT_APPLICABLE.

**Primary diagnostic (LOCAL_ADAPTATION, not the author's test):**
- Freeze independent qualifying Double-7 event dates based on completed closes (above SMA200, inclusive 7-close low).
- For each event, measure its signed long return from the **next eligible open t+1** to the opening mark **three eligible trading sessions later t+4**; subtract identically time-anchored conservative costs.
- Compare against above-SMA200 non-Double-7 control sessions matched *ex ante* by calendar period and trailing realized volatility. Fix selection/matching and one 3-session horizon before reading results. Keep SPY/QQQ as two preregistered replications; do not pick the winning ETF.
- Handle overlapping events and serial dependence with preregistered event clustering and block/HAC-robust uncertainty. Report effective independent event count, sign/mean, distribution tails, conditional gap contribution, and effect sizes. Do not turn additional 1/5-day exploratory diagnostics into silent optimizations.
- **One primary falsifier:** incremental three-session net event return contrast is not convincingly > 0 versus the matched above-SMA200 non-event baseline at the preregistered one-sided 5% level, with sufficient sample power. Failure with adequate sample rejects the entry thesis; insufficient independent events or missing costs yields INCONCLUSIVE, not PASS.
- Chronologically isolate any source-publication periods from post-2015 development. Proposed future development 2016–2021 and later validation 2022–2025 are **not permissions** to inspect data. All project-protected partitions, including the currently protected 2026 boundary where applicable, remain sealed.
- If Phase 3 were separately authorized and adequate, the next *smallest* native ML4T simulation would model **dynamic 7-close-high exits and next-opening fills**. Fixed-horizon event diagnostic does not replicate variable-duration portfolio P&L or crash drawdown. Phase 4 is not run or authorized.

**Selection control:** Freeze exactly the 200/7 rules. The original 2008/2016 variants, stock variants, other known pullback systems, tie-rule alternatives and published source tuning constitute prior selection exposure; do not count this as a single virgin hypothesis.

## 8. Parity, admission decision and blockers

Proposed parity checks: 200 fully completed same-symbol closes; inclusive 7-low tie; symmetric 7-high and the July 2017 contradictory reply; t-close availability/next-session order; future-row invariance; dividend/split rollovers; 2008 gap tail; chronological event clusters; holiday, half-day and DST; raw opening marks versus hindsight-adjusted signal prices; author 2000–07 versus 2008–15 split. Actual features, data, Phase 3 metrics and engine paths are **NOT TESTED**.

**Research admission rationale:** This is a published exact-rule ETF strategy with concrete original retest years and exceptionally candid, negative post-2008 source evidence. It is suitable as a *strictly falsifiable negative-replication design*, not a performance endorsement. It is mechanically distinct from the existing S&P 500 monthly ROC x volatility rotation thesis; previously reviewed stock pullback/gap mean-reversion mechanisms are treated as related prior exploration, **not independent confirmation**. Existing research-inbox sources were inspected but unseen concurrent imports or archives may still duplicate the wider mean-reversion family.

**STOP before research execution:** lacking causally correct ETF bars/quotes, conflicting high-versus-low exit not resolved, no prospectively frozen costs, inadequate independent sample, failed source provenance, or disallowed access window.

**PUBLISHING STATUS:** A successful actual ATS handoff validator proves only the two-file structure and declared provenance. It does NOT prove these source claims, availability of real ETF data, test edge, backtest readiness or trading authorization.
