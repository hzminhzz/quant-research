# Research inbox admission copy

Candidate: `us500_european_open_uncertainty_resolution_cfd_v1`.
Original source identifier: `us500_european_open_uncertainty_resolution_cfd_v1`.
Status: `THESIS_READY_UNVERIFIED`; `not_execution_approved: true`; `not_a_frozen_session: true`.
Selection family: `us500_european_open_uncertainty_resolution_cfd_v1` (assigned as the single-candidate family because the source did not specify a family ID).
This remains a descriptive research design. It is not an executable CandidateSpec, backtest result, or execution approval.


# Economic thesis discovery — research brief and handoff

**As of 15 October 2026. Status: THESIS_READY_UNVERIFIED, not execution-approved.**

**Preferred research question:** Does the historical S&P 500 futures return concentration around the European market opening survive when converted into an executable, long-only **USA500.IDX/USD CFD** four-hour schedule with verified broker costs? One matched prior-session control should distinguish the timing effect from merely holding US equity risk.

## A. Candidate comparison and evidence

### Candidate 1 — European-open US equity uncertainty resolution (SELECT)

- **VERIFIED:** Bondarenko and Muravyev (2023, *Journal of Financial and Quantitative Analysis*) document a historical E-mini S&P 500 return concentration around the four-hour European opening. The accompanying internet appendix explicitly defines **23:30–03:30 US Eastern time**. The paper ties the phenomenon to uncertainty processing when European investors arrive and reports evidence against the simpler dealer-inventory story. This is **futures evidence, not a claim about CFD returns**. The official Dukascopy market table lists **USA500.IDX/USD** and seasonal trading hours. Sources: [journal paper](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/market-return-around-the-clock-a-puzzle/089E33AC0B4D3B9A02CBA31EDF6505B3), [authors' appendix](https://static.cambridge.org/content/id/urn:cambridge.org:id:article:S0022109022000783/resource/name/S0022109022000783sup001.pdf), [Dukascopy trading hours](https://www.dukascopy.com/europe/english/cfd/range-of-markets/).
- **INFERENCE:** Institutional arrival times and time-zone separation may concentrate compensation for uncertainty into a recurring four-hour window. Institutional schedules could be slower to change than indicator patterns. Publication and greater competition may nonetheless eliminate it.
- **HYPOTHESIS:** Historical CFD net mean return is positive specifically in this window and greater than the equal-duration preceding evening window. Hypothesized counterparties paying are earlier risk-reducing sellers and investors demanding risk transfers as Europe opens; a precise transfer-based payer is **not independently established**.
- **Regimes:** Potentially supports an accumulated-uncertainty/risk-acceptance mechanism. Likely to fail in acute negative macro shocks, wider broker spreads, holiday/maintenance closures, structural arbitrage, or proxy mispricing. Europe/US DST mismatch weeks create clock tests, not tuning opportunities.
- **Uniqueness:** Fixed clock, unconditioned by price. Different from pre-existing ORB, breakout, RSI, and time-series momentum research, though still exposed to the S&P 500 long-equity factor.
- **Disproof:** After full CFD costs and real fill timing, EU hours do not beat paired preceding hours; target net mean is nonpositive; or the apparent edge is caused by bad timestamp handling, quotes, DST, or selective missing bars.
- **Feasibility:** Preferred by academic specificity and existing likely source data, **conditional** on actual overnight 1m coverage, broker-product mapping, and quote/commission evidence. The repository's `index_minute_ES` store was referenced by existing native audits. That does *not* verify it is the executable Dukascopy USA500 feed.

### Candidate 2 — Gold LBMA afternoon auction pressure/reversal (DO NOT RESEARCH YET)

- **VERIFIED:** LBMA and ICE report electronic London gold benchmark auctions at 10:30 and 15:00 UK time. Auction participants are real benchmark-sensitive buyers and sellers. Sources: [LBMA](https://www.lbma.org.uk/prices-and-data/about-lbma-daily-auction-prices) and [ICE](https://status.ice.com/iba/lbma-precious-metals).
- **INFERENCE:** Benchmark-linked dealers or clients can transact with urgency and temporarily affect nearby gold quotes. They could pay those able to warehouse inventory. This need not imply **any particular sign** of post-auction return.
- **HYPOTHESIS:** An as-yet-unspecified, directional short-horizon event premium exists on XAUUSD CFDs. Such a claim is not warranted from the existence of an auction alone.
- **Regimes:** Stronger on large index/benchmark flows and stress; weaker on low net imbalance days, liquid two-sided auctions, high spreads, and holidays.
- **Distinctness and falsifier:** Auction-flow/liquidity-transfer mechanism, rather than trend or reversion indicators. Reject if signed return is indistinguishable from same-clock nonauction controls and after-cost fills, or if identifying the direction requires unavailable live order imbalances.
- **Reason rejected for MVP:** Lacks a sourced deterministic direction, sufficient timestamped benchmark imbalance data, and demonstrated transfer to the CFD. Data cost and trial-design complexity are higher than candidate 1.

### Candidate 3 — Perpetual-futures positive-funding carry (DO NOT RESEARCH YET)

- **VERIFIED:** Funding is a contract cash transfer: on common designs, a positive funding rate makes longs pay shorts. Academic no-arbitrage work establishes funding's role anchoring perps to spot, not a promised excess PnL. Primary source: Ackerer, Hugonnier, and Jermann, *Perpetual Futures Pricing*, [SSRN](https://doi.org/10.2139/ssrn.4603820).
- **INFERENCE:** Leveraged directional demand can pay hedged liquidity providers; that payment is offset by basis movement, borrow, hedge execution, and counterparty/venue risk.
- **HYPOTHESIS:** A fully delta-hedged short-perp/long-spot spread yields positive net cash-flow PnL after full funding and hedge costs. The long-spot leg is outside the target CFD/perp-only execution preference unless separately authorized.
- **Regimes:** Better when speculative long demand drives persistently positive funding; fails when funding flips, basis converges against the entry, margin forces deleveraging, or hedge availability/costs deteriorate.
- **Distinctness and falsifier:** Carry paid through the funding mechanism, rather than price trend. Reject if fully hedged net carry is nonpositive with synchronously priced legs and complete capital charges.
- **Reason rejected for MVP:** Requires two-sided cross-market hedge data, funding timestamp reconstruction, broker/custody assumptions, and a different execution market. Existing repository research already includes `funding_extreme_reversal_mvp_20261011_v1.yaml`, creating thematic overlap (though a different rule).

**Qualitative selection:** Candidate 1 has the strongest independent academic mechanism-specific test (but only one author group), direct deterministic rules, no ML, a simple native event strategy, and likely available index-minute data. Its main weakness is transfer from a futures study to a broker CFD. Candidate 2 has clear events but no ex-ante signed signal. Candidate 3 has the clearest mechanical transfer but weaker portfolio-scope fit and much higher data/execution complexity. No candidate is accepted as profitable.

## Source and repository verification

**VERIFIED INSPECTIONS (current VPS checkout):** `AGENTS.md`; `docs/research_operations.md`; `docs/research_sessions.md`; `docs/architecture/market_scope_policy.md`; `config/research_contract_v1_example.yaml`; `run_log/validation_status.json`; `data/processed/_manifest.json`; `src/strategies/independent_seven_data.py`; `docs/audit/independent_five_full_history_20261014.md`; `docs/audit/independent_five_portfolio_20261014.md`; `config/research_sessions/structural_alpha_eow_6040_20261011.yaml`; `docs/audit/crypto_five_structural_phase12_20261011.md`; and relevant local ML4T skills. The checkout is dirty; nothing was modified.

**Existing prior research:** `docs/audit/independent_five_full_history_20261014.md` confirms a canonical ES/index CFD proxy store used in native testing. It does not establish a Dukascopy broker price, 23:30–03:30 quote completeness, or actual historical spreads. Several earlier ES mean-reversion/trend sleeves have evaluated overlapping development dates, so 2023–2025 can be labeled *retrospective development*, not unseen OOS. The repository documents protected dates in individual sessions and a more recent October 2026 holdout; these remain unopened. The LSE `SPX500_USD_15m_2017_2026.parquet` is **not** a proven overnight source because the manifest labels approximately 8.5-hour weekday sessions.

**UNKNOWN:** Current canonical store vendor contract, 1m quote spread, broker min-lot/multiplier/financing, exact historical holiday closures, and current native ML4T callback and `NEXT_BAR` behavior. These are explicit go/no-go checks, not small assumptions to conceal.

## Preferred candidate — executable CFD adaptation

**Frozen-for-review economic choice, not repository-frozen session:** Buy Dukascopy `USA500.IDX/USD` long at the earliest legal fill after 23:29–23:30 ET is complete. Exit at the earliest legal fill after 03:29–03:30 ET is complete. One trade per Sun–Thu US Eastern evening, flat otherwise. Compare against an independent shadow-book long at 19:30–23:30 ET on the same night. Both have the same capital, 1× maximum gross notional, zero additional filters, and two broker-side trades. Exact prices, lot size, slippage, cash financing and quote timestamps must be independently verified. Each position spans four hours. Do not pretend futures settlements or price proxy mid-bars are executable CFD fills.

**Clock:** Primary event is the source's fixed **New York** clock even during US/EU DST mismatch. Under verified 1m **bar-start** time semantics, the buy decision occurs when `[23:29,23:30)` completes, for a candidate fill no earlier than the 23:30 next-minute opening event. The exit decision uses the completed `[03:29,03:30)` minute and next opening event at 03:30. Matched control uses 19:29/19:30 and 23:29/23:30. If the installed native Engine cannot implement this exact event-ordering contract, **revise the draft before any research freeze**; never simulate an order at an already observed close.

**Feature implementation:** There are no technical indicators or statistical lookbacks. All five preliminary features are calendar eligibility and order-transition events. These require verified timezone/session state and an order callback adapter; classify them `EXTENSION_REQUIRED`, **not native verified**. Executable bid/ask pricing is `DATA_UNAVAILABLE` until independently qualified. `ml4t.engineer.compute_features` is preferred where it genuinely supports the feature contract, but do not force a fake indicator or invent a registry name. The native `ml4t.backtest.Strategy` and `Engine` handle execution only after installed capabilities are inspected. Full mathematical Boolean definitions, warmups, raw columns, and numerical/causal parity tests appear in `thesis_candidate.yaml`.

**One decisive development MVP:** Intended half-open UTC development window **2023-01-01 through 2026-01-01**; predeclare one paired candidate/control trial, with no optimization. Primary metric: paired-night mean of candidate four-hour **net** return minus control four-hour **net** return on equal capital. Estimate a 95% Newey–West/HAC interval with fixed lag 5 nights. Require at least **400 complete pairs covering two calendar years**. A positive candidate post-cost mean and a strictly positive lower 95% interval bound on paired excess justify **Validation research only**, not promotion. If qualified data show target net mean <= 0 or paired excess net mean <= 0, reject the executable thesis without changing its clock. Positive estimates whose interval includes zero are **INCONCLUSIVE**. Unverified source mapping/costs/calendar/engine cause **BLOCKED_DATA** or **BLOCKED_COST** before PnL trials. Primary scope has no holdout access.

**Adversarial concerns:** The academic pattern can be publication-selected, arbitraged away, an unhedged equity risk premium, or a futures-specific liquidity effect that cannot be earned through CFDs. The primary paper and its appendix are not independent replication studies. A nearby Asian window controls holding duration and directional beta imperfectly: US news, liquidity, and risk exposure can differ by clock time. Broker spreads may peak exactly when one must enter, and winning bar-close selection can disappear on actual ask/bid fills. DST, broker non-24h sessions, missing-minute conditioning, point-in-time symbol mapping, undocumented roll/continuous-price adjustments, margin, and financing are mandatory independent audit targets. Existing ES research can share substantial market-risk drawdowns even with weak unconditional signal correlation.

## C. Handoff to the ChatGPT Web research lead

**Established:** A historically documented and falsifiable ES futures anomaly has a deterministic four-hour clock, a plausible uncertainty-resolution mechanism, and an official Dukascopy CFD symbol that could provide an executable adaptation. Native ML4T should be sufficient for orders and ledgers if event clock, broker price, and cost semantics pass inspection. A complete, syntactically valid proposed contract is in `thesis_candidate.yaml`, with status `THESIS_READY_UNVERIFIED`. No session was frozen, no backtest/feature computation ran, and no history was read for this new candidate.

**Next independent work:** First verify canonical `index_minute_ES` source/vendor/symbol and the actual available `USA500.IDX/USD` historical quote data. Verify the 19:30, 23:30 and 03:30 ET paired 1m bars, DST and holiday coverage, trading size and actual spreads/costs. Inspect installed `ml4t.engineer.compute_features` registry and native `ml4t.backtest` callback/fill order from code; test deterministic event and quote fixtures. Only if all essential gates pass should the lead produce a *new* repository-compatible SessionSpec/ResearchContract/RunPermit, preregister one paired trial on authorized development history, and delegate its implementation and independent audit. Fail closed otherwise. Holdouts remain sealed and no live execution is authorized.

**Questions that could materially change trades:** (1) Is `index_minute_ES` true Dukascopy `USA500.IDX/USD`, another CFD, an ES futures reference, or an adjusted proxy? (2) Do raw timestamps mark opens/ends, and do minute OHLC reflect quotes or trades? (3) Are the as-of historical broker spreads, bid/ask quotes and effective costs sufficiently documented? (4) Are the 19:30, 23:30 and 03:30 events executable through every eligible overnight session and historical DST/holiday closure? (5) What are the broker lot multiplier, lot step, margin and commission/financing rules? (6) Do required source prices incorporate dividend or roll adjustments inconsistent with CFD cash PnL? (7) Can native ML4T truly submit after bar completion and fill at the next 1m opening event without a same-bar lookahead? (8) How must the runner handle known pre-entry closures versus *unexpected* future quote/data gaps? (9) Can the two shadow portfolios be independently accounted at simultaneous 23:30 control exit / candidate entry? (10) Does the requested cost/accounting methodology imply a separate cash financing charge or daily CFD rollover during the hold? (11) Has this exact clock already been tested elsewhere in the current local trial ledger, making the proposed development evaluation selection-contaminated? (12) Is there any user-declared protected holdout that overlaps 2023–2025? Do not alter a high-impact answer retroactively inside the frozen trial; update the draft **before** registering it.

## Migration notes and source material retained

The original YAML draft warning and CFD-versus-paper distinction are preserved in the thesis flags/rules. The source-only `approval`, `original_source_design`, and `session_calendar` declarations were moved into the required status fields, economic thesis, execution clock, and strategy rules.

These source-local references named files absent from this checkout. Their exact reference records are retained below as unconfirmed provenance; they are not represented as validated sources.

```yaml
- id: prior_return_history_warning
  kind: inspected_vps_repository
  local_path: docs/audit/independent_five_full_history_20261014.md
- id: prior_portfolio_drivers
  kind: inspected_vps_repository
  local_path: docs/audit/independent_five_portfolio_20261014.md
```

Source-only top-level metadata not represented by the handoff root schema is retained verbatim here:

```yaml
approval: NOT_APPROVED
```
