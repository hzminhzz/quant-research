# Crypto Research Run — 1-week Cross-Sectional Momentum

## Conclusion

**REJECT.** The pre-registered Binance USDT perpetual 1h cross-sectional momentum candidate achieved net OOS Sharpe **0.515** after base costs, below the required 1.0 success threshold. Mean rank IC was **-0.0011**, 2025 performance deteriorated sharply, and removing the strongest contributor reduced Sharpe to **0.145**.

## Source

Victoria Dobrynskaya, “Cryptocurrency Momentum and Reversal,” *The Journal of Alternative Investments* 26(1), 2023. DOI 10.3905/jai.2023.1.189. Source: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3913263

## Hypothesis

Short-horizon relative strength may persist across crypto assets because information diffusion and capital rotation are gradual.

## Research Archetype

Cross-sectional factor.

## Pre-Registered Specification

Full rules and parameters were persisted before observing results in:
`run_log/crypto_research/runs/20260928-xs-momentum-1w-manifest.json`

Canonical formation horizon: 168h. Pre-registered neighboring horizons: 120h and 240h.

## Universe Construction

The actual local Binance 1h panel contained 19 usable USDT-margined perpetual symbols. Eligibility used only prior/current history, valid OHLCV, complete formation/holding prices, and trailing notional-volume ranking. No asset was selected from strategy PnL.

## Data

- Market: Binance USDT-margined perpetual futures
- Input: 1h OHLCV
- OOS evaluation: 2022-01-01 through 2025-09-30
- Sealed confirmation: 2025-10-01 onward was not consumed
- Assets evaluated: 19
- OOS daily observations: 1,368
- Weekly rebalances: 269

## ML4T Engineer Usage

No feature-catalog sweep was used. The candidate used only grouped trailing return and trailing notional volume, matching the pre-registered momentum mechanism.

## Signal Diagnostics

| Metric | Result |
|---|---:|
| Mean rank IC | -0.0011 |
| IC IR | -0.0035 |
| Mean extreme-bucket spread | +1.02% |

The factor diagnostic does not show a stable monotonic relationship.

## Methodology

Signals were formed from information available at the decision timestamp and portfolio exposure began only at the subsequent hourly open. Returns were aggregated into continuous daily portfolio returns for Sharpe calculation. Base, 2x, and 3x cost cases were evaluated.

## Results

| Metric | Base cost |
|---|---:|
| Net OOS Sharpe | **0.515** |
| Sortino | 0.842 |
| Total return | +42.9% |
| CAGR | +10.0% |
| Max drawdown | **-30.8%** |
| Profit factor | 1.076 |

Subperiod net Sharpe: 2022 **0.448**, 2023 **1.112**, 2024 **1.012**, 2025 through September **-1.198**.

## Asset Breadth / Contribution

Removing the strongest contributor, DOGEUSDT, reduced net OOS Sharpe to **0.145**. Excluding BTCUSDT and ETHUSDT produced Sharpe **0.321**.

## Robustness

| Test | Net OOS Sharpe |
|---|---:|
| Canonical 168h | 0.515 |
| 2x cost | 0.419 |
| 3x cost | 0.323 |
| 120h formation | -0.036 |
| 240h formation | 0.356 |
| Exclude BTC/ETH | 0.321 |
| Remove strongest asset | 0.145 |

## Failure Analysis

The candidate fails the success gate because Sharpe is below 1.0, IC is effectively zero, performance is unstable across subperiods, and the result is sensitive to its strongest contributor and neighboring formation horizons.

Funding was not modeled separately. Since the candidate already fails before adding that uncertainty, this omission does not change the rejection.

## Multiple-Testing Audit

Previous recorded trials: 3. New pre-registered variants/robustness trials: 5. Cumulative recorded trial count: **8**. DSR probability: **0.127**. Haircut Sharpe: **-0.490**. PBO is N/A because there are too few comparable CPCV winner-selection variants.

## Decision

**REJECT**

## Reproduction

Runner: `scripts/run_crypto_xs_momentum.py`

Data root: `/home/quant/dev/quant/ml4t-data/data/crypto/market/ohlcv_1h`

Manifest and structured result contain the exact settings and outputs required to reproduce the run.

## Provenance

Starting remote research SHA: `a29141fd7cb14f84fc37ae39e6586961d6076057`

Manifest fingerprint: `c076f3719299c6050b624273ea22f29ed8531c62a8e38b0002182f22e1ad833d`

Runner hash: `f5ce5a674f37301ff81afa241f818a2cb5038cad8d1d1e0ab283c290fff87c01`

Data-panel fingerprint: `5fbcdbb99488fe02ba4b9a249669e9eea42b483df861b6c6b8a72deb9014ae4e`
