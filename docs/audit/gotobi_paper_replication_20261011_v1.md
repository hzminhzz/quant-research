# Gotobi paper replication - native USDJPY pre-fix MVP

**Decision: REJECTED_OR_INCONCLUSIVE. EXPLORATORY; NOT_APPROVED for live trading.**

## Source vs claims

The uploaded 1.0.0 strategy specification cites 2004-2024, but the
Alpha in Academia article corrected July 27, 2026 uses 2006-2025,
1,175 complete events, and reports +4.54 gross pips per trade for
03:00 JST open to 09:55 minute bar close. Its publisher specifically
does not claim observed customer orders, dealer hedges, non-Gotobi
controls, or executable broker spreads. The attached LightGBM, passive
execution, intraday spreads, and 16 production controls are proposals,
not source-tested profits.

## Local method

Canonical LSE UTC-open one-minute USDJPY, 2020-Aug2026 only.
Official Japanese bank calendar inherited unchanged. Every minute
02:58-09:56 required. Primary 03:00 native next-bar market BUY,
09:54 native next-bar market SELL; 1 pip all-in fixed adverse fill.
Fixed USD10,000 base, USD10,000 reference equity, no compounding.
JPY native ledger; exit-price USD conversion; cash and ordinary
same-window long as baselines. This pre-fix exit is intentionally
earlier than the article's 09:55-bar CLOSE and is not claimed exact
publication-rule replication. Native 09:55 and 09:56-open sensitivity
checks are separately recorded.

## Primary outcomes

- Eligible: 999 of 1627 banking dates
  (61.4%);
  Gotobi 306, ordinary 693.
- Gotobi gross +2.687 pips/trade, net +1.687,
  USD PnL +429.24, net PF 1.213,
  flat-inclusive daily Sharpe 0.488.
- Ordinary gross -0.228, net -1.228 pips/trade,
  USD PnL -525.18.
- Gotobi net HAC mean: +1.403 USD/trade,
  95% CI [-0.979, +3.784],
  p=0.2473.
- Controlled Gotobi minus ordinary: +2.544 USD/trade,
  HAC 95% CI [-0.789, +5.878],
  Holm2 p=0.269.
- Development 2020-23: +524.78 USD;
  retrospective 2024-25: -190.06 USD;
  inspected 2026 Jan-Aug: +94.53 USD.
- At 1.5 pips, net USD +314.54;
  at 2.0 pips, +199.85.
- Frozen checks: {"absolute_hac_lower_gt_0": false, "calendar_holm_p_lt_05": false, "completeness_ge_70pct": false, "net_1p5pip_gt_0": true, "net_usd_gt_0": true, "stable_2024_2025": false, "stable_2026": true}.

## Interpretation

No September-October 2026 protected observations were loaded.
All 2020-Aug2026 observations have already been examined in previous
Gotobi programs. Low early-morning bar coverage and unknown executable
broker costs constrain any inference beyond the retained cohort.
No customer-order-flow measurements or truly independent non-price
predictive features are present. HOLM2 applies only to this session;
full historical selection adjustment is not reproducible.

## Reproduction

- YAML: config/research_sessions/gotobi_paper_replication_20261011_v1.yaml
- Runner: scripts/run_gotobi_paper_replication_20261011_v1.py
- Frozen CLI: run_log/gotobi_paper_replication_20261011_v1/freeze_init.json
- Source identities: run_log/gotobi_paper_replication_20261011_v1/source_manifest.json
- Native ledgers: run_log/gotobi_paper_replication_20261011_v1/runs/*/
- Event, cost, audit, trial evidence: run_log/gotobi_paper_replication_20261011_v1/T*/result.json
- Native order and source-price oracle: 5058 orders checked,
  max source error 1.42e-14 JPY,
  max cash reconciliation error 9.17e-09 JPY.

**Next experiment:** prospective broker executable USDJPY quotes and market
fills at 02:59-09:55 JST, with Gotobi/ordinary comparison and previously
fixed entry/exit decisions. Do not unlock the September-October 2026
protected period to retune this mechanism.
