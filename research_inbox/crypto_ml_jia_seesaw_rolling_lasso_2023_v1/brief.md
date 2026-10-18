# Jia et al. (2023): Rolling LASSO crypto seesaw cross-predictability

**Source-captured only:** No model training, backtest or ATS stages performed.

Primary publisher: `https://doi.org/10.1016/j.jempfin.2023.101428`. Yuecheng Jia, Yangru Wu, Shu Yan and Yuzheng Liu, *Journal of Empirical Finance* (2023).

## Verifiable source strategy

Authors report a **negative** five-minute lead/lag effect: positive large-coin shocks forecast **lower** returns on other coins, unlike ordinary equity positive lead-lag. A time-varying rolling **LASSO** forecasts each next-period coin return using past cross-coin return information. It ranks SO forecast values and builds **long top forecast quintile, short bottom forecast quintile**. Publisher text reports gross mean spread exceeding 5 bp per 5-minute formation on BITFINEX, above 6bp on HUOBI, with authors also claiming transaction-cost robustness. Those are study claims only.

## Economic hypothesis and rival thesis

Author mechanism involves money rotating toward suddenly hot large coins, leaving lagging other coins under pressure. The existing `crypto_xs_information_delay_basket_v1` instead conjectures *positive altcoin catch-up* after BTC signals over 48 hours. Both involve information transmission, but the **sign, 5-minute horizon and learned conditional spillover model differ**; count as a distinct conditional ML source, not evidence that the earlier 48h hypothesis works.

## Practical barriers

Original venues BITFINEX and HUOBI (2018–2021), not verified local Binance USDT perpetual panel. Five-minute turnover and 5bps gross before fees are challenging for many prop-firm CFDs. Do not invent an ATS-compatible 1h clock, fees or historical coin set. Exact LASSO penalty, source matching and fill model require the full paper/data.

Future-only validation: frozen chronological OOF rolling fit, label maturity/purge, tradeable coin historical identity, matched negative large-coin linear baseline, realized after-cost 5m economics with short availability and daily drawdown rules. **No funding alpha.**
