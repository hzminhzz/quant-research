# Hourly crypto source discovery — 2026-10-18, recovery batch 11

Status: SOURCE_CAPTURE_ONLY. No ATS research execution or runner inspection. One publication coordinator.

## Authority

Repository: hzminhzz/quant-research; source checkout /home/quant/dev/quant/quant-research.
Verified origin/main 37a6e5a5b21edd5d306f58914e454b0f097450cd, tree 3ba5aa1b0c0e65c5a0134356e549f42015849beb, 112 inbox directories. Local main 49c0d70f21518e0963780b6b3c93f0ec7afe93e0, clean and three commits ahead. Remote research/crypto-source-intake-20261018-1747 contains previously published Keel source at 1d3b05d8da14489c9edcdaf14acc5ccf08f7f7f1. The four listed below were absent from all inspected Git history before publication. Worktree isolated at origin/main with unrelated state preserved.

## Screen (22 original-source mechanism entries; 4 recovered, 8 overlapping, 10 deferred)

Each source below is author evidence only. Reported tests are AUTHOR_REPORTED_TEST_UNVERIFIED; no empirical outputs were read or computed locally.

| # | Mechanism and original source | Disposition |
|---|---|---|
| 1 | Bui & Nguyen, 6h trend + monthly per-coin Sharpe gate + 70/30: https://arxiv.org/html/2602.11708 | RECOVERED: author H6 Binance perps, not hourly |
| 2 | Garfinkel, Hsiao & Hu, abnormal turnover conditional on shorting restrictions: https://doi.org/10.1111/fima.12491 | RECOVERED: daily BTC-quoted spot research quintiles, NOT a tradable short basket |
| 3 | Guidolin & Ionta, monthly sort by past forecastability of weekly blockchain/attention factors: https://doi.org/10.1016/j.intfin.2026.102285 | RECOVERED: 40-coin long/short research, vintage data UNKNOWN |
| 4 | Shukla, Peyyala & Chakraborty, Granger out-strength directed return network: https://arxiv.org/abs/2606.25466 | RECOVERED: observational, no source-original trades |
| 5 | Wang & Kristoufek, chain gas fee predicts token illiquidity: https://econpapers.repec.org/paper/fauwpaper/wp2026_5f16.htm | DEFER: liquidity-monitoring relationship, no return-ranked trading rules |
| 6 | Zwydak et al., cross-exchange transaction-count complexity anomalies: https://arxiv.org/abs/2607.13916 | DEFER: market quality, not price return prediction |
| 7 | Easley, O'Hara, Yang & Zhang, own/cross Roll and VPIN microstructure effects: https://doi.org/10.1016/j.finmar.2026.101071 | DEFER: five-coin price discovery, not source basket |
| 8 | Shantanu Patil, adaptive reversal/momentum dollar-neutral optimizer: https://github.com/shantanupatil14/Crypto-Cross-Sectional-Statistical-Arbitrage | OVERLAP: composite reversal/momentum with existing families |
| 9 | Deng et al., liquidity quantile spillover crypto/DeFi/NFT: https://doi.org/10.1080/13504851.2023.2275651 | DEFER: connectedness, no portfolio entry/exit |
| 10 | Liu et al., midweek/weekend liquidity commonality: https://doi.org/10.1016/j.frl.2025.108187 | DEFER: seasonal liquidity monitoring, not executable alpha |
| 11 | Pindza & Mba, Hawkes/DCC contagion across 20 cryptocurrencies: https://link.springer.com/article/10.1007/s10690-026-09637-8 | DEFER: observational network, no original basket |
| 12 | Myeong & Kim, crypto-specific disclosure/announcement reaction: https://doi.org/10.1016/j.econlet.2025.112305 | DEFER: event study, PIT announcements and trade rules UNKNOWN |
| 13 | Cheah et al., fractional cointegration adjustment speeds for DeFi: https://doi.org/10.1002/fut.70055 | DEFER: no verified source trade/portfolio clock |
| 14 | Aoyagi & Ito, AMM versus LOB liquidity spillover: https://doi.org/10.1086/732831 | DEFER: theoretical market structure, not L/S crypto thesis |
| 15 | IliassSjm, 1h perps cross-sectional ML and rapid fee/latency decay: https://github.com/IliassSjm/crypto-perps-alpha | OVERLAP: prior hourly ML-source family; useful adverse economics |
| 16 | Brigida, hidden risk factors and relative token pricing: https://arxiv.org/abs/2601.07664 | OVERLAP: latent risk-factor family, no source-executable basket |
| 17 | Benedetti et al., quantile crypto/stablecoin-supply connectedness: https://doi.org/10.1016/j.iref.2026.104912 | DEFER: observational, causality and executable signal UNKNOWN |
| 18 | Pramesh, 25-coin momentum/reversal OOS/cost failures: https://github.com/prams2104/crypto-momentum-backtest | OVERLAP/ADVERSE: preexisting momentum and reversal families |
| 19 | matiasjarnal, BTC-regime-scaled cross-sectional momentum: https://github.com/matiasjarnal/crypto-momentum-strategy | OVERLAP: BTC-regime momentum family |
| 20 | aman3599, pairwise cointegrated z-score spreads: https://github.com/aman3599/crypto-stat-arb/blob/main/paper.md | OVERLAP: existing cointegration pair family |
| 21 | Divyasshree, CEX/DEX 1m price discovery: https://zenodo.org/records/17085264 | OVERLAP: price-transmission/lead-lag family, no basket rules |
| 22 | KASHAPP10, 6h dollar-neutral cross-sectional reversal with adverse costs: https://github.com/KASHAPP10/statistical-arbitrage-crypto | OVERLAP/ADVERSE: existing short-horizon reversal mechanism |

