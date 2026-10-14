# Milkman Trades: source-qualified research intake (2026-10-14)

Status: INTAKE ONLY. Not a native ML4T backtest, parity proof, or terminal six-strategy qualification. All candidates remain EXPLORATORY / NOT_APPROVED. No evaluation data from 2025-2026 was accessed for this program.

## Environment and source provenance

Repository at intake: branch `local-first-main-sync-20261014`, HEAD `144132cd3986929aa5f1367d004be1c8bfd01d59`. Dirty worktree with many unrelated artifacts: do not reset, clean, or bulk stage. Source website: https://milkmantrades.com/#strategies (HTML directly retrieved on 2026-10-14). Original HTML bytes and SHA256 hashes **not yet archived**. Downloadable packages identified but **not yet fetched, hashed or read**; no source-code numerical parity is claimed.

Installed package versions (observed via Python metadata): ml4t-engineer 0.1.4; ml4t-backtest 0.1.7; ml4t-data 0.1.0b14; ml4t-models 0.1.4. `compute_features(data,features,*,group_col=None,timestamp_col=None,assume_sorted=False)` and native `Engine(feed,strategy,config)` confirmed. Feature catalog enumeration and canonical data qualification remain outstanding.

## Candidate source inventory (source claims, NOT reproduced results)

1. **Morning Dip Limit** — https://milkmantrades.com/morning-dip-limit.html
   Package: https://milkmantrades.com/data/morning-dip-limit-package.zip .
   NQ 1-second bars aggregated to 3-minute UTC-grid bars; simple ATR14, efficiency ratio ER15 <= 0.35; 09:00–11:00 CT signal; buy limit one ATR below last 3-minute close armed one second later; require one-tick penetration, nine-minute expiry; take profit at signal candle midpoint; 1.5 ATR stop, 15-minute time cap, 11:00 CT flat. One position/order at a time. Author reports Jan–Sep 2026 398 trades average across offsets, +$34,986. **Crucial negative out-of-period evidence**: author reports 2010–2025 total -$48,600 (start 0); 2010–2019 negative every year; 2025 materially offset-dependent. Exact replication requires genuine 1-second NQ data and fill semantics. A 1-minute CFD adaptation cannot replicate same-second fill/order sequencing.

2. **Legend's Buy Day** — https://milkmantrades.com/legends-buy-day.html
   Package: https://milkmantrades.com/data/legends-buy-day-package.zip ; ledger: https://milkmantrades.com/data/legends-buy-day-trades.csv .
   ES session 18:00 previous evening to 17:00 ET, full-session close from 16:59 bar; fresh exactly-three lower daily closes, predecessor not lower; buy 18:00 ET Globex open, sell 09:30 ET open; no stop, no target; 0.5 ES point roundtrip. Author reports 230 trades, +$50,780 on 1 ES, PF 1.83, 61% wins on 2008–2026. Authors disclose 616-cell search and low deflated Sharpe (0.02). Exact clock, 1-minute session data, execution costs, and count parity required.

3. **Legend's EMA** — https://milkmantrades.com/legends-ema.html
   Package: https://milkmantrades.com/data/legends-ema-package.zip ; ledger: https://milkmantrades.com/data/legends-ema-trades.csv .
   NQ 1-minute RTH 09:30–15:59 ET; 15m EMA20; preceding trend day uses |close-open|/(high-low) at >= full-sample 80th percentile; prior session never touched its own 15m EMA; next session open short/long toward EMA and rest target at EMA of last completed 15m bar; flatten at 15:59 ET, no stop, 1.25 NQ points RT. Author reports 270 trades, PF 2.19, +$86,119 over 2008–Aug 2026. **Lookahead blocker for original percentile method:** full 2008–2026 population percentile is not available in 2008. A causal expanding/prior-training percentile is a separately specified ADAPTED trial, not exact parity.

