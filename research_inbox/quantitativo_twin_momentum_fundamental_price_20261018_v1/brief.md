# Twin price and fundamental momentum — descriptive source capture

Candidate: quantitativo_twin_momentum_fundamental_price_20261018_v1 — **THESIS_CAPTURED ONLY**. This is neither a complete ATS handoff nor an executable specification.

Primary practitioner source (Oct 18, 2026): https://www.quantitativo.com/p/less-wrong
Original research repository: https://ink.library.smu.edu.sg/lkcsb_research/5157/

## SOURCE_FACT: Source-described original signal
- Original product is **individual US common stocks**, monthly cross-sectional long/short sorting; NOT an index CFD or a perpetual contract.
- The accessible Quantitativo summary of Huang, Zhang and Zhou describes **12-to-1-month price momentum** combined with **fundamental-implied return (FIR)** built from quarterly accounting trends. It describes 28 transforms from seven accounting variables over 1/2/4/8 quarters.
- On last trading day of a month, separately quintile-sort on both signals. Long top-top intersection; short bottom-bottom intersection.
- The accessible public post does **not** list all seven fundamental variables or regression fitting details. Do not invent them.

## AUTHOR_REPORTED_UNVERIFIED: Performance and modifications
- The practitioner attributes **+1.81% per month (t=4.5)** to the research paper's combined academic strategy, not our evaluation.
- Quantitativo explored value weighting, volatility targeting and liquidity filters. The explicitly modeled **5 bps per side** is an illustrative cost assumption; stock borrow and harder-to-borrow short positions were not included.
- **Sharpe 1.15 belongs to a 50/50 mix with the S&P 500**, after the practitioner's modifications. It is **NOT** the standalone Twin Momentum Sharpe. The paper's sample ends in 2019 and code details are behind a paid section.
- Size/liquidity/adaptive portfolio choices and post-selection bias need independent review.

## LOCAL_INFERENCE and null
Slow processing of firm fundamental trends could create incremental drift alongside price momentum. Counterparty and causality are UNKNOWN. Null: twin intersection does not beat source-matched price-only and FIR-only alternatives after true PIT, borrow and trading costs.

## ADAPTATION_PROPOSAL
None. Keep the source's **US stocks**, monthly clock and long/short orientation. No conversion to CFDs/perpetuals. Proposed falsifier is future work only, not a completed test.

## UNKNOWN and blockers
Original seven variables, release vintages, regression-training chronology, PIT delistings, borrow cost, short availability, fill timing and portfolio weights. Month-end signal construction must not execute against the same already-known closing price without causal proof.

**Boundary:** Zero computed returns, no ML training, backtest, IC, protected holdout or broker actions. Source URLs do not imply scientific qualification.
