# Crypto source-only discovery, 2026-10-19 20:06 ICT

**AUTOMATION_FIRED.** Source-only intake; original checkout `main` and `origin/main` were both `ce4eaf588608002c57e96a3e1639233df2047068` at preflight, with clean original worktree. Baseline `research_inbox`: **112 directories**. This report's owner is isolated branch `research/crypto-thesis-source-20261019-2006` based on that commit; no main merge. Recheck remote publication separately before asserting it.

## Screening ledger: 20 distinct original-source ideas

Two captured; seven overlaps; eleven rejected/deferred. Source access indicates what was read, **not** independently audited backtests. Candidate overlap comparisons used main IDs and inspected peer research branches.

| # | Original material (source) | Decision | Specific basis |
|---|---|---|---|
| 1 | [Magner & Sanhueza, Bitcoin whale contagion (2025)](https://doi.org/10.1016/j.frl.2025.107906) | CAPTURED | BTC transfer event to 15-coin cross-market 6h/24h transmission; new information set; accessible abstract only. |
| 2 | [Keyrock, 16,000+ token unlocks](https://keyrock.com/from-locked-to-liquidity-what-16000-token-unlocks-teach-us/) | CAPTURED | Recipient type plus announced vesting event timing; source describes single-token guidance; basket is explicitly novel adaptation. |
| 3 | [Jia et al., seesaw cross predictability (2023)](https://doi.org/10.1016/j.jempfin.2023.101428) | DUPLICATE | `crypto_ml_jia_seesaw_rolling_lasso_2023_v1`. |
| 4 | [Ma et al., negative cross-chain spillovers (2026)](https://arxiv.org/abs/2602.23762) | DUPLICATE | `crypto_xs_crosschain_attention_substitution_20261018_v1`. |
| 5 | [Nakagawa & Sakemoto, low-anchored reversal (2025)](https://papers.ssrn.com/abstract=5001299) | DUPLICATE | `crypto_xs_low_anchor_reversal_nakagawa_20261018_v1`. |
| 6 | [Cakici et al., ML cross-section (2024)](https://doi.org/10.1016/j.irfa.2024.103244) | DUPLICATE | `crypto_ml_cakici_multicharacteristic_forecast_2024_v1`. |
| 7 | [Yang, direct ranking network (2025)](https://arxiv.org/abs/2512.08124) | DUPLICATE | `crypto_ml_yang_direct_rank_mlp_2025_v1`. |
| 8 | [Saef et al., tick co-jumps (2024)](https://doi.org/10.1007/s42521-024-00116-1) | DUPLICATE | `crypto_xs_cojump_clustering_saef_20261018_v1`. |
| 9 | [Animoca Brands Research, unlock event study (2025)](https://www.smartkarma.com/insights/the-impact-of-token-unlock-events-on-cryptocurrency-prices-an-empirical-analysis) | DUPLICATE | Shares unlock mechanism with #2; different 1%-circulating-supply threshold retained as related source, not second candidate. |
| 10 | [Baur & Hoang, correlations vs spillovers (2024)](https://link.springer.com/article/10.1007/s42521-023-00099-5) | REJECT_STANDALONE | High-value adverse/null evidence attached to #1, not positive trading rules. |
| 11 | [Bui & Nguyen, AdaptiveTrend (2026)](https://arxiv.org/abs/2602.11708) | REJECT_THIS_RUN | H6 (outside 1h target); manuscript claims 2022-24 OOS but figure narrative extends to Oct 2025, unresolved sampling/reporting discrepancy. |
| 12 | [Farag et al., crypto liquidity-provision reversal (2025)](https://doi.org/10.1016/j.jbankfin.2025.107411) | REJECT_THIS_RUN | Abstract does not establish source-exact multi-coin trade/clock; overlaps general reversal/liquidity. |
| 13 | [Alexander et al., central-exchange order flow (2024)](https://papers.ssrn.com/sol3/abstract_id=4867599) | REJECT_THIS_RUN | BTC market microstructure/cross-venue, no source-defined multi-coin tradable rule. |
| 14 | [Jing & Rocha, correlation network portfolios (2023)](https://arxiv.org/abs/2304.02362) | REJECT_THIS_RUN | Diversification/Markowitz selection, correlation mechanism largely already represented. |
| 15 | [Mensi et al., multiscale crypto spillovers (2024)](https://doi.org/10.1016/j.eap.2024.03.021) | REJECT_THIS_RUN | Descriptive hourly/daily wavelet connectedness; no source-established causal entry or alpha. |
| 16 | [Scharnowski & Shi, intraday herding and attention (2024)](https://ideas.repec.org/a/eee/beexfi/v41y2024ics2214635024000091.html) | REJECT_THIS_RUN | Descriptive cross-sectional attention pattern, no directional future-return/portfolio rule. |
| 17 | [Anderson, BTC–ADA tick lead-lag (2023)](https://doi.org/10.21511/imfi.20(1).2023.15) | REJECT_THIS_RUN | Ultra-high-frequency duration may be noncausal or untradable at 5m–1h. |
| 18 | [Chernoff, BTC/ETH price discovery ambiguity (2026)](https://www.mdpi.com/1911-8074/19/9/678) | REJECT_THIS_RUN | Measure-dependent price discovery, no robust ranked basket or side. |
| 19 | [Return and Volatility Forecasting Using On-Chain Flows (2024/25)](https://arxiv.org/abs/2411.06327) | REJECT_THIS_RUN | BTC/ETH directional event inputs; cross-sectional basket and data clock absent. |
| 20 | [Leong & Kwok, BTC spillovers to traditional assets (2025)](https://ideas.repec.org/a/bla/finrev/v60y2025i2p453-479.html) | REJECT_THIS_RUN | BTC-to-equities transmission, not a crypto multi-coin trade thesis. |

**Deep dives:** #1 (whale timing and adverse/null literature), #2 (source's individual-token advice versus proposed cross-coin adaptation), #11 (paper sample inconsistency). No thresholds, exchange symbols, perps, basket weights or source trading profits inferred without source evidence.

## Source admission and scientific boundary

- Flat **existing CLI smoke**: `.venv/bin/python scripts/quant.py validate-handoff research_inbox/hanna_spy_bear_gap_fade_us500_cfd_20261017_1600_v1` yielded `HANDOFF_VALID_UNVERIFIED`, evidence of envelope structure only.
- Both new sources are **nested source captures**, not executable full flat ATS handoffs. Validate using strict YAML duplicate-key/path/safe-load controls and SHA-256 readback before commit; report their hashes separately. Do **not** label either `HANDOFF_VALID_UNVERIFIED`.
- Source 1 is abstract-only (original full methods unavailable). Source 2 is Keyrock's commercially interested practitioner study with no public event-level replication. Funding, basis and carry are not strategy signals. Execution costs and any future financing must not be presumed zero.
- **Real research executions, Stage 1/2/3/4, IC, model training, protected reads, trial-ledger writes, orders and deployments: 0.**

**Next discovery frontier:** first-party source with explicit PIT unlock-calendar or whale-alert timestamps and full 1h cross-asset trading rules; independently inspect raw source and negative lead-lag literature before any later authorized protocol design.
