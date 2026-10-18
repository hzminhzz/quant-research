# Country ETF calendar seasonality: October entry, April versus July exit

Candidate: `alvarez_global_country_etf_oct_jul_seasonality_v1`. **Status: THESIS_CAPTURED (descriptive only)**. No independent research, backtest or execution approval.

Primary source: Cesar Alvarez, **June 12, 2024**, *Sell in August and Go Away*: https://alvarezquanttrading.com/blog/sell-in-august-and-go-away/ . Read the public article sections **Rules**, **1997-2011 Results**, **2012-2023 Results**, and **Final Thoughts**. The 2019 Jay Kaeppel article is context only; not independently reviewed.

## SOURCE_FACT — original markets and rules
The author examined 17 country equity ETFs (EWA, EWC, EWD, EWG, EWH, EWI, EWJ, EWK, EWL, EWM, EWN, EWO, EWP, EWQ, EWS, EWU, EWW) plus SPY, **not** index futures or CFDs. For each ETF, buy at the last trading day's **close** of entry month X; sell at the last trading day's **close** after Y months. The author compared X=October, Y=6 (exit April) with X=October, Y=9 (exit July), buy-and-hold, and the hindsight-best month combination. Entry X=1..12 and holding Y=3,6,9 were searched in public tables (further 1..11 Y configurations mentioned for an inaccessible download). The article **does not** define ETF basket sizing.

## AUTHOR_REPORTED_UNVERIFIED — do not treat as ATS returns
For **1997–2011**, the author reports that April exit led the three displayed alternatives for 13 ETFs, July for 4, buy/hold for 1. For **2012–2023**, April led for 4, July for 12, buy/hold for 2. Reported platform: AmiBroker; data: Norgate. Neither original trade ledger nor spreadsheet was accessed, and **no local performance calculations were made**.

## LOCAL_INFERENCE — hypothesis and adverse evidence
The seasonal edge may depend on evolving bear-market duration, macro policy or changing cash-flow cycles. The author's Federal Reserve interpretation is **speculation**, not a proven causal mechanism. Calendar search across many months/holding periods, correlated country ETFs and split-window selection create substantial snooping risk. Same-close execution assumptions, ETF survivorship/inception and source-specific dividend conventions remain unverified. The earlier period favored the shorter April exit: direct contrary evidence to claims that July is universally optimal.

## ADAPTATION_PROPOSAL
NONE. Future researchers should retain exact source ETF/product and source timing; if later a full spec is approved, explicitly preregister the calendar variant, a comparator, earliest eligible executable fill, fees/impact and out-of-sample windows.

## UNKNOWN and source-fidelity boundaries
Exact opening/closing broker order mechanism, allocation sizing, cash between windows, fees, dividend adjustment, holiday exchange calendar, ETF inception/member filters and forward persistence are **UNKNOWN**. No synthetic values inserted.

## Future falsifier (NOT RUN)
A preregistered calendar rule has no stable after-cost advantage over corresponding buy/hold and alternate fixed seasonal controls, especially once market beta, ETF correlation and the original month grid are acknowledged.

**Descriptive portfolio tags (not measured):** risk driver: country equity seasonality, possible macro liquidity cycle; market: US-listed international equity ETFs; horizon: 6–9 calendar months; expected exposure: long equity/currency beta when invested; likely overlap cluster: equity calendar allocation and country ETF market beta.
