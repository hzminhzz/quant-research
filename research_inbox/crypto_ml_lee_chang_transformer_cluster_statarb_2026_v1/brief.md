# Lee & Chang (2026): Learned clustering and transformer crypto futures statistical arbitrage

**SOURCE_CAPTURE_ONLY / THESIS_CAPTURED.** This is a source-described end-to-end portfolio mechanism, not a trained or executable ATS candidate. No local model, backtest, IC, holdout or broker action.

**Original record:** https://snu.elsevierpure.com/en/publications/an-end-to-end-deep-learning-model-for-clustering-based-statistica/ ; DOI: https://doi.org/10.1109/ACCESS.2026.3678064 ; *IEEE Access* 14 (2026), pp. 47301–47318. Authors: Hyunju Lee and Woojin Chang. Accessed university publication record and abstract 2026-10-18.

## Source-faithful mechanism
An end-to-end learner clusters statistically related cryptocurrency futures and uses a transformer encoder to capture temporal dependencies. Its optimization objective jointly affects pair/group selection **and trade allocation** for market-neutral statistical arbitrage. The authors report annualized Sharpe 2.516 after modeled costs and better results than their referenced benchmark strategies. These are **author claims, not local replicated returns**. The public abstract does not resolve frequency, contract identities, objective details, hedge weights, or source fees.

## Research interest and failure modes
Unlike the existing simple pairwise correlation basket, the experimental proposition is **learned joint asset grouping and trade policy**, not an alternative lookback on the same rank factor. A fair independent eventual comparison would freeze point-in-time clustering, model fit and OOF inference against deterministic rolling correlation/cointegration groups on identical contracts. Beware selection bias, group and label lookahead, simultaneous execution feasibility, net/gross exposure, costs and full-basket drawdown.

## ATS and prop constraints
The current ATS equal-weight long/short **scalar rank** interface does not faithfully represent this integrated allocation policy. Mark executable conversion **BLOCKED_PROTOCOL**, not 'five independent trades' or a fictitious forward-return forecast. Prop accounts might prohibit enough simultaneous futures shorts and hedges; exact allowed pairs, rollover/carry, margin and daily equity rules are unknown. **No funding-derived alpha** is proposed; real financing remains a cost if applicable.
