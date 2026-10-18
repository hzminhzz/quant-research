# ATS Research Inbox Full Corpus Triage Audit — 2026-10-18

**Scope:** Non-executing structural qualification and scientific readiness triage pass across all 112 existing research inbox theses.

## 1. Executive Summary & Actionable Frontier

- **Total Inbox Theses Inspected:** 112
- **Admitted & Triaged:** 111 / 112
- **Structurally Blocked Handoffs:** 1 (`crypto_ml_fieberg_ctrend_price_volume_factor_2025_v1` — URL anchor mismatch between brief and thesis)
- **Unsupported Protocol Blockers:** 8 (All single-instrument event strategies; general single-instrument stop breakout execution is not a qualified ATS-4 factory protocol)
- **Descriptive Blockers (Specification / Data):** 103 (Descriptive research briefs without executable CandidateSpec or with unresolved data/parameter dependencies)
- **Actionable Frontier:** Cross-sectional theses with source-hash-bound local adaptations and qualified development data vaults (`crypto_xs_funding_velocity_dislocation_basket_v1`, `crypto_xs_90d_high_anchoring_basket_v1`).

## 2. Protocol & Status Census

| Scientific Protocol | Triage Status | Count | Description / Frontier Decision |
| :--- | :--- | :---: | :--- |
| `single_instrument_event` | `BLOCKED_PROTOCOL` | 8 | General single-instrument stop breakout execution is not qualified in native Engine; requires intrabar quote depth and gap adapter before Stage 3. |
| `nested_unqualified` (Cross-Sectional) | `BLOCKED_SPEC` | 62 | Descriptive academic/practitioner thesis; lacks executable entry/exit/allocation rules or declares contradictory parameters. |
| `nested_unqualified` (Cross-Sectional) | `BLOCKED_DATA` | 13 | Descriptive thesis; declared market data (e.g. orderbook depth, funding velocity, altcoin universe) not yet compiled into canonical development vault. |
| `flat_unqualified` (Cross-Sectional) | `BLOCKED_SPEC` | 28 | Flat descriptive handoff; unverified executable specification; requires source-bound adaptation before freezing. |
| `unknown` | `BLOCKED_HANDOFF` | 1 | DOI URL mismatch between `thesis.yaml` and `brief.md`; fails closed on provenance verification. |

## 3. Comprehensive Source-by-Source Triage Matrix

