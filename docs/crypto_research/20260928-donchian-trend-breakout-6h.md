# Crypto Research Run — 6h Donchian Trading-Range Breakout

## Conclusion

**REJECT.** The pre-registered canonical 336h channel failed the development gate with net Sharpe 0.4245. Although the 168h and 720h neighbors showed development Sharpes of 1.338 and 1.050, switching to them after observing these results would be post-hoc tuning. The 2024–2025 OOS was therefore not consumed.

## Source

- Gerritsen et al., *The profitability of technical trading rules in the Bitcoin market*, Finance Research Letters, DOI 10.1016/j.frl.2019.08.011.
- Bui & Nguyen, *Systematic Trend-Following with Adaptive Portfolio Construction*, arXiv:2602.11708.

## Pre-Registered Specification

Trading-range breakout state with channel windows 168h / **336h canonical** / 720h; prior-bar information only; 6h rebalancing at current open; inverse-volatility weights; 70% long-side gross / 30% short-side gross when both states exist; point-in-time top-80% lagged trailing-dollar-volume universe.

## Development Results

| Channel | Net Sharpe | Net return | Max DD |
|---:|---:|---:|---:|
| 168h | 1.338 | +343.8% | -52.8% |
| **336h** | **0.424** | **+30.2%** | **-77.0%** |
| 720h | 1.050 | +219.7% | -62.2% |

The fixed development gate required canonical Sharpe >0.70, positive canonical return, and at least two profitable neighboring windows. The canonical Sharpe condition failed.

## Data

19 Binance USDT perpetuals, 1h OHLCV, 2020–2025. SHA256: `f35452fab6b9a32ebc7e773162575ecf582e62ed5cdfaab200f6808060f5f6b8`.

## Methodology

Breakout states use prior close against channel extrema that exclude the prior close bar itself. Volatility and liquidity statistics are lagged. Orders are targeted every six hours at the current open. Development was evaluated after base 3 bps one-way execution cost.

## Results

OOS consumed: **No**.

Net OOS Sharpe / DSR / PBO / robustness: **N/A** because the pre-registered development gate failed.

## Failure Analysis

The family may contain useful neighboring configurations, but the exact candidate tested did not clear its preregistered canonical gate. Promoting the 168h or 720h variant now would contaminate the search. Any future breakout candidate must be independently justified and preregistered as a new trial.

## Multiple-Testing Audit

Previous trials: 27. New trials: 3. Cumulative: **30**.

## Decision

**REJECT**

## Provenance

Runner SHA256: `52064a4f7b9ab3d5358d60c884fdc47474822ef39666d9cac80a00f576d1e87a`.
