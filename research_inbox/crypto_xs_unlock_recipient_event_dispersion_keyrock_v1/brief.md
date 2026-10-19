# Relative Token-Unlock Supply Pressure by Recipient Type

**Candidate:** `crypto_xs_unlock_recipient_event_dispersion_keyrock_v1`

**Status:** `THESIS_CAPTURED` (descriptive capture only, **not** backtested or executable).
**Original primary practitioner source:** Keyrock, [*From Locked to Liquidity: What 16,000+ Token Unlocks Teach Us*](https://keyrock.com/from-locked-to-liquidity-what-16000-token-unlocks-teach-us/). Exact publication date is **UNKNOWN** from accessible page.

## SOURCE_FACT and original source rules

Keyrock studies **more than 16,000 distinct unlock events involving 40 tokens**, measuring daily prices over 30 days *before and after* each event using ETH as a relative benchmark. It distinguishes cliff versus linear vesting and recipient classes (team, investors, public/community, ecosystem). Its article defines **medium 1–5%, large 5–10%, huge >10% of supply** as descriptive unlock-size categories; this does not specify a mechanical short rule. Keyrock *advises exiting a long exposure around 30 days before a major unlock and considering re-entry about 14 days after*. This is original single-token practitioner guidance, **not** a reported net-return trading system or cross-sectional portfolio.

## AUTHOR_REPORTED_TEST_UNVERIFIED

Keyrock reports ~90% of unlocks producing negative relative pressure, with **team** unlocks the most disruptive and **ecosystem development** comparatively favorable. The original raw event ledger, study code, quantitative standard errors, complete 40-token population and usable fill simulations have **not** been checked here. Firm expertise does not remove a possible marketing or selection incentive.

An independent but **non-identical** [Animoca Brands Research note, January 8, 2025](https://www.smartkarma.com/insights/the-impact-of-token-unlock-events-on-cryptocurrency-prices-an-empirical-analysis) also describes selling around large unlocks, but its **>1% of circulating supply** condition is not interchangeable with Keyrock's source categories.

## LOCAL_INFERENCE and separate ADAPTATION_PROPOSAL

Supply release anticipation and recipient hedging could drive **relative dispersion** between otherwise correlated coins. An independent future research proposal would compare eligible tokens with impending *publicly known team/cliff* releases against contemporaneously eligible coins with weaker unlock pressure or ecosystem releases. Constructing simultaneous longs/shorts is **not** the source's strategy. **Coin universe, long selection, short selection, weights, gross/net exposure, event windows, risk stops and 1h execution clock are UNKNOWN**. The source is daily and does **not** establish a 5m/15m/1h trading edge.

## Causal, risk and falsification requirements

The minimum viable future dataset is a **point-in-time publication-and-revision history** for each vesting schedule, event recipient and token supply denominator, combined with delisted token history and actual tradable venue contract identities. Perfect reconstructed event calendars would leak future amendments. Avoid hidden exposure to ETH/broad-market beta, overlapping recurring unlock events and thin-float price impact. Account for spot/perp fees, spreads, slippage, short availability and **actual financing** as costs; never use funding, carry or basis as signal variables.

**Falsifier:** An event-class-aware rank does not incrementally improve chronological after-cost relative returns against an event-blind benchmark using identical tradable coins and timing. No empirical analysis, protected reads or ATS execution was performed.
