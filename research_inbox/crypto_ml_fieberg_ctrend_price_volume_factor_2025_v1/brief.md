# CTREND: learned multi-horizon price/volume trend

**Status:** THESIS_CAPTURED only. Not trained, backtested, executable or approved.

## Original source

Fieberg, Liedtke, Poddig, Walker & Zaremba, *Journal of Financial and Quantitative Analysis* (published online 15 July 2025), `https://doi.org/10.1017/S0022109024000747`. The directly accessible Cambridge publisher abstract describes CTREND as a cryptocurrency cross-sectional factor aggregating price and volume signals over multiple time horizons using ML, tested on more than 3000 coins. The authors claim robustness in large and liquid names, across states and after transaction costs. **These are reported claims, not locally replicated evidence.**

## Why worth a distinct ML capture

Earlier inbox records cover standalone momentum, volume and anomaly baskets. CTREND's distinct research proposition is that a *learned combination of indicators across lookbacks* adds explanatory power over simple characteristics. A proposed portable form would rank liquid coins on a causally trained forecast and construct a frozen basket, but this is a **local adaptation**; the read abstract does not specify dollar-neutral long/short sizing.

## Blocking source gaps

The original indicator set, model type, target, training schedule, factor formula, decision clock, rebalance and trading rules were **not available in the inspected abstract**. Do not fabricate them or treat the source as ATS-executable. Obtain the full paper/code before any source replication. A LightGBM analogy is not a legitimate reproduction.

## Required research controls (future only)

Compare with one-horizon momentum and price-volume baselines on identical PIT liquid symbols. Use fold-local preprocessing and chronologically OOF prediction provenance; sampled prefix invariance does not establish model-fit causality. Validate financing/cost and full portfolio exposure separately. No funding-based signal.