| # | Candidate ID | Format | Protocol | Status | Justified Next Action |
| :---: | :--- | :--- | :--- | :--- | :--- |
| 1 | `alvarez_january_losers_rebound_v1` | `flat_descriptive` | `flat_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 2 | `alvarez_sector_etf_middle_rank_1m_rotation_v1` | `flat_descriptive` | `flat_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 3 | `alvarez_sp500_hilo40_breadth_mr_gate_v1` | `flat_descriptive` | `flat_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 4 | `alvarez_sp500_ibs_filtered_oversold_v1` | `flat_descriptive` | `flat_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 5 | `audusd_policy_carry_cfd_v1` | `unknown` | `single_instrument_event` | `BLOCKED_PROTOCOL` | Qualify intrabar CFD stop adapter on ML4T Engine before Stage 3 |
| 6 | `bta_nq_monday_bb10_atr5_cfd_v1` | `unknown` | `single_instrument_event` | `BLOCKED_PROTOCOL` | Qualify intrabar CFD stop adapter on ML4T Engine before Stage 3 |
| 7 | `crypto_high_watermark_anchoring_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 8 | `crypto_liquidation_cascade_reversal_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 9 | `crypto_london_orb_breakout_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 10 | `crypto_ml_alessandretti_pooled_xgboost_2018_v1` | `flat_descriptive` | `flat_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 11 | `crypto_ml_anastasopoulos_world_orderflow_sgb_2026_v1` | `flat_descriptive` | `flat_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 12 | `crypto_ml_boyer_factorvae_cross_sectional_2026_v1` | `flat_descriptive` | `flat_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 13 | `crypto_ml_cakici_multicharacteristic_forecast_2024_v1` | `flat_descriptive` | `flat_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 14 | `crypto_ml_cengizmandros_hmm_rank_ensemble_v1` | `flat_descriptive` | `flat_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 15 | `crypto_ml_djienne_15m_btc_lgbm_hysteresis_2026_v1` | `flat_descriptive` | `flat_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 16 | `crypto_ml_fieberg_ctrend_price_volume_factor_2025_v1` | `unknown` | `unknown` | `BLOCKED_HANDOFF` | Reconcile brief DOI URL anchor with thesis source reference |
| 17 | `crypto_ml_hamza_cross_sectional_rs_meta_gate_2026_v1` | `flat_descriptive` | `flat_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 18 | `crypto_ml_jia_seesaw_rolling_lasso_2023_v1` | `flat_descriptive` | `flat_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 19 | `crypto_ml_kim_lim_tradability_gap_2026_v1` | `flat_descriptive` | `flat_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 20 | `crypto_ml_lebiedz_slepaczuk_recurrent_ppo_multipair_2026_v1` | `flat_descriptive` | `flat_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 21 | `crypto_ml_lee_chang_transformer_cluster_statarb_2026_v1` | `flat_descriptive` | `flat_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 22 | `crypto_ml_matthiola_xgbranker_20usdt_2026_v1` | `flat_descriptive` | `flat_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 23 | `crypto_ml_mingchelee_multicrypto_tft_onchain_2025_v1` | `flat_descriptive` | `flat_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 24 | `crypto_ml_ogwuche_garch_lstm_altseason_ethbtc_2025_v1` | `flat_descriptive` | `flat_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 25 | `crypto_ml_peng_cryptogat_price_graph_2026_v1` | `flat_descriptive` | `flat_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 26 | `crypto_ml_tsoku_dynamic_coint_dwe_pairs_2026_v1` | `flat_descriptive` | `flat_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 27 | `crypto_ml_yang_direct_rank_mlp_2025_v1` | `flat_descriptive` | `flat_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 28 | `crypto_ml_yicheng_hku_24h_decile_v1` | `flat_descriptive` | `flat_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 29 | `crypto_pairs_copula_stationary_spread_20261018_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_DATA` | Compile missing market data family into canonical development vault |
| 30 | `crypto_pairs_hurst_antipersistence_20261018_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_DATA` | Compile missing market data family into canonical development vault |
| 31 | `crypto_rolling_vwap_pullback_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 32 | `crypto_spot_perp_basis_dislocation_reversal_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 33 | `crypto_us_session_intraday_momentum_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 34 | `crypto_vol_managed_tsmom_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 35 | `crypto_volatility_compression_breakout_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 36 | `crypto_volume_anchored_drift_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 37 | `crypto_weekend_dislocation_reversal_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 38 | `crypto_xs_90d_high_anchoring_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Execute through inbox via bound adaptation `ats_crypto_xs_90d_high_anchoring_local_adaptation_20261018.yaml` |
| 39 | `crypto_xs_amihud_asymmetry_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 40 | `crypto_xs_amihud_illiquidity_premium_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 41 | `crypto_xs_betting_against_beta_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 42 | `crypto_xs_bipower_jump_variation_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 43 | `crypto_xs_btc_regime_momentum_arnal_20261018_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_DATA` | Compile missing market data family into canonical development vault |
| 44 | `crypto_xs_btc_residual_momentum_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 45 | `crypto_xs_capital_gain_overhang_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 46 | `crypto_xs_cojump_clustering_saef_20261018_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_DATA` | Compile missing market data family into canonical development vault |
| 47 | `crypto_xs_community_momentum_spillover_20261018_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_DATA` | Compile missing market data family into canonical development vault |
| 48 | `crypto_xs_corwin_schultz_spread_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 49 | `crypto_xs_crosschain_attention_substitution_20261018_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_DATA` | Compile missing market data family into canonical development vault |
| 50 | `crypto_xs_downside_correlation_asymmetry_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 51 | `crypto_xs_downside_risk_premium_zhang_20261018_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_DATA` | Compile missing market data family into canonical development vault |
| 52 | `crypto_xs_extreme_tail_beta_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 53 | `crypto_xs_funding_beta_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 54 | `crypto_xs_funding_carry_exhaustion_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 55 | `crypto_xs_funding_convexity_skew_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 56 | `crypto_xs_funding_innovation_shock_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 57 | `crypto_xs_funding_kurtosis_tail_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 58 | `crypto_xs_funding_memory_persistence_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 59 | `crypto_xs_funding_velocity_dislocation_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Execute through inbox via bound adaptation `ats_crypto_xs_funding_velocity_local_adaptation_20261018.yaml` |
| 60 | `crypto_xs_hill_tail_index_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 61 | `crypto_xs_idiosyncratic_volatility_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 62 | `crypto_xs_illiquidity_innovation_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 63 | `crypto_xs_information_delay_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 64 | `crypto_xs_information_discreteness_fip_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 65 | `crypto_xs_kyles_lambda_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 66 | `crypto_xs_liquidity_beta_lcapm_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 67 | `crypto_xs_liquidity_conditioned_weekly_trend_20261018_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_DATA` | Compile missing market data family into canonical development vault |
| 68 | `crypto_xs_liquidity_risk_return_interactions_20261018_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_DATA` | Compile missing market data family into canonical development vault |
| 69 | `crypto_xs_low_anchor_reversal_nakagawa_20261018_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_DATA` | Compile missing market data family into canonical development vault |
| 70 | `crypto_xs_max_return_salience_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 71 | `crypto_xs_momentum_lifecycle_turnover_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 72 | `crypto_xs_news_peer_opposite_shock_20261018_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_DATA` | Compile missing market data family into canonical development vault |
| 73 | `crypto_xs_pairwise_correlation_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 74 | `crypto_xs_quadratic_market_beta_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 75 | `crypto_xs_range_efficiency_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 76 | `crypto_xs_realized_kurtosis_tail_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 77 | `crypto_xs_realized_quarticity_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 78 | `crypto_xs_realized_semibeta_asymmetry_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 79 | `crypto_xs_realized_skewness_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 80 | `crypto_xs_relative_downside_beta_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 81 | `crypto_xs_return_synchronicity_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 82 | `crypto_xs_same_weekday_seasonality_20261018_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_DATA` | Compile missing market data family into canonical development vault |
| 83 | `crypto_xs_session_drift_divergence_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 84 | `crypto_xs_signed_jump_variation_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 85 | `crypto_xs_size_rmom_interaction_han_20261018_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_DATA` | Compile missing market data family into canonical development vault |
| 86 | `crypto_xs_stealth_trade_size_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 87 | `crypto_xs_systematic_cokurtosis_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 88 | `crypto_xs_systematic_coskewness_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 89 | `crypto_xs_systematic_jump_beta_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 90 | `crypto_xs_taker_flow_imbalance_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 91 | `crypto_xs_variance_ratio_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 92 | `crypto_xs_vol_of_vol_risk_premium_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 93 | `crypto_xs_volatility_asymmetry_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 94 | `crypto_xs_volatility_feedback_asymmetry_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 95 | `crypto_xs_volatility_of_liquidity_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 96 | `crypto_xs_volume_return_correlation_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 97 | `crypto_xs_volume_volatility_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 98 | `crypto_xs_vpin_adverse_selection_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 99 | `crypto_xs_vwap_tracking_error_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 100 | `crypto_xs_wick_asymmetry_basket_v1` | `nested_descriptive` | `nested_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 101 | `dax_monthend_liquidity_rebound_cfd_20261015_v1` | `unknown` | `single_instrument_event` | `BLOCKED_PROTOCOL` | Qualify intrabar CFD stop adapter on ML4T Engine before Stage 3 |
| 102 | `etf_ml_areeb_crosssector_lgbm_direction_2026_v1` | `flat_descriptive` | `flat_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 103 | `fomc_overnight_uncertainty_premium_us500_cfd_20261015_v1` | `unknown` | `single_instrument_event` | `BLOCKED_PROTOCOL` | Qualify intrabar CFD stop adapter on ML4T Engine before Stage 3 |
| 104 | `gbpusd_weekend_gap_reversal_cfd_20261015_v1` | `unknown` | `single_instrument_event` | `BLOCKED_PROTOCOL` | Qualify intrabar CFD stop adapter on ML4T Engine before Stage 3 |
| 105 | `hanna_spx_vix_corise_friday_reversal_v1` | `flat_descriptive` | `flat_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 106 | `hanna_spy_bear_gap_fade_us500_cfd_20261017_1600_v1` | `unknown` | `single_instrument_event` | `BLOCKED_PROTOCOL` | Qualify intrabar CFD stop adapter on ML4T Engine before Stage 3 |
| 107 | `oil_to_cad_daily_delayed_adjustment_20261015_v1` | `unknown` | `single_instrument_event` | `BLOCKED_PROTOCOL` | Qualify intrabar CFD stop adapter on ML4T Engine before Stage 3 |
| 108 | `quantinsti_spy_monthturn_one_day_v1` | `flat_descriptive` | `flat_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 109 | `robotwealth_earnings_open_gap_intraday_drift_v1` | `flat_descriptive` | `flat_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 110 | `robotwealth_gdx_gld_kalman_spread_v1` | `flat_descriptive` | `flat_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 111 | `robotwealth_spy_overnight_risk_premium_v1` | `flat_descriptive` | `flat_unqualified` | `BLOCKED_SPEC` | Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism |
| 112 | `us500_european_open_uncertainty_resolution_cfd_v1` | `unknown` | `single_instrument_event` | `BLOCKED_PROTOCOL` | Qualify intrabar CFD stop adapter on ML4T Engine before Stage 3 |
