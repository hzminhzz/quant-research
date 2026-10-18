# Lebiedź & Ślepaczuk (2026): Recurrent PPO overlay for 1h crypto multi-pair statistical arbitrage

**SOURCE_CAPTURE_ONLY.** Original working paper: https://arxiv.org/abs/2606.04574 (2026-06-03). The original author HTML, including methodology and significance section, was directly inspected. None of its results was replicated.

## Source's actual mechanism
At monthly formation, eligible Binance USD-M futures are ranked from the preceding **two-month** history. The liquidity pool is the 100 most liquid assets; related pairs are ranked with cointegration and squared correlation. A deterministic Fixed Risk, Adaptive Mean spread-z-score system manages pair entries, stops, locks and time limits. A *recurrent PPO-LSTM actor* is overlaid to improve when permitted actions are taken, with hard risk shielding. The source uses **1h** signal close -> following open execution, 2024 training and 2025 OOS. Source reports 0.05% fees and tests a 0.10% friction proxy. The paper reports a block-bootstrap Sharpe difference **p≈0.0603**, significant at 10%, not 5%. Reported performance is intertwined with source OOS **10x leverage**, a major prop-firm mismatch.

## Why a distinct ML research question
This does not predict next coin return ranks. It learns stateful execution decisions *inside* a relative-value strategy. Fair independent evidence must compare the trained actor with the **same pair selection, deterministic spread baseline and fee model**, not an unrelated directional momentum rule.

## ATS and prop-fit blocks
The generic ATS equal-weight scalar cross-sectional IC/basket protocol is not this stateful recurrent pair execution; don't force it through that funnel or invent an executable CandidateSpec. Record **BLOCKED_PROTOCOL** for executable transfer. Future development would require a qualified path-dependent/event oracle for pair hedges, shared risk, trigger ordering, gaps, stop lock and portfolio netting. A firm may forbid high gross leverage, hedged legs or the stated multi-instrument count. Account rules and actual costs are UNKNOWN. **No funding-rate or basis/carry alpha** used.
