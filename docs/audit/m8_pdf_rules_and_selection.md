# M8-B1 source document and selection status

**Status:** `SOURCE_DOCUMENT_UNAVAILABLE`. **Observed:** 2026-10-13.

The mission names the source as
`Systematic_Breakout_and_Prop_Trading_Strategies_Rulebook(1).pdf` or
*Systematic Breakout & Prop Trading Strategies*. A filename search under
`/home/quant`, `/mnt/data`, `/tmp`, and the task worktree found no matching PDF.
No original bytes, PDF hash, or page citations are available in this checkout.

I did not use a prose recap as a substitute. I did not select or reconstruct a
strategy rule. I did not freeze a strategy contract or inspect performance
outcomes for a candidate.

M8-A identified a qualified historical price source for a possible future
price-only adaptation: Dukascopy `index_minute_NQ`, resolved from the NAS100
alias. This is a CFD series, not CME NQ futures. The source catalog does not
establish cash/extended session rules, broker spread, financing, point value,
lot size, or margin. These are additional execution inputs for B1/B3.

## Blocker

The exact missing input is the original PDF file. The next step is to place its
bytes in a user-reachable workspace path. Then record its SHA-256 and cite the
pages that define one executable price-only rule before freezing a separate
CFD session.

Issue [#31](https://github.com/hzminhzz/quant-research/issues/31) tracks B1.
The missing source blocks strategy selection, strategy-specific B2 feature
certification, and B3 backtesting. General feature plumbing is recorded
separately in [the capability report](m8_feature_capability.md).
