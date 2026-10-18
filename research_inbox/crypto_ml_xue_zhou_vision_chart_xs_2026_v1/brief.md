# crypto_ml_xue_zhou_vision_chart_xs_2026_v1

Source: Weijia Xue and Chunyang Zhou (2026), Predicting cryptocurrency returns with vision transformers: A look-ahead bias-free approach, Journal of Banking & Finance 190:107750. DOI: https://doi.org/10.1016/j.jbankfin.2026.107750 . Indexed abstract: https://econpapers.repec.org/article/eeejbfina/v_3a190_3ay_3a2026_3ai_3ac_3as037842662600124x.htm .

SOURCE_FACT: The authors study cross-sectional cryptocurrency return forecasts using images constructed from OHLCV-like data and ImageNet-pretrained vision transformers. They report a value-weighted long-short portfolio with weekly results. Original venue, exact coin universe, target label, image window, training cadence, cost assumptions and execution clock are UNKNOWN from the inspected abstract.

AUTHOR_TEST_UNVERIFIED: The indexed abstract reports mean weekly excess return 2.24 percent and annualized Sharpe 1.89, above their CNN and characteristic-sort comparators. This is neither replicated nor native ATS evidence. No local models or backtests were run.

LOCAL_INFERENCE: Nonlinear price-volume chart interactions may add information beyond a fixed momentum and size factor. A simpler alternative might explain the entire effect.

PROPOSED_ADAPTATION: Any 5m, 15m or 1h crypto-perp basket would be a separate new hypothesis, not original paper replication. First obtain exact source details and compare ViT against causal simple momentum and size sorting with the same point-in-time instruments, weights, clock and costs. No funding or basis predictor is proposed, but short financing and exchange fees remain relevant.

Scientific blockers: REQUIRES_TRAINING_WORKFLOW and BLOCKED_DATA. Native ATS Stage 2 does not train ViTs or prove out-of-fold predictions. A future workflow must establish model and preprocessing provenance, purged chronological OOF predictions, original value-weighted portfolio parity, and financing and shorting permissions. Source capture conveys NO execution authority.