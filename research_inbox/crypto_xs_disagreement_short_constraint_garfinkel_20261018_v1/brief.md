# Short-sale-constrained disagreement and abnormal turnover

**Status:** THESIS_CAPTURED; SOURCE_CAPTURE_ONLY; not an executable strategy or claim of profitability.

**Primary source:** Jon A. Garfinkel, Lawrence Hsiao, Danqi Hu, *Disagreement and returns: The case of cryptocurrencies*, Financial Management (2025), first published January 9, 2025. https://doi.org/10.1111/fima.12491. Original publisher sections 2.1–2.2, 3.1/Table 2, margin-short-constraint evidence and conclusion.

**Original information set and rules:** Binance.com BTC-quoted spot pairs (not a perpetual universe), CoinAPI hourly source converted to UTC daily. Study 356 base assets across Aug 2018–Dec 2021 after minimum one-month listing and prior-month capitalization >= USD 1m; leverage tokens/missing volume excluded. DISAGREE is a daily coin-specific turnover z-like shock: today's base-unit spot volume / circulating supply, minus the previous 30-day mean, divided by the previous 30-day standard deviation. Every day rank by *yesterday's* DISAGREE into equal-weight quintiles, then compare following-day returns. Source shows Q5 minus Q1; this is not documentation of feasible short sales.

**Author findings — UNVERIFIED:** Table 2 shows Q5 minus Q1 following-day return -0.498% (Q1 0.542%, Q5 0.044%). After Binance margin shorting becomes available for a given coin, the conditional disagreement effect disappears. These are author research results, not independent after-cost/OOS/prop-firm returns.

**Important adverse implication:** The hypothesized alpha exists particularly where the allegedly overpriced coins cannot be shorted. Reversing Q5-Q1 into a long-Q1/short-Q5 basket would be a *distinct hypothetical adaptation*, not the paper's executable investment program. Spot-to-perp transfer is therefore doubtful without falsification.

**UNKNOWN / blockers:** as-of circulating supply, past market-cap vintages, delistings, historical BTC-quoted pair mapping, per-coin margin activation, short inventory, local derivatives eligibility, borrow/swaps, execution clock, costs, short/hedge permission and prop-firm daily loss rules. A causal universe cannot be replaced by survivors. Financing is a cost, NOT the alpha signal.

**Novel vs corpus:** dynamic short-sale constraint × standardized abnormal turnover is not the same as generic 1h volume rank, Amihud illiquidity or volume/volatility factors. No empirical simulation, no protected read, no orders.
