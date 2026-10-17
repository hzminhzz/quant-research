# Economic thesis discovery — 2026-10-15 10:00 ICT

**Candidate:** `dax_monthend_liquidity_rebound_cfd_20261015_v1`  
**Status:** `THESIS_READY_UNVERIFIED` — not frozen, not executable or live approved.  
**Previous candidates excluded:** European-opening S&P 500 return concentration; S&P 500 pre-FOMC overnight premium; AUD/USD policy-rate carry.

## A. Research brief

### Evidence basis

**VERIFIED — publication:** Etula, Rinne, Suominen and Vaittinen, *Dash for Cash: Monthly Market Impact of Institutional Liquidity Needs* (*Review of Financial Studies*, 2020), directly link institutional month-end cash needs and settlement conventions to temporary equity-price pressure and later return reversal. Their international table includes Germany's DAX, with an historical T+2 settlement regime. Most of the cited historical data end in 2013; the study does not provide an actionable Germany 40 CFD strategy or show profits after its specific broker fees. [Primary paper](https://doi.org/10.1093/rfs/hhz054).

**VERIFIED — official rules:** European securities settlement remains T+2 in 2026; the approved EU transition to T+1 is scheduled for 11 October 2027. Xetra's normal cash-equity session is 09:00–17:30 local Berlin time. Dukascopy lists a Germany 40 index CFD, `DEU.IDX/EUR`. [European Commission](https://finance.ec.europa.eu/news/commission-welcomes-political-agreement-increasing-efficiency-eu-capital-markets-thanks-shorter-2025-06-19_en); [Deutsche Börse](https://www.cashmarket.deutsche-boerse.com/cash-en/trading/trading-calendar-and-trading-hours); [Dukascopy](https://www.dukascopy.com/swiss/deutsch/cfd/range-of-markets/cfd-indices/).

**VERIFIED — inspected VPS documentation:** Current read-only checkout `/home/quant/dev/quant/quant-research` documents `index_minute_DAX` as a Dukascopy CFD-proxy minute series covering approximately 2018–2026 in `docs/DATA_CATALOG.md`. `AGENTS.md`, `docs/research_operations.md`, `docs/research_sessions.md`, `docs/architecture/market_scope_policy.md` and `config/research_contract_v1_example.yaml` were read. The checkout has substantial unrelated untracked work, which was preserved. The catalog is NOT fresh proof of usable quotes, actual venue mapping, or costs.

### Up to three mechanism candidates

| Idea | Who creates it / what behavior | Why it could persist / who pays | Regime and decisive falsifier | Decision |
|---|---|---|---|---|
| **DAX settlement-linked month-end rebound** | Institutions sell underlying equities before cash-payment deadlines; later purchase flows can relieve temporary pressure. **VERIFIED** for older international equity samples; current CFD persistence **HYPOTHESIS**. | Liquidity constrained funds/clients incur price pressure; capital providers warehouse equity risk. **INFERENCE** for 2018–2024 Germany CFD. | Weak if payment cycles change, macro risk dominates or broker financing absorbs it. Falsifier: no positive standalone net return and no positive paired advantage over an intramonth control. | **SELECT** |
| London 16:00 FX benchmark reversal | Benchmark clients demand USD; dealers alter inventory and pre-hedge. **VERIFIED** by Krohn, Mueller and Whelan (2024) and FCA evidence. | Benchmark customers pay for immediacy; dealers earn inventory compensation. | Fix-window spread/impact spikes. **Strong adverse evidence:** paper finds that a simple liquidity-demanding client-market trade loses after costs. | **REJECT for retail CFD** |
| London afternoon gold fixing information pressure | Informed flow shifts exchange-traded gold prices around historical fixing. **VERIFIED** in Caminschi and Heaney (2014), not current. | Liquidity takers/scheduled gold hedgers can pay informed market makers. | Old fixing regime, speed-sensitive execution and missing private order information. No defensible price-only direction after benchmark reforms. | **REJECT** |

The DAX thesis differs from breakout and technical mean reversion. Its input is an **ex-ante payment and settlement calendar**. It predicts a conditional return window, not a reaction to an indicator extreme. Historical stock and DAX findings may have been arbitraged away. McConnell and Xu (2006) also showed that simple mutual-fund net-flow explanations of turn-of-month returns were inadequate in their sample. That limits certainty about the exact causal channel, even if the calendar pattern exists.

### Selection criteria

