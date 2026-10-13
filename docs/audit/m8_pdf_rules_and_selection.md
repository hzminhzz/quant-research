# M8-B1 source review and candidate status

**Status:** `SPEC_INCOMPLETE`. **Observed:** 2026-10-13.

## Source evidence

A page-marked text extraction became available locally at
`run_log/m8/original_rulebook_extracted_pages.txt`. Its content is not included
in this repository. It identifies the source as
`Systematic_Breakout_and_Prop_Trading_Strategies_Rulebook(2).pdf`, 12 pages,
265,940 bytes, and reports PDF SHA-256
`b947c5aeaee61da3c8bf660b410b10bb25f5af74b53facc8f04d9a486658b526`.
The extraction itself has SHA-256
`a0ece8b0aad23b28d5041b308a8ed7aa00a75a255338d6c03b6b8c0d0dd6661a`.

The extraction explicitly says the PDF binary remained in the uploaded-file
system and only extracted text was transferred. The binary is not available in
the task worktree or searched local paths, so I cannot verify the reported PDF
hash or confirm that the extraction matches the named `(1).pdf` from the
mission. Page markers are present and usable as extraction references, but they
are not independently verified against the PDF bytes.

## One candidate examined

I selected the **Nesnidal LOD/HOD Index Bounce**, limited here to its long NQ
rule, as the one candidate to assess. The source extraction describes the rule
on pages 6–7 and gives a production EasyLanguage version on pages 11–12. The
local trial ledger and research artifacts contain no trial explicitly named
Nesnidal LOD/HOD or Flagship Index LOD. This candidate was selected from its
rule completeness and price-only entry concept, before inspecting any result
for this candidate.

The extracted rule says: 20-minute NQ bars; POI is the developing Low of Day;
space is `1.0 × ATR(40)` on 20-minute bars; place a next-bar buy stop at
`LowD(0) + space` between 08:30 and 15:00 America/Chicago; require daily
ADX(15) above 20 and entry-bar high above the daily open; allow at most one
trade per day; exit at session close. These are source-reported futures rules,
not a CFD strategy.

## Why the contract cannot be frozen

The extraction contains a material stop-loss conflict. Pages 6–7 describe the
stop as one tick below Low of Day and also show the formula
`(space × BigPointValue) + 10`. The page 11 code calls `SetStopLoss` with that
currency-risk formula; it does not place a stop one tick below Low of Day. The
source does not resolve which rule is intended. Choosing one would invent a
rule.

A CFD adaptation also needs verified broker point value, lot sizing, margin,
fees, spread/slippage, financing, and an executable session calendar. The
qualified NAS100 source is a Dukascopy CFD price series and does not provide
those broker terms. The original PDF bytes are also needed to verify the
source hash and extraction.

No B1 contract or frozen trial was created. No candidate performance was
inspected, and no strategy backtest was run. The next decisive inputs are the
original PDF binary and verified NAS100 CFD execution terms. Then an independent
review can resolve the source stop rule before freezing a CFD adaptation.

Issue [#31](https://github.com/hzminhzz/quant-research/issues/31) remains open.
