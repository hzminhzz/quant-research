# Peng, Khushi & Poon (2026): CryptoGAT cross-asset graph attention

**THESIS_CAPTURED — SOURCE_CAPTURE_ONLY.** Original author paper: https://arxiv.org/abs/2606.27670 ; implementation: https://github.com/FanBroWell/CryptoGAT . Source evidence from author HTML and README, **not** independently executed code or models.

## Source mechanism

The authors propose that **spatial relationships across cryptocurrencies** carry more useful price-prediction information than deeper temporal networks. They build a trailing-price Pearson-correlation graph; a GAT learns how strongly to weight other coins, while FGAT mixes indicators into graph representations. Inputs are price/volume, not funding.

The source uses 66 Binance USDT-denominated coins selected with continuous daily coverage from April 2023 to January 2026, a 30-day lookback, chronological 60:20:20 model split, next-day return forecasts, and an **equal-weight LONG-ONLY top-five daily portfolio**. The claimed daily cross-sectional IC (GAT 0.037; FGAT 0.047) and portfolio Sharpe (GAT 3.128 no cost; 2.759 at 10bps/side) are original paper claims. GAT's modeled maximum drawdown is approximately 39% with costs, incompatible with tight prop evaluation risk unless independently redesigned.

## ATS compatibility and falsification

The original study **does not demonstrate a dollar-neutral long/short basket**. Adding shorts would be a separate adaptation, not source fidelity. Current native ATS allocation is fixed top/bottom with neutrality, so original strategy transfer is BLOCKED_PROTOCOL. GNN execution, inference graph construction and model-fit cutoff semantics would also require a frozen callback/model artifact with chronological OOF evidence before an executable handoff.

Main red flags: **full-window continuously listed coin selection (survivorship)**, risk that graph edges learn from future prices, missing venue/product equivalence, and paper's 1D clock rather than local 1h signals. A defensible null is lagged-return and simple correlation-weighted peer momentum in the exact same PIT universe.

No training, OOF, SHAP, IC, backtest, ATS runner interaction, protected reads or orders occurred.