## Three deepened source checks

1. **AdaptiveTrend:** primary arXiv methodology confirms H6 momentum thresholds, monthly top-15 market-cap longs and bottom-K short set, per-asset in-prior-month Sharpe filter >=1.3/1.7, and 70/30 weights. SOURCE_FACT: algorithm opens at the same signal close; exact short stop and K short count remain UNKNOWN. AUTHOR_REPORTED_TEST_UNVERIFIED: Sharpe 2.41 / MDD -12.7%. Figure period conflicts with paper's stated OOS ending. Funding applies to modeled trading COST only, not signal.
2. **Abnormal turnover:** original Wiley paper confirms next-day negative high-minus-low return among constrained spot coins, and effect disappearance after margin activation. SOURCE_FACT: research spread is not an executable short-sale program. Derivative transfer may invalidate mechanism. Historical as-of circulating supply, volume units and short eligibility UNKNOWN.
3. **Past predictive accuracy ranking:** original Elsevier paper confirms monthly median split long 20/short 20 of 40 assets, separately over 8 forecasting predictors x 2 scoring approaches based on earlier OOS success. SOURCE_FACT: weekly factor forecasts, not 1h price strategy. Historical Google Trends and chain-data vintages, genuine shortability and financing UNKNOWN.

## Integrity

Original source instruments, horizons and portfolio rules were not converted or filled in. All four recovered descriptions were staged outside discoverable inbox, unique-key YAML parsed, identity/source HTTPS/status/non-funding claims checked, and SHA-256 read back before entering the isolated inbox. This nested descriptive validation grants THESIS_CAPTURED only; NOT HANDOFF_VALID_UNVERIFIED or executable approval. Each contains exactly thesis.yaml and brief.md. No native scientific CLI, stage, trial, runner queue, empirical diagnostics, holdout, protected source, deployment, account action or order was used.

Prop-firm crypto instrument eligibility, shorting, hedging, leverage, daily drawdown limits, financing and venue costs remain UNKNOWN. Next frontier: non-price PIT information sets only where an original source specifies usable causal trading rules; prioritize confirming publish state and the general-factory source corpus at next run.

Boundary: funding-alpha candidates=0; local backtests=0; ATS runner interactions=0; protected reads=0; orders=0.