| Criterion | DAX month-end | FX fixing | Gold fixing |
|---|---|---|---|
| Mechanism with primary evidence | Stronger: institutional trades, settlement and international DAX | Strong: dealer trades and inventory | Historical information flow only |
| Independent support | Published payment-cycle study + older month-end literature + EU T+2 rules | 2024 Journal of Finance + FCA | 2014 futures/ETF study |
| Canonical market-data plausibility | High: DAX 1m catalog; executable costs unknown | High: EUR/USD and GBP/USD 1m | Medium: XAUUSD ticks/1m, but auction info unavailable |
| Feature simplicity | Calendar only | Clock only | Would need order-flow/auction insight |
| Retail trading cost risk | Material: spread + several nights financing | **High; source explicitly warns negative net for customers** | **High; minutes and queue/access dependent** |
| Diversification | Institutional calendar flow; still long equity beta | FX market microstructure | Gold information flow |
| Main research risk | Old evidence and settlement-to-CFD transfer | Cost evidence already adverse | Historical regime change and source mismatch |
| MVP information gain / cost | Best of the three, conditional on broker-cost qualification | Low expected gain | Low expected gain |

**Selection:** One **new, unverified** DAX CFD calendar thesis. Do not interpret this as a found edge or a reproduction of historical paper results.

### One frozen-candidate MVP proposal

- **Instrument:** Dukascopy Germany 40 CFD `DEU.IDX/EUR`; canonical research proxy `index_minute_DAX`. Broker mapping, multiplier, quote side, trading hours, DAX price-vs-performance definition, and dividends are **UNKNOWN** pending source qualification.
- **T:** Last official Xetra cash trading session of the month in `Europe/Berlin`. This reference is distinct from the broker's OTC CFD market.
- **Candidate:** Long once per month. Calendar decision at **09:10 Berlin time on T**, market buy with first legal fill **09:11 or later**, and flatten on Xetra session **T+3** from a 17:10 decision with first legal sell fill **17:11 or later**. The next bar must have a genuine executable quote; do not shift to a favorable fill if missing. **Future quote completeness must never be an entry filter.** If a later exit quote is absent, mark the selected trade as data-invalid, report it, and block executable qualification rather than quietly discard losing cases.
- **Control:** Long from **T−10 09:11** to **T−7 17:11** for the same monthly anchor. Require the entry weekdays to match; otherwise drop the paired month. One candidate and one control, no parameter variants.
- **Size:** 1.0× initial EUR-account NAV notional, max one open position. Contract quantity and margin compliance must be verified. No stops, technical filters, leverage optimization, or shorting.
- **Costs:** Historical bid/ask, commissions, market-order slippage, overnight/weekend financing, and dividend cash adjustments. Current advertised rates are not valid historical substitutes. Mark broker-execution research **BLOCKED_DATA** until costs are qualified.
- **Development only:** 2018-01-01 through 2024-12-31, but only monthly anchors through 2024-11 to prevent any exit crossing the conservatively excluded January 2025 period. Adjust downward if a real protected project boundary is earlier. Data availability and ≥60 monthly paired events over ≥6 years remain unverified.
- **Economic null:** Mean paired candidate-minus-control net EUR return ≤0, or mean standalone candidate net return ≤0. **Primary metric:** mean monthly paired net return per initial notional; use a predeclared HAC lag 3 for 95% confidence interval. A positive gross price pattern without verified financing is not a pass.
- **Stopping:** `REJECT` for nonpositive mean net candidate or paired point estimate with valid sufficient sample. `INCONCLUSIVE` for insufficient events or positive estimates whose 95% lower paired bound ≤0. `BLOCKED_DATA` for missing executable-cost, source, DST/session, or contract-mapping proof. If both candidate net return and the lower 95% paired bound are positive, proceed only to *separately approved Validation*, not promotion.

### Stage 4: feature and engine architecture

`xetra_session_distance_to_monthend`, `xetra_local_signal_minute`, and `eligible_month_paired_windows` have exact definitions and parity tests in `thesis_candidate.yaml`. They are `EXTENSION_REQUIRED` calendar/time controls unless the installed ML4T scheduler provides a verified equivalent; no native feature API has been inspected or claimed verified. No technical indicator is required. A coding executor should prefer `ml4t.engineer.compute_features` for features if supported, and the native `ml4t.backtest.Strategy`/`Engine` for causal market orders. Do not introduce a custom backtest engine.

### Stage 6: adversarial assessment