4. **Bilbo Box v2** — https://milkmantrades.com/bilbo-box-replication.html ; companion rules: https://milkmantrades.com/bilbo-box-options-v2.html .
   Package: https://milkmantrades.com/data/bilbo-box-replication-package.zip ; ledger: https://milkmantrades.com/data/bilbo-box-replication-trades.csv .
   5-minute 04:00–19:55 ET stock bars aggregated to hourly extended-hours, Phase Oscillator compression, grey BB21 inside 2*ATR14 Keltner with extra 1.854 expansion/shrinking-gap exception (exact code essential); box first 5 grey hours, frozen, live 10 calendar days; first out-of-compression hourly close above box high, between 10:00–15:00 ET; previous RTH close >= daily EMA21; two-sided option spread <= 5% of mid; NO volume floor. Buy call ~spot+0.75*prior ATR14, expiry 21–37 days; underlying-price 5-minute stop, ATR-armed trailing, ten trading-day cap. Corrected source claims 1,374 options trades, PF 1.36; old 1,031 was erroneous. **Separate objects:** underlying signal parity may be tested with stocks; option-return parity BLOCKED_DATA without historical NBBO/option contracts and licensed source inputs.

5. **Swing Golden Gate** — https://milkmantrades.com/swing-gg-stocks.html .
   Monthly prior-close anchor and prior-month Wilder ATR14; short after downside -38.2% gate opens while prior daily close above EMA21, resting sell-stop at -61.8% completion; target -100%, stop monthly pivot, flatten month end; one trade/name/month. Author reports 349 build trades with +0.56% net mean/trade (2000–2024) and 47 forward trades +1.19% net mean/trade (2025–Jul 2026). Source universe 17 stocks, stock corporate actions and point-in-time universe essential.

6. **Daily Bilbo Boxes** — https://milkmantrades.com/bilbo-daily.html .
   Daily Phase Oscillator compression (exact implementation needed), first 5 grey sessions (or fewer if compression ends), buy-stop at locked box high up to 20 trading sessions while preceding close > EMA21; invalidate if box low touched first; initial stop box low; trailing stop max(previous stop, preceding daily EMA50), gap-honest stop execution; optional 3-day scratch is a separate version. Author reports 1,269 trades and PF 2.08 on 17-name discovery universe, and a separate 30-name check. No evidence of source package from visible main article links. Exact PO implementation and PIT stock universe required. This is NOT independent from Bilbo v2's compression signal family even though its horizon and instruments differ.

## Options-specific sources (separate, not two additional independent signals)

- https://milkmantrades.com/atr-premium-selling.html — SPXW put credit spread: weekly previous close minus previous Wilder ATR14 for short strike, 50-point wing, first weekly trading day ~10:00 ET, PM settlement, historical NBBO required. It is a distinct options mechanism, not a Bilbo derivative.
- https://milkmantrades.com/bilbo-box-options-v2.html — earlier description of the same Bilbo Box v2 signal and options execution. The accompanying corrected replication page overrides the stale 1,031-trade headline.

## Next evidence gates

1. Archive every source HTML and public ZIP, write UTC retrieval times and SHA256, extract and inspect included source code/reference CSVs; resolve source contradictions in frozen machine-readable rules.
2. Inspect canonical local data and feature catalog without touching /home/quant/dev/quant/ml4t-data; check 1s NQ, 1m ES/Globex, ETH/RTH stock OHLCV, PIT membership/corporate actions, NBBO.
3. Use native ML4T feature registry for supported indicators; verify oscillator and ER extensions against original code, and check future-bar perturbation, warmup, DST, and bar-close availability.
4. Register six distinct research objects/trials; use pre-2025 data only. Keep existing allocation evaluation 2025–2026 locked.
5. Native Engine broker execution with bounded sequential heavy jobs, independent trade/fill/cash/equity review, and parity diffs. No homemade vectorized PnL.
6. Only for qualified equity ledgers, develop daily marked-equity diversification versus four frozen incumbent strategies.
7. Record terminal `REPLICATED`, `ADAPTED`, `FAILED`, `INCONCLUSIVE`, or `BLOCKED_DATA` with evidence. **None of the six has such a supported terminal label yet**.

No promotion, optimizer search, live orders, or reserved holdout access authorized.
