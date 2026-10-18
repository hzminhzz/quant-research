# Hourly ML source discovery — 2026-10-18, bounded batch 12

Status: SOURCE_CAPTURE_ONLY. No training, empirical IC, backtests, ATS runner interactions, protected reads or orders.

## Repository and schema
- Inspected VPS checkout /home/quant/dev/quant/quant-research, AGENTS.md, research_inbox_operations.md, research_inbox_factory_operations.md, src/engine/research_handoff.py, thesis_ingest.py, src/workbench.py and src/models.py.
- Original local main HEAD 49c0d70f21518e0963780b6b3c93f0ec7afe93e0 (3 ahead); remote origin/main 37a6e5a5b21edd5d306f58914e454b0f097450cd, 112 thesis.yaml files. Neither changed.
- Isolated detached clean worktree based on origin/main: /home/quant/.devspace/worktrees/quant-research-cfe3a6fe. Source staging is outside the active inbox.
- Native flat handoff uses src/engine/research_handoff.py. No obsolete research_capture.py commands. Handoff validity is NOT execution approval.
- The existing ATS path does not train/fine-tune Vision Transformers or independently establish chronological OOF prediction provenance.

## Source screen (22 distinct identities; most screened at abstract/README level)
Outcome codes: NEW=source captured, DUP=economic/source family already represented in main or historical draft, DEFER=missing incremental tradeable ML evidence or incompatible protocol, ADVERSE=negative scientific/practical evidence.

| # | Original source | Screening | Distinct reason |
|---|---|---|---|
| 1 | [Xue & Zhou (2026), chart Vision Transformers](https://doi.org/10.1016/j.jbankfin.2026.107750) | NEW | Nonlinear image-based crypto cross-sectional value-weighted long-short signal vs CNN and simple characteristic sorts. |
| 2 | [Cakici et al. (2024)](https://doi.org/10.1016/j.irfa.2024.103244) | DUP | Already crypto_ml_cakici; simple models competitive, illiquidity concentration. |
| 3 | [Anastasopoulos et al. (2026)](https://doi.org/10.1016/j.finmar.2026.101047) | DUP | Already global order-flow nonlinear crypto forecast in main. |
| 4 | [Fieberg et al. (2025), CTREND](https://doi.org/10.1017/S0022109024000747) | DUP | Already multi-horizon learned crypto price/volume factor. |
| 5 | [Yang (2025), crypto rank NN](https://arxiv.org/abs/2512.08124) | DUP | Existing rank MLP source; reported portfolio long-only. |
| 6 | [Ma, Bao & Wen (2026)](https://arxiv.org/abs/2602.23762) | DUP | Existing cross-chain attention substitution family; original primarily on-chain spillover. |
| 7 | [Guo, Sang, Tu & Wang (2024)](https://doi.org/10.1016/j.jedc.2024.104863) | DUP | Delayed cross-coin returns and sparse models overlap information-delay family. |
| 8 | [Qiu & Fang (2025)](https://arxiv.org/abs/2510.20066) | DUP | Previous ML factory capture/draft for liquidity-risk classification; forecast-label ambiguity. |
| 9 | [Guidolin & Ionta (2026)](https://doi.org/10.1016/j.intfin.2026.102285) | DEFER | Weekly on-chain/search-factor predictive sorting; no demonstrated trained nonlinear ML increment. |
| 10 | [Zhai (2026)](https://doi.org/10.2139/ssrn.6566940) | ADVERSE | Single-ETH live ML performance reportedly near random despite historical AUC; self-report unverified. |
| 11 | [Hao, Chen & Qi (2026)](https://doi.org/10.3390/a19080704) | DEFER | Fixed-odds event-contract selective prediction, no ATS return-basket protocol. |
| 12 | [Saidane & Ben Mohamed (2026)](https://doi.org/10.1002/for.70159) | DEFER | Crypto VaR/ES mixture model, risk protocol distinct from return IC. |
| 13 | [Qizhao Chen (2026)](https://doi.org/10.1007/s42521-026-00187-2) | DEFER | VADER/Gemini sentiment and optimizer, incremental supervised ML trading edge unisolated. |
| 14 | [Huang et al. (2026)](https://doi.org/10.1002/ijfe.70012) | DEFER | Deep-learning CVaR utility allocation, incompatible with simple return-ranking qualification. |
| 15 | [Wang, Huang & Liao (2026)](https://doi.org/10.1016/j.frl.2026.109776) | DEFER | Single-BTC VMD/CNN price forecast, lookahead in decomposition to establish. |
| 16 | [Zhao, Crane & Bezbradica (2026)](https://doi.org/10.1111/exsy.70343) | DEFER | Multi-scale transformer for three-asset price levels; tradable long/short extension unproven. |
| 17 | [FionaNi crypto momentum and reversal](https://github.com/FionaNi-DS/crypto-statistical-arbitrage) | ADVERSE | Author reports 2025 untouched validation failure of weekly momentum. |
| 18 | [avi-mukesh crypto quant](https://github.com/avi-mukesh/crypto-quant-project) | ADVERSE | Strong simple momentum/attention effect claims, but retrospective market-cap universe and source-time coverage require audit. |
| 19 | [Bieganowski & Slepaczuk (2026)](https://arxiv.org/abs/2602.00776) | DUP | Existing prior short-horizon L2 CatBoost source capture; three-second protocol. |
| 20 | [Garcia Seuma (2026)](https://arxiv.org/abs/2607.27070) | ADVERSE | No event-invariant per-cascade precursor across seven liquidations. |
| 21 | [RIVF BTC multimodal 15m (2025)](https://doi.org/10.1109/RIVF68649.2025.11365170) | DEFER | Single BTC direction/uncertainty classifier, no substantiated basket economics. |
| 22 | [Liu & Sun, MoFE (2026)](https://arxiv.org/abs/2608.17342) | DEFER | High-complexity Fourier mixture price forecasting without transparent basket/cost benchmark. |

Counts: 22 screened; 1 NEW; 8 DUP; 9 DEFER; 4 ADVERSE. Deepened: Xue (source capture), Guidolin (factor-versus-ML), Zhai (adverse live-report). No funding, basis or carry-alpha idea admitted.

## New candidate
crypto_ml_xue_zhou_vision_chart_xs_2026_v1 staged as two safe regular UTF-8 files under research_staging/. Indexed abstract shows ImageNet-pretrained vision transformers forecast crypto cross-sectional returns using chart images from OHLCV-like data, with a value-weighted long-short portfolio. SOURCE_REPORTED_TEST (unverified): weekly excess return 2.24 percent, Sharpe 1.89, beating CNN/characteristic portfolios. Local conjecture: nonlinear patterns might add to simple momentum and size. Original asset membership, spot/perp venue, target/forecast clock, exact costs and model training schedule not verified. No direct full-paper or code inspection.

Future scientific requirements: same-universe same-cost simple momentum and size benchmarks; PIT constituents; fold-local image pipeline and model selection; time-ordered purged OOF model prediction provenance; labels/availability; source value-weighted versus ATS allocation parity; short borrow/perp financing and prop account restrictions. No native ML training or empirical work occurred.

## No-execution accounting
Model training=0. OOF or other predictions=0. Empirical backtests=0. Stage 1-4 or ATS runner interactions=0. Protected/holdout reads=0. Orders=0. Source-only handoff structure and SHA-256 checks are permitted.