1. **Historical mechanism may not persist:** The international cash-flow study largely ends in 2013. Evidence on Germany's modern index CFD is absent. The DAX 30-to-40 constituent expansion further changes comparability.
2. **Other explanations:** Traditional equity beta, general turn-of-month drift and macro clustering can produce similar returns. The control window tests generic same-duration exposure but does not perfectly match holiday financing.
3. **Settlement translation:** EU T+2 applies to underlying cash equities, not the CFD itself. The CFD can only inherit the effect through price tracking. A mapping failure invalidates the adaptation.
4. **Dividend accounting:** The commonly reported DAX is a performance index; the broker may quote or adjust the CFD differently. Unverified adjustment creates fake return.
5. **Timing:** Entry and exit require distinct decision and fill bars. Xetra holidays, DST and CFD breaks must be checked before counting trades. Missing bars cannot be forward-filled; later gaps cannot be used to decide earlier entries.
6. **Economic costs:** Holding across 3 Xetra session gaps can incur weekend or special-day broker financing; it can erase a small historical premium.
7. **Sample:** At most 83 monthly candidate anchors before data exclusions in the specified development period. If fewer than 60 valid independent pairs or <6 years, stop inconclusive. More sophisticated CIs do not create observations.
8. **Selection:** A published calendar pattern is not an unseen discovery. Protected holdouts must remain sealed. No tuning by month, volatility or relative strength.
9. **Portfolio overlap:** DAX long exposure may covary with existing index ORB and other equity beta. Independent portfolio value is unknown, and is not a prerequisite to the standalone MVP.

## C. Handoff — ChatGPT Web research lead

**Established:** This is an economic-calendar mechanism with primary paper evidence, direct inclusion of historical Germany DAX, an officially documented T+2 underlying settlement cycle, a listed Dukascopy CFD, and a likely local 1-minute price proxy. A single candidate-control rule set and falsifier are specified in the companion YAML. The relevant ML4T methodology skills reviewed were `ml4t-point-in-time`, `ml4t-calendar-ops`, `ml4t-lookahead-bias`, `ml4t-transaction-costs`, and `ml4t-compute-features`.

**Next, independently verify:** Current VPS catalog identity, whether the source is actual `DEU.IDX/EUR`, bar-open timestamps, monthly entry/exit quote completeness, historical Xetra and broker calendars, actual historical bid/ask and financing/dividend debit rules, broker contract multiplier, and available native ML4T scheduling and next-bar semantics. If these checks pass, a separate executor may register exactly one bounded MVP research session and implement it in native ML4T. If not, report `BLOCKED_DATA`; do not substitute hand-written simulation or fictional cost schedules.

**Trade-material open questions (must be resolved before executable testing):**

1. Is `index_minute_DAX` actually the Dukascopy `DEU.IDX/EUR` contract throughout 2018–2024, or only a vendor-relabelled proxy?
2. Does its underlying quote reference a price, gross-performance, or net-return DAX; how do CFD dividends and corporate actions adjust PnL?
3. Are timestamps truly UTC bar opens, and what is the exact earliest legal native next-bar fill at 09:10/17:10 signals?
4. Which Xetra sessions, historical holidays, early closes and CFD broker trading breaks apply at those times?
5. What historical bid/ask, market impact/slippage, commissions, financing (including weekend rollover) and effective dates are independently defensible?
6. What contract multipliers, minimum lot sizes, margin and lot step apply, and can a 1.0× notional risk target be represented without rounding materially changing exposure?
7. Does the repo protect any period before January 2025? If so, constrain development further; never read protected data to find out performance.
8. Can native ML4T scheduling produce these calendar events and next-bar fills without feature extension? If not, what is the smallest approved calendar-only extension?
9. How many independent complete month-pairs remain after rejecting missing broker quotes and price-source anomalies? Is the sample large enough?
10. Does existing DAX/index portfolio exposure make diversification potential low even if standalone net expectancy eventually qualifies?

**Authority boundary:** No repository files or research sessions were changed. No market-history data, holdout, optimizer, feature calculator, historical return evaluation, or trade was run. The recurring hourly automation must remain enabled after this iteration ends.

### Sources

- [Etula et al., *Dash for Cash* (2020)](https://doi.org/10.1093/rfs/hhz054)
- [McConnell and Xu, *Equity Returns at the Turn of the Month* (2006)](https://docs.lib.purdue.edu/ciberwp/43/)
- [European Commission, T+2 to T+1 transition (2025)](https://finance.ec.europa.eu/news/commission-welcomes-political-agreement-increasing-efficiency-eu-capital-markets-thanks-shorter-2025-06-19_en)
- [Deutsche Börse Xetra calendar](https://www.cashmarket.deutsche-boerse.com/cash-en/trading/trading-calendar-and-trading-hours)
- [Dukascopy Germany 40 CFD](https://www.dukascopy.com/swiss/deutsch/cfd/range-of-markets/cfd-indices/)
- [Krohn, Mueller and Whelan, *Foreign Exchange Fixings and Returns around the Clock* (2024)](https://doi.org/10.1111/jofi.13306)
- [FCA Occasional Paper 46, 4pm FX Fix](https://www.fca.org.uk/publications/occasional-papers/occasional-paper-no-46-fixing-fix-assessing-effectiveness-4pm-fix)
- [Caminschi and Heaney, London PM Gold Fix (2014)](https://doi.org/10.1002/fut.21636)
