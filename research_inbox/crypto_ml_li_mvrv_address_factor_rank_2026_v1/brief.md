# Li et al. (2026): high-dimensional crypto return ranking

Candidate: crypto_ml_li_mvrv_address_factor_rank_2026_v1

Source: https://doi.org/10.1016/j.pacfin.2025.103033
Authors: Xingyi Li, Zhuang Liu, Yujun Liu, Shushang Zhu, Jingzhou Yan. Pacific-Basin Finance Journal 96 (2026), 103033.

SOURCE_FACT: the indexed abstract examines cryptocurrency cross-sectional return prediction with twelve models and long-only / long-short portfolio constructions. MVRV, new addresses, and active addresses feature prominently.

AUTHOR_TEST_UNVERIFIED: Random Forest is reported strongest for forecasting while a neural-network allocation has the highest cumulative portfolio returns. Neither has been independently reproduced. Original venue, universe, horizon, fill clock, fees, and OOF prediction bytes remain UNKNOWN in the accessible abstract.

LOCAL_INFERENCE: on-chain valuation-distance and address adoption may interact nonlinearly to change future relative returns.

PROPOSED_ADAPTATION: compare a shallow Random Forest against same-input Ridge regression and simple MVRV and past-return rankings; preserve the original multiasset portfolio family, not an invented source strategy.

REQUIRES_TRAINING_WORKFLOW and BLOCKED_DATA. Recover the full primary methods and causal availability of on-chain vintages, label endpoints, purged forward OOF splits, source portfolio construction, and executable cost benchmark. No model training, backtests, protected reads, runner interactions or orders.
