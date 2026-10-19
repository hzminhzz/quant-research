# BTC Whale-Alert Cross-Coin Transmission — descriptive source capture

**Identity:** `crypto_xs_btc_whale_alert_transmission_magner_2025_v1`

**State:** `THESIS_CAPTURED` / `SOURCE_CAPTURE_ONLY` / not execution-approved.
**Original:** Nicolás Magner and Aliro Sanhueza, *The Moby Dick effect: Contagious Bitcoin whales in the crypto market*, *Finance Research Letters* 85 PB (2025), DOI [10.1016/j.frl.2025.107906](https://doi.org/10.1016/j.frl.2025.107906); [public indexed abstract](https://econpapers.repec.org/article/eeefinlet/v_3a85_3ay_3a2025_3ai_3apb_3as154461232501164x.htm). Only the public abstract was available; full paper methods were not verified.

## 1. SOURCE_FACT — original mechanism and causal clock

Authors construct an event indicator from BTC wallet-to-exchange and exchange-to-wallet transfers surfaced by *Whale Alert* Telegram. They study returns on **15 largest-market-cap cryptocurrencies**, via time-varying-parameter VAR at **1, 6 and 24 hours after the transfer**. Individual ticker membership, spot/perp instruments, chosen venues, event thresholds and post timestamp relative to block time remain **UNKNOWN**.

## 2. AUTHOR_REPORTED_TEST_UNVERIFIED — not executable alpha

The abstract claims significant BTC whale contagion mainly at **6h and 24h**. It does **not** provide a directionally signed tradable signal, long/short rules, costs, a basket backtest, or verified net P&L. No local return computations were performed.

## 3. LOCAL_INFERENCE and separate ADAPTATION_PROPOSAL

A BTC whale alert may contain inventory/information shock not fully reflected in *subsequent* altcoin prices. This is only a conjecture: a blockchain transfer is not synonymous with a market sell, exchange addresses may be mislabeled and market prices may respond before a Telegram alert is public. A *new*, independent future study could rank eligible alts conditional on **timestamp-proven public BTC whale alerts**, with candidate decisions on **completed 1h bars**, checking 6h/24h response. Neither long/short sign, counts, weights, leverage, rebalance nor exact rule is source-specified. Any future basket is **not the author's strategy**.

## 4. Alternative explanation and adverse source

[Dirk G. Baur and Lai T. Hoang, *Cryptocurrency spillovers and correlations: inefficiency and co-movement*, *Digital Finance* (2024)](https://link.springer.com/article/10.1007/s42521-023-00099-5) report that generic lagged crypto spillovers are small relative to contemporaneous correlations. Their generic-market null does not directly test BTC whale events, but creates an explicit high-priority falsification challenge. Synchronicity and common BTC beta may explain a naive event response without tradable delayed information.

## 5. Blocking source and trading-data questions

Preserve original event records and publication availability, historically known exchange-address classifications, PIT top-15 membership with listings/delistings and actual platform symbols, missing venue/quote conventions, market-impact and fee/spread/slippage estimates. If using perpetuals, financing must be measured as a cost when later authorized, **never as a predictive input**. Proposed 5m/15m signals and instant fills are not supported by the cited abstract.

**Falsifier for any later frozen specification:** conditional return/rank evidence beyond synchronized BTC movements and after-cost, alert-available timing disappears or cannot be causally executed. Research trials, native ATS stages, orders and holdout access during this capture: **0**.
